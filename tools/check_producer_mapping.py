"""Cross-check producer addresses against C++ extracted from native mapping source."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from dram_fast_forward.producer_ir import route

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--source',type=Path,required=True);p.add_argument('--program',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
text=a.source.read_text();start=text.index('static unsigned mapping_shift');end=text.index('// Exact integer partition:',start)
excerpt=text[start:end]
cpp='#include <cstdint>\n#include <iostream>\nusing u64=uint64_t;\n'+excerpt+'\nint main(){u64 a;while(std::cin>>a)std::cout<<endpoint(a,64)<<" "<<local_address(a,64)<<"\\n";}\n'
(a.output/'mapping.cc').write_text(cpp)
subprocess.run(['c++','-O2',str(a.output/'mapping.cc'),'-o',str(a.output/'mapping')],check=True)
program=json.loads(a.program.read_text());addresses=[x for r in program['producers'] for x in r['logical_addresses']]
rng=random.Random(20261023);addresses+= [rng.randrange(0,2**32//256)*256 for _ in range(10000)]
result=subprocess.run([str(a.output/'mapping')],input='\n'.join(map(str,addresses))+'\n',text=True,capture_output=True,check=True)
rows=[tuple(map(int,s.split())) for s in result.stdout.splitlines()]
assert rows==[route(x) for x in addresses]
report=dict(status='pass',addresses=len(rows),source_sha256=hashlib.sha256(a.source.read_bytes()).hexdigest(),
            excerpt_sha256=hashlib.sha256(excerpt.encode()).hexdigest(),program_sha256=hashlib.sha256(a.program.read_bytes()).hexdigest(),
            scope='Native CRC endpoint and local-address transform; fixed 512-byte stripe, no coloring. Not the full accelerator producer scheduler.')
(a.output/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
