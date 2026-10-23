"""Compile a fixed-order diagnostic DAG, never an online speedup claim.

Inputs: reference-selected command order, admissions, refresh injection, optional
observed policy branches, and pending enqueue order. Actual command/callback
timestamps are verification targets only, not graph release constraints.
"""
import argparse
from array import array
from collections import Counter,defaultdict,deque
import gzip
import json
import os
from pathlib import Path
import struct
import subprocess
import time


def rows(path):
    with path.open() as f:return [json.loads(line) for line in f if line.strip()]


class Graph:
    def __init__(self):
        self.release=array('q');self.offset=array('Q',[0]);self.pred=array('I');self.delay=array('i');self.expected=array('q');self.kinds=Counter()
    def add(self,release,edges,expected):
        node=len(self.release);self.release.append(release);self.expected.append(expected)
        merged={}
        for previous,delay,kind in edges:
            if previous is None:continue
            assert previous<node,(previous,node)
            merged[previous]=max(delay,merged.get(previous,delay));self.kinds[kind]+=1
        for previous,delay in merged.items():self.pred.append(previous);self.delay.append(delay)
        self.offset.append(len(self.pred));return node
    def save(self,path):
        with path.open('wb') as f:
            f.write(struct.pack('<QQ',len(self.release),len(self.pred)))
            for data in [self.release,self.offset,self.pred,self.delay]:data.tofile(f)
        with path.with_suffix('.expected.bin').open('wb') as f:self.expected.tofile(f)


