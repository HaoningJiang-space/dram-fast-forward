"""Test exact fallback and preservation of the old mixed/refresh reference."""
import argparse
import copy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from dram_fast_forward.common import save,load,invoke,equal_files,sha
from dram_fast_forward.parametric_study import workload
from dram_fast_forward.workloads import synthetic

p=argparse.ArgumentParser(description=__doc__)
for name in ('artifact','binary','old_binary','yaml','output'):
    p.add_argument('--'+name.replace('_','-'),dest=name,type=Path,required=True)
a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
base=workload(load(a.artifact)['program'],4,'closed',[0],a.yaml)
cases=[]
for name in ('unknown_write','feedback','wrong_row_contract','out_of_domain','changed_timing'):
    work=copy.deepcopy(base)
    if name=='unknown_write':work['requests'].append([1,32768,1,9000]);work['requests'].sort(key=lambda r:r[0])
    if name=='feedback':work['closed_loop']=True;work['followups']={'0':[1,16384,0,9000]}
    if name=='wrong_row_contract':work['initial_rows'][0]=99
    if name=='out_of_domain':
        work=workload(load(a.artifact)['program'],4,'closed',[3899],a.yaml)
    if name=='changed_timing':
        path=a.output/'changed.yaml';path.write_text(a.yaml.read_text().replace('nBL: 8','nBL: 16'));work['dram_yaml']=str(path)
    folder=a.output/name;folder.mkdir();cfg=folder/'config.json';save(cfg,work)
    fast=invoke(a.binary,cfg,'parametric',folder/'fast');ref=invoke(a.binary,cfg,'reference',folder/'reference')
    assert not fast['parametric']['admitted'],name
    for file in ('events.bin','state.json'):equal_files(folder/'fast'/file,folder/'reference'/file)
    cases.append(dict(name=name,status='pass',fast=fast,reference=ref,event_sha256=sha(folder/'fast/events.bin')))
work=dict(synthetic('D',1000),dram_yaml=str(a.yaml),audit=True)
folder=a.output/'original_reference';folder.mkdir();cfg=folder/'config.json';save(cfg,work)
before=invoke(a.old_binary,cfg,'reference',folder/'old');after=invoke(a.binary,cfg,'reference',folder/'new')
for file in ('events.bin','state.json'):equal_files(folder/'old'/file,folder/'new'/file)
result=dict(status='pass',fallback_cases=cases,old_reference=dict(status='pass',before=before,after=after,event_sha256=sha(folder/'new/events.bin')))
save(a.output/'results.json',result);print(json.dumps({'status':'pass','fallback_cases':len(cases),'old_reference':'unchanged'}))
