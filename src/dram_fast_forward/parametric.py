"""Bounded symbolic execution of competing READ producers, not trace fitting.

Each comparison splits a Presburger parameter domain. A successful leaf is a
whole command sequence with affine times. No reference schedule is an input.
Lengths and initial row layouts are finite structural variants; arrival offsets
are symbolic integers. Exhausted budgets leave uncovered domains for fallback.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time
from .polyhedral import ISL


@dataclass(frozen=True)
class Affine:
    coeff: tuple[int, ...]
    constant: int = 0

    def __add__(self, other):
        if isinstance(other, int): return Affine(self.coeff, self.constant + other)
        return Affine(tuple(a+b for a,b in zip(self.coeff,other.coeff)), self.constant+other.constant)

    def __sub__(self, other):
        if isinstance(other, int): return self + (-other)
        return Affine(tuple(a-b for a,b in zip(self.coeff,other.coeff)), self.constant-other.constant)

    def expression(self):
        return str(self.constant)+''.join(f'{a:+d}*x{i}' for i,a in enumerate(self.coeff) if a)

    def serial(self): return [self.constant, *self.coeff]


class Fork(Exception):
    def __init__(self, positive, negative): self.children=(positive,negative)


class SymbolicPath:
    def __init__(self, isl, dimension, constraints):
        self.isl,self.dimension,self.constraints=isl,dimension,tuple(constraints)
        self.queries=0

    def set_text(self, extra=()):
        names=','.join(f'x{i}' for i in range(self.dimension))
        return '{ ['+names+'] : '+' and '.join(f'({c})' for c in self.constraints+tuple(extra))+' }'

    def le(self, a, b):
        d=a-b
        if not any(d.coeff): return d.constant<=0
        yes=d.expression()+'<=0'; no=d.expression()+'>=1'
        self.queries+=2
        pos=not self.isl.empty(self.set_text((yes,)))
        neg=not self.isl.empty(self.set_text((no,)))
        if pos and neg: raise Fork(self.constraints+(yes,),self.constraints+(no,))
        if not pos and not neg: raise RuntimeError('Empty symbolic path')
        return pos

    def maximum(self, *args):
        best=args[0]
        for other in args[1:]:
            if self.le(best,other): best=other
        return best

    def minimum(self, args):
        best=args[0]
        for other in args[1:]:
            if self.le(other,best): best=other
        return best


def initial_rows(program, length, profile):
    rows=[-1]*8
    if profile!='closed':
        for producer in program['producers']:
            for local in producer['local_addresses'][:length]:
                bank=(local//1024)%8
                if rows[bank]<0: rows[bank]=local//8192+(profile=='conflict')
    return rows


def execute(program, model, length, profile, path):
    """Translate frozen active-before-read policy and timing-history semantics.

    Admission is bounded to <=64 total reads (actual queue admits at least 64).
    No write, refresh or unknown feedback is compiled. Region admission rejects
    completion at/after refresh; the original simulator then executes the case.
    """
    d=path.dimension; zero=Affine((0,)*d); neg=zero-1
    commands=model['commands']; ACT,PRE,RD=[commands.index(c) for c in ('ACT','PRE','RD')]
    rows=initial_rows(program,length,profile)
    requests=[]
    for p,producer in enumerate(program['producers']):
        offset=Affine(tuple(producer['offset_coefficients']))
        for i,local in enumerate(producer['local_addresses'][:length]):
            requests.append(dict(id=p*1000+i,addr=local,bank=local//1024%8,row=local//8192,
                                 arrival=offset+program.get('arrival_gap',0)*i))
    if len(requests)>64: raise ValueError('Finite admission proof requires <=64 requests')
    # Stable insertion sort is symbolic: equal arrivals retain producer order.
    future=[]
    for r in requests:
        at=len(future)
        while at and not path.le(future[at-1]['arrival'],r['arrival']): at-=1
        future.insert(at,r)
    ready=[[neg]*len(commands) for _ in range(9)]
    history=[[[] for _ in commands] for _ in range(9)]
    edges={c:[] for c in (ACT,PRE,RD)}
    for level,previous,following,latency,window,sibling,blocked in model['constraints']:
        if previous not in edges: continue
        if level not in (0,3) or sibling or blocked>0:
            raise ValueError('Unsupported resource effect')
        edges[previous].append((level,following,latency,window))
    active=[]; normal=[]; now=zero; emitted=[]; decisions=0

    def preq(r):
        return ACT if rows[r['bank']]<0 else RD if rows[r['bank']]==r['row'] else PRE

    def candidate(queue,t):
        winner=None
        for r in queue:
            c=preq(r); available=path.maximum(ready[0][c],ready[r['bank']+1][c])
            if path.le(available,t):
                if winner is None or not path.le(winner['arrival'],r['arrival']): winner=r
        return winner

    while future or active or normal:
        decisions+=1
        if decisions>4096: raise RuntimeError('Symbolic event budget exceeded')
        while future and path.le(future[0]['arrival'],now): normal.append(future.pop(0))
        t=now+1
        r=candidate(active,t); queue=active
        if r is None: r=candidate(normal,t); queue=normal
        if r is not None:
            c=preq(r)
            # Frozen controller invalidates the chosen closing command; it does
            # NOT reschedule another normal request in the same cycle.
            if c==PRE and any(a['bank']==r['bank'] for a in active): r=None
        if r is None:
            transitions=[]
            if future: transitions.append(future[0]['arrival']+1)
            for q in (active,normal):
                for item in q:
                    c=preq(item); a=path.maximum(ready[0][c],ready[item['bank']+1][c])
                    if not path.le(a,t): transitions.append(a)
            if not transitions: raise RuntimeError('No progress under supported policy')
            now=path.minimum(transitions)-1
            continue
        c=preq(r); emitted.append([r['id'],c,t.serial()])
        for node,level in ((0,0),(r['bank']+1,3)):
            history[node][c].insert(0,t)
            for lev,following,latency,window in edges[c]:
                if lev==level and len(history[node][c])>=window:
                    ready[node][following]=path.maximum(ready[node][following],history[node][c][window-1]+latency)
        if c==ACT:
            rows[r['bank']]=r['row']; queue.remove(r); active.append(r)
        elif c==PRE: rows[r['bank']]=-1
        else: queue.remove(r)
        now=t
    return dict(commands=emitted,final_rows=rows,event_decisions=decisions)


def compile_program(program, model, lengths, profiles, max_regions=256):
    d=len(program['bounds']); start=time.process_time(); leaves=[]; unresolved=[]; stats=[]
    bounds=tuple(c for i,(lo,hi) in enumerate(program['bounds']) for c in (f'x{i}>={lo}',f'x{i}<={hi}'))
    with ISL() as isl:
        for length in lengths:
            if any(len(p['local_addresses'])<length for p in program['producers']): raise ValueError('Short producer')
            for profile in profiles:
                pending=[bounds]; count=queries=attempts=0; before=time.process_time()
                while pending and count<max_regions:
                    constraints=pending.pop(); path=SymbolicPath(isl,d,constraints); attempts+=1
                    try:
                        result=execute(program,model,length,profile,path)
                        leaves.append(dict(length=length,profile=profile,guard=list(constraints),**result)); count+=1
                    except Fork as fork: pending.extend(reversed(fork.children))
                    queries+=path.queries
                unresolved.extend(dict(length=length,profile=profile,guard=list(x)) for x in pending)
                stats.append(dict(length=length,profile=profile,regions=count,unresolved=len(pending),
                                  symbolic_runs=attempts,isl_queries=queries,cpu_s=time.process_time()-before))
    return dict(version=1,algorithm='bounded path-sensitive symbolic policy execution',program=program,model=model,
                regions=leaves,unresolved=unresolved,stats=stats,compiler_cpu_s=time.process_time()-start,
                scope='symbolic offsets; finite lengths/initial-row profiles; no oracle; unknown arrivals and refresh are boundaries')


def emit_header(artifact):
    """Runtime performs entry dispatch and affine evaluation, no queue scheduling."""
    program=artifact['program']; lines=['#pragma once','namespace parametric_schedule {',
      'struct Command { int id,command; long long cycle; };',
      'inline bool select(int length,int profile,const std::vector<long long>& x,std::vector<Command>& out) {',
      f'if(x.size()!={len(program["bounds"])}) return false;']
    profiles={'closed':0,'hit':1,'conflict':2}
    for region in artifact['regions']:
        guards=[]
        for c in region['guard']:
            for i in reversed(range(len(program['bounds']))): c=c.replace(f'x{i}',f'x[{i}]')
            guards.append('('+c+')')
        lines.append(f'if(length=={region["length"]} && profile=={profiles[region["profile"]]} && '+ ' && '.join(guards)+') {')
        for rid,cmd,time_expr in region['commands']:
            expr=str(time_expr[0])+''.join(f'{v:+d}*x[{i}]' for i,v in enumerate(time_expr[1:]) if v)
            lines.append(f'out.push_back({{{rid},{cmd},{expr}}});')
        lines.append('return true; }')
    lines.extend(['return false; }',f'inline constexpr const char* program_json=R"PROGRAM({json.dumps(program,separators=(",",":"))})PROGRAM";',
                  f'inline constexpr const char* constraints_json=R"MODEL({json.dumps(artifact["model"]["constraints"],separators=(",",":"))})MODEL";', '}'])
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for n in ('program','model','output'): parser.add_argument('--'+n,type=Path,required=True)
    parser.add_argument('--lengths',type=int,nargs='+',default=[4,8,12])
    parser.add_argument('--profiles',nargs='+',choices=['closed','hit','conflict'],default=['closed','hit','conflict'])
    parser.add_argument('--max-regions',type=int,default=256)
    args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=False)
    a=compile_program(json.loads(args.program.read_text()),json.loads(args.model.read_text()),args.lengths,args.profiles,args.max_regions)
    a['source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (args.output/'artifact.json').write_text(json.dumps(a,separators=(',',':'))+'\n')
    header=emit_header(a); (args.output/'parametric_schedule.hh').write_text(header)
    print(json.dumps(dict(regions=len(a['regions']),unresolved=len(a['unresolved']),cpu_s=a['compiler_cpu_s'],stats=a['stats'])))


if __name__=='__main__': main()
