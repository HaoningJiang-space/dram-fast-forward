"""Fresh-process timings at an explicitly chosen compiled parameter point."""
import argparse
import json
from pathlib import Path
import statistics
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from dram_fast_forward.common import save,load,invoke
from dram_fast_forward.parametric_study import workload

p=argparse.ArgumentParser(description=__doc__)
for name in ('artifact','binary','yaml','output'):p.add_argument('--'+name,type=Path,required=True)
p.add_argument('--parameters',type=int,nargs='+',required=True)
p.add_argument('--length',type=int,default=4);p.add_argument('--repeats',type=int,default=7)
a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
base=workload(load(a.artifact)['program'],a.length,'closed',a.parameters,a.yaml)
samples={name:[] for name in ('reference','hybrid','dynamic','parametric')}
for repeat in range(a.repeats):
    names=list(samples) if repeat%2==0 else list(reversed(samples))
    for name in names:
        config=dict(base,audit=False,bank_affine_only=False,bank_incremental=True,compiler_match_mode=3)
        cfg=a.output/(name+'.json');save(cfg,config)
        result=invoke(a.binary,cfg,{'hybrid':'bank_symbolic','dynamic':'compiled'}.get(name,name),a.output/f'{name}_{repeat}')
        if name=='parametric':assert result['parametric']['admitted']
        samples[name].append(result)
reference=samples['reference'][0]
for values in samples.values():
    for item in values:
        assert all(item[k]==reference[k] for k in ('end_cycle','commands','accepted','completed'))
loop={n:statistics.median(x['host_cpu_seconds'] for x in v) for n,v in samples.items()}
whole={n:statistics.median(x['whole_process_cpu_s'] for x in v) for n,v in samples.items()}
result=dict(parameters=a.parameters,length=a.length,samples=samples,median_loop_cpu_s=loop,
            median_whole_cpu_s=whole,whole_relative_to_hybrid={n:whole['hybrid']/v for n,v in whole.items()})
save(a.output/'results.json',result);print(json.dumps({k:v for k,v in result.items() if k!='samples'}))
