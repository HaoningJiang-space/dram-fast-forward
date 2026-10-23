"""Closed-loop/refresh/row-conflict differential stress for per-resource plans."""
import argparse
import json
import os
from pathlib import Path
from .fuzz import workload
from .interference import validate_case
from .common import save


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['binary','dram_yaml','output']:p.add_argument('--'+key.replace('_','-'),dest=key,type=Path,required=True)
    p.add_argument('--seeds',type=int,default=20);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);os.nice(15);rows=[]
    for seed in range(a.seeds):
        save(a.output/'status.json',dict(status='running',seed=seed,completed=len(rows)))
        row=validate_case(a.output,a.binary,a.dram_yaml,'seed'+str(seed),512,1,work=workload(seed))
        rows.append(dict(seed=seed,status='pass',bank_audit={v:dict(exits=x['exit_state_count'],stats=x['fast']['bank_symbolic']) for v,x in row['audit'].items()}))
    save(a.output/'results.json',dict(status='pass',cases=rows));save(a.output/'status.json',dict(status='pass',cases=len(rows)))
    print(json.dumps(dict(status='pass',seeds=len(rows))))


if __name__=='__main__':main()
