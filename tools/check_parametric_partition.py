"""Independently check finite guard coverage and overlap, not scheduling policy."""
import argparse
import ast
import collections
import itertools
import json
from pathlib import Path


def value(node,x):
    if isinstance(node,ast.Constant):return node.value
    if isinstance(node,ast.Name):return x[int(node.id[1:])]
    if isinstance(node,ast.UnaryOp) and isinstance(node.op,ast.USub):return -value(node.operand,x)
    if isinstance(node,ast.BinOp):
        a,b=value(node.left,x),value(node.right,x)
        if isinstance(node.op,ast.Add):return a+b
        if isinstance(node.op,ast.Sub):return a-b
        if isinstance(node.op,ast.Mult):return a*b
    if isinstance(node,ast.Compare) and len(node.ops)==1:
        a,b=value(node.left,x),value(node.comparators[0],x)
        if isinstance(node.ops[0],ast.LtE):return a<=b
        if isinstance(node.ops[0],ast.GtE):return a>=b
    raise ValueError('Unsupported guard expression')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--artifact',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();data=json.loads(a.artifact.read_text());groups=collections.defaultdict(list)
    for kind in ('regions','unresolved'):
        for region in data[kind]:
            groups[region['length'],region['profile']].append((kind,region,[ast.parse(c,mode='eval').body for c in region['guard']]))
    output=[]
    for (length,profile),regions in groups.items():
        counts=collections.Counter();covered=[]
        for parameters in itertools.product(*(range(lo,hi+1) for lo,hi in data['program']['bounds'])):
            winners=[(k,r) for k,r,guard in regions if all(value(c,parameters) for c in guard)]
            assert len(winners)==1,(length,profile,parameters,len(winners))
            kind,region=winners[0];counts[kind]+=1
            if kind=='regions':
                times=[t[0]+sum(c*v for c,v in zip(t[1:],parameters)) for _,_,t in region['commands']]
                assert all(b>a for a,b in zip(times,times[1:]))
                covered.append(parameters)
        leaves=[r for k,r,_ in regions if k=='regions']
        output.append(dict(length=length,profile=profile,parameter_points=dict(counts),
                           regions=len(leaves),distinct_orders=len({tuple((x[0],x[1]) for x in r['commands']) for r in leaves}),
                           first_compiled_parameters=covered[0] if covered else None))
    result=dict(status='pass',scope=__doc__,variants=output)
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
