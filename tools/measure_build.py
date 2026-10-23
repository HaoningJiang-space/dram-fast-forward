"""Measure a fresh full compiler invocation, including C++ build and link."""
import argparse
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--receipt',type=Path,required=True)
p.add_argument('arguments',nargs=argparse.REMAINDER)
a=p.parse_args();arguments=a.arguments[1:] if a.arguments[:1]==['--'] else a.arguments
command=[sys.executable,'-m','dram_fast_forward.build',*arguments]
start=time.perf_counter(); before=resource.getrusage(resource.RUSAGE_CHILDREN)
result=subprocess.run(command)
after=resource.getrusage(resource.RUSAGE_CHILDREN)
report=dict(command=command,returncode=result.returncode,wall_s=time.perf_counter()-start,
            cpu_s=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
            maximum_child_rss_kib=after.ru_maxrss)
a.receipt.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
sys.exit(result.returncode)
