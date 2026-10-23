"""Replay one owned completed real accelerator program; capture actual DRAM IO."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import time


def load(p):return json.loads(p.read_text())
def save(p,j):p.write_text(json.dumps(j,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('input','native','output'):p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();a.output.mkdir(exist_ok=False,parents=True);os.nice(15)
    cfg=load(a.input/'native/config.json')
    for key,name in [('output','result.json'),('summary','summary.json'),('events','events.jsonl.gz'),
                     ('lifetime_log','lifetimes.jsonl.gz'),('diagnostic_log','native.log')]:cfg[key]=str(a.output/name)
    save(a.output/'config.json',cfg)
    memory=load(a.input/'memory.json');nodes=memory['nodes']['0'];admissions=[]
    for line in (a.input/'coupling.jsonl').read_text().splitlines():
        row=json.loads(line)
        if row['kind']=='stage':admissions.append(row)
    env=dict(os.environ,LEANWAFER_POC_TRACE=str(a.output/'dram_events.bin'))
    with (a.output/'stderr.log').open('w') as error:
        child=subprocess.Popen([str(a.native),'--live',str(a.output/'config.json')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=error,text=True,env=env)
        save(a.output/'owned_pid.json',dict(pid=child.pid,owned=True))
        def reply():
            while True:
                line=child.stdout.readline()
                if not line:raise RuntimeError('Capture native ended without reply')
                if line.startswith('@LIVE '):return json.loads(line[6:])
        assert reply()['status']=='ready'
        for row in admissions:
            binding=nodes[str(row['node'])]
            command=dict(command='run',at_ns=row['start_ns'],token=binding['token'],until=binding['until'])
            child.stdin.write(json.dumps(command)+'\n');child.stdin.flush();result=reply()
            assert result['status']=='output_ready' and result['time_ns']==row['output_ready_ns']
        child.stdin.write('{"command":"finish"}\n');child.stdin.flush();assert reply()['status']=='finished'
        child.stdin.close();assert child.wait()==0
    for name in ('result.json','summary.json'):assert load(a.output/name)==load(a.input/'native'/name)
    for name in ('events.jsonl.gz','lifetimes.jsonl.gz'):
        with gzip.open(a.output/name,'rb') as x,gzip.open(a.input/'native'/name,'rb') as y:
            while True:
                chunk=x.read(1024*1024);assert chunk==y.read(1024*1024)
                if not chunk:break
    records=[];devices=set();attempts=0;commands=0;callbacks=0
    row_format=struct.Struct('<12q')
    with (a.output/'dram_events.bin').open('rb') as f:
        while True:
            data=f.read(row_format.size)
            if not data:break
            row=row_format.unpack(data);kind,device,channel,cycle,identity,address,type_id,ok,*_=row
            devices.add(device)
            if kind==1:
                attempts+=1
                if ok:records.append([cycle,address,type_id,identity,device])
            elif kind==2:commands+=1
            elif kind==3:callbacks+=1
    records.sort(key=lambda row:row[0])
    save(a.output/'accepted_requests.json',dict(scope='Actual accepted controller requests from a real-width native accelerator workload; open-loop replay, not a closed-loop full decoder.',
         requests=records,devices=max(devices)+1,source=str(a.input),raw_trace_sha256=sha(a.output/'dram_events.bin')))
    save(a.output/'capture_summary.json',dict(status='pass',accepted=len(records),attempts=attempts,commands=commands,callbacks=callbacks,devices=len(devices),
         scope=__doc__,native_sha256=sha(a.native),source=str(a.input),exact=['native stage replies','native result/summary','all native events/lifetimes']))
    print(json.dumps(load(a.output/'capture_summary.json')),flush=True)


if __name__=='__main__':main()