def compile_graph(reference,events,with_policy,omit_shared_bus=False):
    started=time.process_time();selected=rows(reference/'selected.jsonl');priority=rows(reference/'priority.jsonl');policies=rows(reference/'policy.jsonl')
    timing=json.loads((reference/'timing.json').read_text());incoming=defaultdict(list)
    for level,previous,following,delay,window,sibling,offset in timing['constraints']:
        if sibling or offset>0:raise ValueError('unsupported timing dependency')
        if omit_shared_bus and timing['shared_bus'] and level==0 and previous in (3,4) and following in (3,4):continue
        incoming[level,following].append((previous,delay,window))
    stream=[];admission={};callbacks={};fmt=struct.Struct('<12q')
    opener=gzip.open if events.suffix=='.gz' else open
    with opener(events,'rb') as f:
        while data:=f.read(fmt.size):
            event=fmt.unpack(data);stream.append(event)
            if event[0]==1 and event[7]:admission[event[1],event[4]]=event[3]
            if event[0]==3:callbacks[event[1],event[4]]=event[3]
    graph=Graph();histories=defaultdict(list);serial={};last_pop={};phase={};policy_index=0
    pri=defaultdict(deque)
    for row in priority:pri[row[0],row[1]].append(row)
    command_nodes=[];final={};release_sources=Counter()
    for index,row in enumerate(selected):
        d,ci,actual,cmd,final_cmd,type_id,rid,arrived,address,buffer_kind=row
        # Phase records provide decisions/queue IDs. Their observed timestamp
        # orders the records only; it is never used as a graph release bound.
        while policy_index<len(policies) and tuple([policies[policy_index][2],*policies[policy_index][:2]])<=tuple([actual,d,ci]):
            pd,pc,observed,write_mode,reads,writes=policies[policy_index];policy_index+=1
            constant=1;edges=[];key=(pd,pc)
            if write_mode:
                if len(writes)>0.8*64:
                    constant=admission[pd,writes[51]]+1;cause='policy_write_high'
                else:
                    assert not reads
                    edges.append((last_pop.get((pd,pc,2)),1,'policy_read_empty'));cause='policy_read_empty'
            else:
                assert reads
                constant=admission[pd,reads[0]]+1
                edges.append((last_pop.get((pd,pc,3)),1,'policy_write_low'));cause='policy_write_low'
            phase[key]=(constant,edges,cause)
        edges=[(serial.get((d,ci)),1,'controller_serial')]
        if buffer_kind==1:
            item=pri[d,ci][0];release=item[2];release_sources['refresh_injection']+=1
            if cmd==final_cmd:pri[d,ci].popleft()
        else:
            release=max(1,arrived+1);release_sources['request_admission']+=1
        if with_policy and buffer_kind in (2,3) and (d,ci) in phase:
            constant,gate_edges,cause=phase[d,ci];release=max(release,constant);edges+=gate_edges;release_sources[cause]+=1
        scope=min(3,timing['command_scopes'][cmd]);keys=[]
        for level in range(scope+1):
            if address[level]<0:break
            key=(d,*address[:level+1]);keys.append((level,key))
            for previous,latency,window in incoming[level,cmd]:
                history=histories[key,previous]
                if len(history)>=window:
                    edges.append((history[-window],latency,'timing_level_'+str(level)+'_window_'+str(window)))
        node=graph.add(release,edges,actual);command_nodes.append(node);serial[d,ci]=node
        for level,key in keys:histories[key,cmd].append(node)
        if cmd==final_cmd and rid>=0:final[d,rid]=(node,type_id)
        if buffer_kind in (2,3) and (cmd==final_cmd or cmd==0):last_pop[d,ci,buffer_kind]=node
    # Pending order is taken from the reference's relative event order, not from
    # observed completion times. These append-order decisions are part of C's
    # oracle input and are not available for a general online simulator.
    pending=defaultdict(list);command_index=0;immediate=[]
    for event in stream:
        kind,d,ci,clock,rid,address,type_id,ok,*_=event
        if kind==1 and ok and type_id==0 and (d,rid) not in final:
            pending[d,ci].append((None,clock+1,d,rid,'forwarded_read'))
        elif kind==2:
            row=selected[command_index];node=command_nodes[command_index];command_index+=1
            sd,sc,actual,cmd,last,type_id,request_id,*_=row
            assert [d,ci,clock,event[4]]==[sd,sc,actual,cmd]
            if cmd==last and request_id>=0:
                latency=timing['read_latency'] if type_id==0 else timing['write_latency']
                item=(node,latency,d,request_id,'data_latency')
                if latency>0:pending[d,ci].append(item)
                else:immediate.append(item)
    for queue in pending.values():
        previous=None
        for source,latency,d,rid,kind in queue:
            edges=[(previous,1,'callback_fifo')];release=latency if source is None else 0
            if source is not None:edges.append((source,latency,kind))
            previous=graph.add(release,edges,callbacks[d,rid])
    for source,latency,d,rid,kind in immediate:graph.add(0,[(source,latency,kind)],callbacks[d,rid])
    assert len(graph.release)==len(selected)+len(callbacks)
    return graph,dict(command_nodes=len(selected),callback_nodes=len(callbacks),release_sources=dict(release_sources),
                      edge_kinds=dict(graph.kinds),compile_cpu_seconds=time.process_time()-started,
                      oracle_inputs=['command and pending-append order','reference admissions','refresh injection','policy branches/queue IDs' if with_policy else 'no policy branches'],
                      deliberately_omitted_shared_data_bus=omit_shared_bus,
                      actual_command_cycles_used_as_release=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['reference','events','solver','output']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--ablate-shared-bus',action='store_true',help='Deliberately omit only channel RD/WR bus constraints; diagnostic negative control')
    a=parser.parse_args();a.output.mkdir(parents=True,exist_ok=False);results={};os.nice(15)
    variants=[('timing_only',False,False),('with_policy',True,False)]
    if a.ablate_shared_bus:variants.append(('bus_omitted_negative_control',True,True))
    for variant,policy,omit_bus in variants:
        graph,meta=compile_graph(a.reference,a.events,policy,omit_bus);path=a.output/(variant+'.bin')
        start=time.process_time();graph.save(path);meta['serialize_cpu_seconds']=time.process_time()-start
        start=time.process_time();result=subprocess.run([str(a.solver),str(path),str(path.with_suffix('.expected.bin')),'7'],capture_output=True,text=True,check=True)
        meta.update(json.loads(result.stdout));meta['driver_cpu_after_compile']=time.process_time()-start;results[variant]=meta
    output=dict(scope=__doc__,results=results)
    (a.output/'results.json').write_text(json.dumps(output,indent=2)+'\n');print(json.dumps(output))


if __name__=='__main__':main()
