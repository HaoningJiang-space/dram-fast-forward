"""Separate syntactic locality from the runtime's strictly guarded coverage."""
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics


def describe(values):
    if not values:return dict(count=0)
    ordered=sorted(values)
    return dict(count=len(values),mean=statistics.mean(values),p50=ordered[len(values)//2],
                p90=ordered[min(len(values)-1,int(len(values)*.9))],
                p99=ordered[min(len(values)-1,int(len(values)*.99))],maximum=max(values),
                histogram=dict(sorted(Counter(values).items())),
                requests_in_runs_ge2=sum(x for x in values if x>=2),
                requests_in_runs_ge16=sum(x for x in values if x>=16),
                requests_in_runs_ge100=sum(x for x in values if x>=100))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--trace',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--channels',type=int,default=8);a=p.parse_args()
    data=json.loads(a.trace.read_text());rows=data['requests'];bank_runs=[];global_runs=[]
    states={};last=None;length=0;reasons=Counter();read_count=0;same_row_links=0
    for cycle,address,kind,identity,device in rows:
        bank=(address//1024)%a.channels;row=address//(1024*a.channels);key=(device,bank)
        prior=states.get(key)
        if kind==0:
            read_count+=1
            if prior and prior[0]==0 and prior[1]==row:
                n=prior[2]+1;same_row_links+=1
            else:
                if prior and prior[0]==0:bank_runs.append(prior[2])
                reasons['bank_write_to_read' if prior and prior[0]==1 else 'bank_row_change_or_first']+=1;n=1
            states[key]=(kind,row,n)
        else:
            if prior and prior[0]==0:bank_runs.append(prior[2]);reasons['bank_read_to_write']+=1
            states[key]=(kind,row,0)
        current=(device,bank,row)
        if kind==0 and last==current:length+=1
        else:
            if length:global_runs.append(length)
            if last is not None and current[:2]!=last[:2]:reasons['global_other_bank_or_device']+=1
            elif last is not None and current[2]!=last[2]:reasons['global_row_change']+=1
            if kind:reasons['global_write']+=1
            length=1 if kind==0 else 0
        last=current if kind==0 else None
    for kind,row,n in states.values():
        if kind==0 and n:bank_runs.append(n)
    if length:global_runs.append(length)
    times=sorted(set(row[0] for row in rows));gaps=[b-a for a,b in zip(times,times[1:])]
    result=dict(scope='Syntactic input locality only; ignoring intervening work does not prove a safe jump. Runtime safe coverage is measured separately.',
                source=data.get('source'),requests=len(rows),reads=read_count,writes=len(rows)-read_count,
                devices=data['devices'],channels_per_device=a.channels,physical_row_bytes=1024,
                same_row_read_transition_fraction=same_row_links/max(1,read_count),
                per_bank_same_row_read_runs=describe(bank_runs),global_uninterrupted_read_runs=describe(global_runs),
                input_interruptions=dict(reasons),distinct_arrival_cycles=len(times),positive_arrival_gaps=describe(gaps))
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ('requests','same_row_read_transition_fraction','distinct_arrival_cycles')}))


if __name__=='__main__':main()
