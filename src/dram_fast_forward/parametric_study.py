"""Differential validation of one parametric artifact over many entry values."""
import argparse
import itertools
import json
from pathlib import Path
import random
import statistics
from .common import save, load, invoke, equal_files, sha
from .parametric import initial_rows
from .check_bus import check


def workload(program,n,profile,parameters,yaml):
    requests=[]
    for p,producer in enumerate(program['producers']):
        offset=sum(a*b for a,b in zip(parameters,producer['offset_coefficients']))
        for i,local in enumerate(producer['local_addresses'][:n]):
            requests.append([offset+i*program.get('arrival_gap',0),local,0,p*1000+i])
    requests.sort(key=lambda r:r[0])
    return dict(devices=1,requests=requests,initial_rows=initial_rows(program,n,profile),
                producer_length=n,row_profile=['closed','hit','conflict'].index(profile),
                parameters=parameters,audit=True,dram_yaml=str(yaml),closed_loop=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('binary','artifact','dram_yaml','output'):
        p.add_argument('--'+name.replace('_','-'),dest=name,type=Path,required=True)
    p.add_argument('--dense-offsets',action='store_true')
    p.add_argument('--offset-values',type=int,nargs='+',help='Explicit one-dimensional boundary cases')
    p.add_argument('--samples',type=int,default=30)
    p.add_argument('--bench-repeats',type=int,default=5)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    artifact=load(a.artifact); program=artifact['program']; bounds=program['bounds']
    rng=random.Random(240123)
    if a.offset_values:
        if len(bounds)!=1:p.error('--offset-values requires one parameter')
        parameters=[(x,) for x in a.offset_values]
    elif a.dense_offsets:
        parameters=list(itertools.product(*(range(lo,hi+1) for lo,hi in bounds)))
    else:
        parameters=list(itertools.product(*([lo,hi] for lo,hi in bounds)))
        parameters+=list(dict.fromkeys(tuple(rng.randint(lo,hi) for lo,hi in bounds) for _ in range(a.samples)))
    parameters=list(dict.fromkeys(parameters))
    variants=sorted(set((r['length'],r['profile']) for r in artifact['regions']+artifact['unresolved']))
    rows=[];checks={};benchmark=[]
    for n,profile in variants:
        for params in parameters:
            label=f'n{n}_{profile}_'+ '_'.join(map(str,params));folder=a.output/label;folder.mkdir()
            work=workload(program,n,profile,list(params),a.dram_yaml)
            cfg=folder/'config.json';save(cfg,work)
            fast=invoke(a.binary,cfg,'parametric',folder/'parametric')
            exits=load(folder/'parametric/checkpoints.json')
            checkpoint_file=folder/'exit_cycles.json';save(checkpoint_file,[r[0] for r in exits])
            ref_cfg=folder/'reference.json';save(ref_cfg,dict(work,checkpoints=str(checkpoint_file)))
            reference=invoke(a.binary,ref_cfg,'reference',folder/'reference')
            for name in ('events.bin','state.json','checkpoint_states.jsonl'):
                equal_files(folder/'reference'/name,folder/'parametric'/name)
            result=check(folder/'parametric/events.bin',artifact['model'])
            for k,v in result['checks'].items():checks[k]=checks.get(k,0)+v
            item=dict(label=label,parameters=params,length=n,profile=profile,status='pass',
                      event_sha256=sha(folder/'parametric/events.bin'),
                      fast=fast,reference=reference)
            rows.append(item)
            # Atomic status replacement avoids repeatedly truncating a page
            # being written back by the shared filesystem.
            pending=a.output/'status.next.json';save(pending,dict(completed=len(rows),last=label));pending.replace(a.output/'status.json')
            if params==parameters[0]:benchmark.append((label,work))
    # Strong controls share the new binary and entry state. These short regions
    # do not stand in for a full FFN throughput or end-to-end accelerator result.
    benches=[]
    for label,work in benchmark:
        folder=a.output/(label+'_bench');folder.mkdir(); samples={k:[] for k in ('reference','hybrid','dynamic','parametric')}
        for repeat in range(a.bench_repeats):
            names=list(samples) if repeat%2==0 else list(reversed(samples))
            for name in names:
                config=dict(work,audit=False,bank_affine_only=False,bank_incremental=True,compiler_match_mode=3)
                cfg=folder/(name+'.json');save(cfg,config)
                mode={'hybrid':'bank_symbolic','dynamic':'compiled'}.get(name,name)
                value=invoke(a.binary,cfg,mode,folder/f'{name}_{repeat}')
                samples[name].append(value)
        med={name:statistics.median(v['host_cpu_seconds'] for v in vs) for name,vs in samples.items()}
        whole={name:statistics.median(v['whole_process_cpu_s'] for v in vs) for name,vs in samples.items()}
        benches.append(dict(label=label,samples=samples,median_loop_cpu_s=med,median_whole_cpu_s=whole,
                            relative_to_hybrid={k:med['hybrid']/v for k,v in med.items()}))
    result=dict(status='pass',cases=len(rows),admitted=sum(r['fast']['parametric']['admitted'] for r in rows),
                comparisons=rows,benchmarks=benches,bus_checks=checks,binary_sha256=sha(a.binary),artifact_sha256=sha(a.artifact))
    save(a.output/'results.json',result);save(a.output/'status.json',dict(status='pass',cases=len(rows),admitted=result['admitted']))
    print(json.dumps(dict(status='pass',cases=len(rows),admitted=result['admitted'])))


if __name__=='__main__':main()
