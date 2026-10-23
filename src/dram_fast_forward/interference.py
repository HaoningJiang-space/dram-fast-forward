"""Compare online per-resource plans with fresh precise reference executions."""
import argparse
import gzip
import json
import os
from pathlib import Path
import statistics

from .common import invoke,save,load,sha,equal_files
from .workloads import synthetic,real_workload


def validate_case(root,binary,yaml,label,count,repeats,real_trace=None,work=None):
    folder=root/f'{label}_{count}';folder.mkdir(exist_ok=False)
    workload=work or (real_workload(real_trace,count) if label=='E' else synthetic(label,count))
    base=dict(workload,dram_yaml=str(yaml),audit=True)
    results={}
    for variant,affine in [('bank_affine',True),('bank_rowhit',False),('bank_hybrid',False)]:
        config=dict(base,bank_affine_only=affine,bank_incremental=variant=='bank_hybrid')
        path=folder/(variant+'.json');save(path,config)
        fast=invoke(binary,path,'bank_symbolic',folder/variant)
        checkpoints=folder/variant/'bank_checkpoints.json'
        ref_config=dict(config,bank_checkpoints=str(checkpoints),oracle_trace=variant=='bank_affine')
        ref_path=folder/(variant+'_reference.json');save(ref_path,ref_config)
        reference=invoke(binary,ref_path,'reference',folder/(variant+'_reference'))
        for name in ['events.bin','state.json','bank_checkpoint_states.jsonl','bank_checkpoints.json']:
            equal_files(folder/(variant+'_reference')/name,folder/variant/name)
        # Compress compared records, retaining one exact stream per variant.
        archive=folder/(variant+'_events.bin.gz')
        with (folder/variant/'events.bin').open('rb') as src,gzip.open(archive,'wb') as dst:
            while chunk:=src.read(1024*1024):dst.write(chunk)
        result=dict(status='pass',fast=fast,reference=reference,
                    raw_trace_sha256=sha(folder/variant/'events.bin'),
                    exit_state_count=len(load(checkpoints)))
        results[variant]=result
        for mode in [variant,variant+'_reference']:
            (folder/mode/'events.bin').unlink()
        config['audit']=False;save(folder/(variant+'_benchmark.json'),config)
    save(folder/'reference_benchmark.json',dict(base,audit=False))
    modes=['reference','incremental','event','symbolic','bank_affine','bank_rowhit','bank_hybrid']
    samples={mode:[] for mode in modes}
    for repeat in range(repeats):
        for mode in (modes if repeat%2==0 else modes[::-1]):
            variant=mode if mode.startswith('bank_') else 'reference'
            config=folder/(variant+'_benchmark.json')
            result=invoke(binary,config,'bank_symbolic' if mode.startswith('bank_') else mode,folder/f'bench_{repeat}_{mode}')
            assert result['end_cycle']==results['bank_affine']['reference']['end_cycle']
            assert result['commands']==results['bank_affine']['reference']['commands']
            samples[mode].append(result)
    med={m:statistics.median(x['host_cpu_seconds'] for x in values) for m,values in samples.items()}
    whole={m:statistics.median(x['whole_process_cpu_s'] for x in values) for m,values in samples.items()}
    result=dict(status='pass',pattern=label,count=count,binary_sha256=sha(binary),config_sha256=sha(yaml),
                scope='Actual online order certification, no oracle command sequence; unchanged arrival/callback dispatch.',
                audit=results,samples=samples,median_cpu_s=med,median_whole_cpu_s=whole,
                loop_speedups={m:med['reference']/v for m,v in med.items()},
                whole_speedups={m:whole['reference']/v for m,v in whole.items()})
    save(folder/'results.json',result);return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['binary','dram_yaml','output']:p.add_argument('--'+name.replace('_','-'),dest=name,type=Path,required=True)
    p.add_argument('--patterns',nargs='+',default=['A','B','C','D','A_affine4','A_interrupt','A_closed','A_pressure'])
    p.add_argument('--counts',nargs='+',type=int,default=[10000]);p.add_argument('--real-trace',type=Path)
    p.add_argument('--repeats',type=int,default=3);a=p.parse_args();a.output.mkdir(exist_ok=False,parents=True);os.nice(15)
    results=[]
    for count in a.counts:
        for label in a.patterns:
            save(a.output/'status.json',dict(status='running',current=[label,count],completed=len(results)))
            result=validate_case(a.output,a.binary,a.dram_yaml,label,count,a.repeats,a.real_trace);results.append(result)
            print(json.dumps(dict(pattern=label,count=count,status='pass',loop_speedups=result['loop_speedups'])),flush=True)
    save(a.output/'results.json',dict(status='pass',cases=results));save(a.output/'status.json',dict(status='pass',cases=len(results)))


if __name__=='__main__':main()
