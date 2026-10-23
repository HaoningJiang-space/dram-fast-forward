"""Extract loop structure from a real pre-simulation native tile descriptor."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
from .polyhedral import resource_projection


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tiles',type=Path,required=True)
    p.add_argument('--base-ir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    with a.tiles.open('rb') as f:
        length=struct.unpack('<I',f.read(4))[0]
        tile=json.loads(f.read(length))
    start=time.process_time();program=json.loads(a.base_ir.read_text());regions=[]
    for base,width,rows,stride in tile['reads']:
        projection=resource_projection(base,width,rows,stride)
        regions.append(dict(base=base,width=width,rows=rows,stride=stride,projection=projection))
    program['resource_regions']=regions
    program['source']=dict(tiles_path=str(a.tiles),tiles_sha256=hashlib.sha256(a.tiles.read_bytes()).hexdigest(),
                           tile=tile,scope='First actual native Up/Gate tile, before DRAM simulation; request structure only')
    program['projection_cpu_s']=time.process_time()-start
    (a.output/'memory_ir.json').write_text(json.dumps(program,indent=2)+'\n')
    print(json.dumps(dict(status='pass',source_tile=tile['execution']['id'],regions=len(regions),
                         projection_cpu_s=program['projection_cpu_s'])))


if __name__=='__main__':main()
