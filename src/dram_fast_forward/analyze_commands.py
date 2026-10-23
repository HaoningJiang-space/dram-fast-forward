"""Necessary per-channel READ-window conditions, not an implemented fast path."""
import argparse
from collections import Counter
import json
import hashlib
from pathlib import Path
import re
import struct

if __package__:
    from .analyze_trace import describe
else:
    from analyze_trace import describe


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture',type=Path,required=True);p.add_argument('--reference-summary',type=Path,required=True)
    p.add_argument('--model-source',type=Path,help='Frozen original DRAM source, to name every command ID')
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    summary=json.loads(a.reference_summary.read_text());ids=summary['command_ids'];reverse={v:k for k,v in ids.items()}
    model_identity=None
    if a.model_source:
        source=a.model_source.read_bytes()
        match=re.search(r'm_commands\s*=\s*\{([^}]+)\}',source.decode())
        if match is None:raise ValueError('Cannot read frozen command enumeration')
        names=re.findall(r'"([A-Za-z0-9_]+)"',match.group(1))
        complete=dict(enumerate(names))
        if any(complete.get(number)!=name for number,name in reverse.items()):
            raise ValueError('Frozen command IDs disagree with reference summary')
        reverse=complete
        model_identity=dict(path=str(a.model_source),sha256=hashlib.sha256(source).hexdigest())
    delta=summary['nBL'];runs={k:[] for k in ('arithmetic_row_reads','without_local_arrival','without_any_callback')}
    active={k:{} for k in runs};local_arrivals=Counter();callback=0;commands=Counter();breaks=Counter();fmt=struct.Struct('<12q')
    def finish(kind,key,reason):
        previous=active[kind].pop(key,None)
        if previous:runs[kind].append(previous[2]);breaks[kind+'/'+reason]+=1
    with a.capture.open('rb') as f:
        while True:
            data=f.read(fmt.size)
            if not data:break
            event=fmt.unpack(data);kind,device,channel,cycle,command=event[:5];key=(device,channel)
            if kind==1:local_arrivals[key]+=1;continue
            if kind==3:callback+=1;continue
            if kind!=2:continue
            commands[reverse.get(command,'other')]+=1
            if command!=ids['RD']:
                for label in runs:finish(label,key,reverse.get(command,'other'))
                continue
            row=event[9]
            for label in runs:
                old=active[label].get(key);reason='row_or_spacing'
                match=old is not None and old[0]==row and old[1]+delta==cycle
                if match and label!='arithmetic_row_reads' and old[3]!=local_arrivals[key]:match=False;reason='local_arrival'
                if match and label=='without_any_callback' and old[4]!=callback:match=False;reason='global_callback'
                if not match:finish(label,key,reason)
                active[label][key]=(row,cycle,(old[2]+1 if match else 1),local_arrivals[key],callback)
    for label in runs:
        for key in list(active[label]):finish(label,key,'end')
    result=dict(scope=__doc__,qualification='These necessary-condition windows ignore controller queue/write-policy guards. They are upper opportunities, not measured safe coverage; observed executed safe coverage is separate.',
                commands=dict(commands),breaks=dict(breaks),windows={k:describe(v) for k,v in runs.items()},nBL=delta,
                model_identity=model_identity)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(commands=result['commands'],windows={k:{x:y for x,y in v.items() if x!='histogram'} for k,v in result['windows'].items()})))


if __name__=='__main__':main()
