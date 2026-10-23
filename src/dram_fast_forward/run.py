"""Original global-isolation PoC driver, retained for historical controls."""
import argparse
import gzip
import json
import os
from pathlib import Path
import shutil
import statistics
if __package__:
    from .common import save,load,sha,invoke,equal_files
    from .workloads import synthetic,real_workload
else:
    from common import save,load,sha,invoke,equal_files
    from workloads import synthetic,real_workload

MODES=('reference','event','incremental','symbolic')


def case(root,binary,yaml,label,count,bench_repeats,real_trace=None,workload=None,reference_root=None):
    out=root/f'{label}_{count}';out.mkdir(exist_ok=False)
    work=workload if workload is not None else (real_workload(real_trace,count) if label=='E' else synthetic(label,count))
    config=dict(work,dram_yaml=str(yaml),audit=True)
    save(out/'input.json',config)
    # Discover every actual fast-exit checkpoint before replaying the reference.
    fast=invoke(binary,out/'input.json','symbolic',out/'symbolic')
    times=[x[0] for x in load(out/'symbolic/checkpoints.json')]
    save(out/'checkpoint_times.json',times)
    config['checkpoints']=str(out/'checkpoint_times.json');save(out/'checked_input.json',config)
    old_case=reference_root/f'{label}_{count}' if reference_root else None
    if old_case:
        old=load(old_case/'input.json')
        for key in ('requests','devices','closed_loop','followups'):
            assert old.get(key)==config.get(key),('Changed reference workload',key)
        assert load(old_case/'checkpoint_times.json')==times,'Host-only optimization changed the fast exit schedule'
        old_result=load(old_case/'results.json');reference=old_result['audit']['reference']
        (out/'reference').mkdir()
        for name in ('summary.json','state.json','checkpoints.json'):shutil.copy2(old_case/'reference'/name,out/'reference'/name)
    else:reference=invoke(binary,out/'checked_input.json','reference',out/'reference')
    results={'reference':reference,'symbolic':fast}
    for mode in ('event','incremental'):results[mode]=invoke(binary,out/'checked_input.json',mode,out/mode)
    for mode in ('symbolic','event','incremental'):
        for name in ('events.bin','state.json','checkpoints.json','checkpoint_states.jsonl'):
            expected=out/'reference'/name
            if old_case:
                expected=old_case/({'events.bin':'reference_events.bin.gz','checkpoint_states.jsonl':'reference_checkpoint_states.jsonl.gz'}.get(name,'reference/'+name))
            equal_files(expected,out/mode/name)
    # No input may appear inside a claimed atomic jump. Closed-loop jumps must
    # also stop before any potentially input-generating callback.
    from bisect import bisect_right
    arrival_times=[row[0] for row in work['requests']]
    callback_times=[]
    if work.get('closed_loop'):
        import struct
        fmt=struct.Struct('<12q')
        with (out/'symbolic/events.bin').open('rb') as stream:
            while True:
                chunk=stream.read(fmt.size)
                if not chunk:break
                event=fmt.unpack(chunk)
                if event[0]==3:callback_times.append(event[3])
        callback_times.sort()
    for start,first,end,n,delta,horizon,channel,closed in load(out/'symbolic/intervals.json'):
        assert end<horizon and end==first+(n-1)*delta
        assert bisect_right(arrival_times,end)==bisect_right(arrival_times,start)
        if closed:assert bisect_right(callback_times,end)==bisect_right(callback_times,start)
    result=dict(status='pass',pattern=label,count=count,binary_sha256=sha(binary),config_sha256=sha(yaml),
                audit=results,exact=['command kinds/order/cycles','every admission/rejection attempt','every actual callback cycle',
                                     'all fast-exit device/timing/history/controller/queue/refresh states',
                                     'final full device/controller state' if label=='E' else 'final state after paid recovery suffix'])
    if old_case:result['reused_validation_reference']=dict(directory=str(old_case),binary_sha256=old_result['binary_sha256'],scope='Literal archived reference bytes and state, not reused benchmark timings')
    # Preserve one compressed raw trace after literal byte comparisons.
    for source_name,target_name in [('events.bin','reference_events.bin.gz'),('checkpoint_states.jsonl','reference_checkpoint_states.jsonl.gz')]:
        with (out/'symbolic'/source_name).open('rb') as source,gzip.open(out/target_name,'wb') as target:
            while True:
                chunk=source.read(1024*1024)
                if not chunk:break
                target.write(chunk)
    result['raw_trace_sha256']=sha(out/'symbolic/events.bin')
    for mode in MODES:
        for name in ('events.bin','checkpoint_states.jsonl'):
            path=out/mode/name
            if path.exists():path.unlink()
    config.pop('checkpoints');config['audit']=False;save(out/'benchmark_input.json',config)
    samples={mode:[] for mode in MODES}
    for repeat in range(bench_repeats):
        order=MODES if repeat%2==0 else MODES[::-1]
        for mode in order:
            item=invoke(binary,out/'benchmark_input.json',mode,out/f'bench_{repeat}_{mode}')
            assert item['end_cycle']==reference['end_cycle'] and item['commands']==reference['commands']
            samples[mode].append(item)
    result['benchmark']=samples
    med={k:statistics.median(x['host_cpu_seconds'] for x in v) for k,v in samples.items()}
    whole={k:statistics.median(x['whole_process_cpu_s'] for x in v) for k,v in samples.items()}
    result.update(median_cpu_s=med,cpu_speedups={k:med['reference']/v for k,v in med.items()},
                  median_whole_process_cpu_s=whole,whole_process_cpu_speedups={k:whole['reference']/v for k,v in whole.items()},
                  safe_read_coverage=fast['bulk_reads']/sum(x[2]==0 for x in work['requests']),
                  average_segment_length=fast['bulk_reads']/max(1,fast['bulk_segments']))
    save(out/'results.json',result);return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('output','binary','dram_yaml'):p.add_argument('--'+key.replace('_','-'),dest=key,type=Path,required=True)
    p.add_argument('--counts',type=int,nargs='+',default=[10000]);p.add_argument('--patterns',nargs='+',default=['A','B','C','D','A_affine4','A_interrupt','A_closed','A_pressure'])
    p.add_argument('--real-trace',type=Path)
    p.add_argument('--validation-reference',type=Path)
    p.add_argument('--repeats',type=int,default=3);a=p.parse_args()
    if 'E' in a.patterns and a.real_trace is None:p.error('E requires --real-trace from an actual capture')
    a.output.mkdir(exist_ok=False,parents=True)
    os.nice(15);save(a.output/'owned_pid.json',dict(pid=os.getpid(),owned=True));rows=[]
    for n in a.counts:
        for label in a.patterns:
            save(a.output/'status.json',dict(status='running',current=[label,n],completed=[dict(pattern=x['pattern'],count=x['count'],status=x['status']) for x in rows]))
            item=case(a.output,a.binary,a.dram_yaml,label,n,a.repeats,a.real_trace,reference_root=a.validation_reference);rows.append(item)
            print(json.dumps({k:item[k] for k in ('pattern','count','cpu_speedups','safe_read_coverage')}),flush=True)
    save(a.output/'results.json',dict(status='pass',cases=rows));save(a.output/'status.json',dict(status='pass',cases=len(rows)))


if __name__=='__main__':main()
