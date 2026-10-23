"""Build a private request/command capture binary from original native objects."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('original','poc_build','output'):p.add_argument('--'+name.replace('_','-'),dest=name,type=Path,required=True)
    a=p.parse_args();a.output.mkdir(exist_ok=False)
    manifest=json.loads((a.original/'manifest.json').read_text());commands=manifest['commands']
    inputs={}
    for name in ('3D_DRAM.cpp','controller.cpp','poc_hooks.hh'):
        old=a.poc_build/name;target=a.output/name;shutil.copy2(old,target);inputs[str(old)]=sha(old)
    prefix=commands[1][:commands[1].index('-c')];prefix+=['-I'+str(a.output)]
    builds=[]
    for stem,file in [('capture_dram','3D_DRAM.cpp'),('capture_controller','controller.cpp')]:
        source=a.output/(stem+'.cc');source.write_text('#include "base/base.h"\n#include "poc_hooks.hh"\n#include "'+file+'"\n')
        builds.append(prefix+['-c',str(source),'-o',str(a.output/(stem+'.o'))])
    link=[]
    for word in commands[-1]:
        if word==str(a.original/'dram.o'):word=str(a.output/'capture_dram.o')
        elif word.endswith('generic_dram_controller.cpp.o'):word=str(a.output/'capture_controller.o')
        elif word==str(a.original/'leanwafer_live'):word=str(a.output/'leanwafer_live')
        link.append(word)
        path=Path(word)
        if path.is_file() and path.suffix in ('.o','.a'):inputs[str(path)]=sha(path)
    with (a.output/'build.log').open('w') as log:
        for command in builds+[link]:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
    if inputs!={k:sha(k) for k in inputs}:raise RuntimeError('Capture build dependency drift')
    (a.output/'manifest.json').write_text(json.dumps(dict(scope=__doc__,commands=builds+[link],sources_sha256=inputs,binary_sha256=sha(a.output/'leanwafer_live')),indent=2)+'\n')
    print('Capture build complete')


if __name__=='__main__':main()
