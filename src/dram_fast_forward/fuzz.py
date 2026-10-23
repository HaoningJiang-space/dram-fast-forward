"""Actual Ramulator differential tests around arrival/refresh/callback boundaries."""
import argparse
import json
import os
from pathlib import Path
import random
if __package__:
    from .run import case,save
else:
    from run import case,save


def workload(seed,n=512):
    rng=random.Random(seed);requests=[];followups={};devices=1+int(seed%3==0)
    for i in range(n):
        block=i//48;cycle=3800+block*700+rng.randrange(3)
        bank=0 if rng.random()<.95 else rng.randrange(8)
        row=0 if seed%4==0 else block%3
        address=(row*8+bank)*1024+(i%4)*256
        kind=0 if seed%4==0 else int(rng.random()<.15)
        device=0 if rng.random()<.95 else rng.randrange(devices)
        requests.append([cycle,address,kind,i,device])
        if seed%2 and i%7==0:followups[str(i)]=[rng.randrange(3),rng.randrange(16)*1024,i%2,10000+i]
    for j,t in enumerate((3899,3900,3901,7799,7800,7801)):
        requests.append([t,(j%8)*1024,j%2,n+j,0])
    requests.sort(key=lambda row:row[0])
    return dict(requests=requests,devices=devices,closed_loop=bool(seed%2),followups=followups,
                allow_symbolic=True,workload_requests=n,scope='Seeded mixed guard stress; only proved READ prefixes may batch, all other actions retain original paths.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('output','binary','dram_yaml'):p.add_argument('--'+key.replace('_','-'),dest=key,type=Path,required=True)
    p.add_argument('--seeds',type=int,default=20);a=p.parse_args();a.output.mkdir(exist_ok=False,parents=True);os.nice(15)
    rows=[]
    for seed in range(a.seeds):
        result=case(a.output,a.binary,a.dram_yaml,'seed'+str(seed),512,1,workload=workload(seed))
        rows.append(dict(seed=seed,status=result['status'],bulk_reads=result['audit']['symbolic']['bulk_reads']))
        save(a.output/'status.json',dict(status='running',completed=rows))
    save(a.output/'results.json',dict(status='pass',cases=rows))
    save(a.output/'status.json',dict(status='pass',seeds=len(rows)))
    print(json.dumps(dict(status='pass',seeds=len(rows),bulk_reads=sum(x['bulk_reads'] for x in rows))))


if __name__=='__main__':main()
