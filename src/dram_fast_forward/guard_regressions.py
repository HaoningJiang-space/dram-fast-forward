"""Target new read arrivals, row-miss invalidation and write-mode thresholds."""
import argparse
import json
import os
from pathlib import Path
from .interference import validate_case
from .workloads import synthetic
from .common import save


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['binary','dram_yaml','output']:p.add_argument('--'+name.replace('_','-'),dest=name,type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);os.nice(15);results=[]
    for label in ['watermark_write','benign_read','late_row_miss']:
        work=synthetic('A' if label!='late_row_miss' else 'C',5000)
        if label=='watermark_write':
            work['requests'] += [[1250,(8+i%8)*1024,1,900000+i] for i in range(52)]
        elif label=='benign_read':work['requests'].append([1250,0,0,900000])
        else:work['requests'].append([1250,13*1024,0,900000])
        work['requests'].sort(key=lambda row:row[0]);work['scope']=__doc__
        result=validate_case(a.output,a.binary,a.dram_yaml,label,5000,1,work=work);results.append(result)
        save(a.output/'status.json',dict(status='running',completed=len(results)))
    save(a.output/'results.json',dict(status='pass',cases=results));save(a.output/'status.json',dict(status='pass',cases=len(results)))
    print(json.dumps(dict(status='pass',cases=len(results))))


if __name__=='__main__':main()
