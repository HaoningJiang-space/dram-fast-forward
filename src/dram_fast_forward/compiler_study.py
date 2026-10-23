"""Exact differential experiments and amortization for generated kernels."""
import argparse
import gzip
import json
import math
import os
from pathlib import Path
import statistics
from .common import equal_files, invoke, load, save, sha
from .workloads import real_workload, synthetic


def validate(root,binary,yaml,label,work,repeats):
    folder=root/label;folder.mkdir(exist_ok=False)
    base=dict(work,dram_yaml=str(yaml),audit=True)
    audits={}
    for variant,match in [('compiled_stride',0),('compiled_resource',2),('compiled_dynamic',3)]:
        config=dict(base,compiler_match_mode=match)
        save(folder/(variant+'.json'),config)
        result=invoke(binary,folder/(variant+'.json'),'compiled',folder/variant)
        checkpoints=folder/variant/'bank_checkpoints.json'
        ref=dict(config,bank_checkpoints=str(checkpoints))
        save(folder/(variant+'_ref.json'),ref)
        reference=invoke(binary,folder/(variant+'_ref.json'),'reference',folder/(variant+'_ref'))
        for name in ('events.bin','state.json','bank_checkpoint_states.jsonl','bank_checkpoints.json'):
            equal_files(folder/(variant+'_ref')/name,folder/variant/name)
        audits[variant]=dict(status='pass',fast=result,reference=reference,
                            event_sha256=sha(folder/variant/'events.bin'),
                            exit_states=len(load(checkpoints)))
        with (folder/variant/'events.bin').open('rb') as src,gzip.open(folder/(variant+'_events.bin.gz'),'wb') as dst:
            while chunk:=src.read(1024*1024):dst.write(chunk)
        (folder/variant/'events.bin').unlink();(folder/(variant+'_ref')/'events.bin').unlink()
    modes=['reference','incremental','event','bank_hybrid','compiled_stride','compiled_resource','compiled_dynamic']
    samples={name:[] for name in modes}
    for i in range(repeats):
        for name in (modes if i%2==0 else modes[::-1]):
            config=dict(base,audit=False,bank_affine_only=False,bank_incremental=True,
                        compiler_match_mode={'compiled_stride':0,'compiled_resource':2,'compiled_dynamic':3}.get(name,2))
            path=folder/(name+'_bench.json');save(path,config)
            mode='compiled' if name.startswith('compiled_') else 'bank_symbolic' if name=='bank_hybrid' else name
            item=invoke(binary,path,mode,folder/f'bench_{i}_{name}')
            assert item['end_cycle']==reference['end_cycle'] and item['commands']==reference['commands']
            samples[name].append(item)
    median={name:statistics.median(x['host_cpu_seconds'] for x in values) for name,values in samples.items()}
    whole={name:statistics.median(x['whole_process_cpu_s'] for x in values) for name,values in samples.items()}
    result=dict(status='pass',label=label,workload_requests=len(work['requests']),audit=audits,samples=samples,
                median_cpu_s=median,median_whole_cpu_s=whole,
                loop_speedups={name:median['reference']/value for name,value in median.items()},
                whole_speedups={name:whole['reference']/value for name,value in whole.items()},
                binary_sha256=sha(binary),config_sha256=sha(yaml))
    save(folder/'results.json',result);return result


def tile_work(program,repeat_row=False):
    region=program['resource_regions'][1]
    base,width,rows,stride=(region[k] for k in ('base','width','rows','stride'))
    requests=[]
    for r in range(200 if repeat_row else rows):
        for offset in range(0,width,256):
            requests.append([0,base+(0 if repeat_row else r*stride)+offset,0,len(requests)])
    return dict(requests=requests,devices=1,closed_loop=False,
                scope='Controlled repeated activation-row geometry' if repeat_row else 'Actual pre-simulation tile weight DMA range; all requests externally released at zero, with real backpressure')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('binary','dram_yaml','output'):
        p.add_argument('--'+name.replace('_','-'),dest=name,type=Path,required=True)
    p.add_argument('--patterns',nargs='+',default=['A','C','D','A_closed','A_pressure'])
    p.add_argument('--count',type=int,default=10000)
    p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--real-trace',type=Path)
    p.add_argument('--memory-ir',type=Path)
    p.add_argument('--extra-workloads',type=Path)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);os.nice(15)
    cases=[]
    workloads=[]
    for label in a.patterns:
        if label=='E':work=real_workload(a.real_trace,a.count)
        elif label in ('tile_weight','resource_repeat'):
            work=tile_work(load(a.memory_ir),label=='resource_repeat')
        else:work=synthetic(label,a.count)
        workloads.append((label,work))
    if a.extra_workloads:workloads.extend((x['label'],x['work']) for x in load(a.extra_workloads))
    for label,work in workloads:
        save(a.output/'status.json',dict(status='running',current=label,completed=len(cases)))
        result=validate(a.output,a.binary,a.dram_yaml,label,work,a.repeats);cases.append(result)
        print(json.dumps(dict(label=label,status='pass',loop_speedups=result['loop_speedups'])),flush=True)
    save(a.output/'results.json',dict(status='pass',cases=cases))
    save(a.output/'status.json',dict(status='pass',cases=len(cases)))


if __name__=='__main__':main()
