"""Shared artifact IO and child-process measurement; no physical model policy."""
import gzip
import hashlib
import json
import resource
import subprocess
import time

def save(p,value):p.write_text(json.dumps(value,separators=(',',':'))+'\n')
def load(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def invoke(binary,config,mode,folder):
    started=time.perf_counter();before=resource.getrusage(resource.RUSAGE_CHILDREN)
    with folder.with_suffix('.log').open('w') as log:
        p=subprocess.Popen([str(binary),str(config),mode,str(folder)],stdout=log,stderr=subprocess.STDOUT)
        save(folder.with_suffix('.pid.json'),dict(pid=p.pid,owned=True))
        if p.wait():raise RuntimeError(('PoC execution failed',folder.with_suffix('.log')))
    after=resource.getrusage(resource.RUSAGE_CHILDREN)
    result=load(folder/'summary.json');result['whole_process_wall_s']=time.perf_counter()-started
    result['whole_process_cpu_s']=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime
    return result


def equal_files(a,b):
    opener=gzip.open if a.suffix=='.gz' else open
    with opener(a,'rb') as x,b.open('rb') as y:
        while True:
            xx=x.read(1024*1024);yy=y.read(1024*1024)
            if xx!=yy:raise AssertionError(('Trace byte mismatch',a,b))
            if not xx:return
