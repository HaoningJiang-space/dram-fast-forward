"""Export only the measured PoC's frozen inputs into a relocatable Linux bundle.

Run once where the original manifest inputs exist. The bundle is an ignored,
platform-specific build dependency, not a new copy of the parent repository.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--poc-build',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();build=args.poc_build.resolve();out=args.output.resolve()
    manifest=json.loads((build/'manifest.json').read_text())
    out.mkdir(parents=True,exist_ok=False);inventory={}

    def copy(source,target,expected=None):
        source=Path(source);target=out/target
        digest=sha(source)
        if expected and digest!=expected:raise ValueError(('Frozen input drift',source))
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        if sha(target)!=digest:raise ValueError(('Copy mismatch',target))
        inventory[str(target.relative_to(out))]=dict(source=str(source),sha256=digest)
        return '${BUNDLE}/'+str(target.relative_to(out))

    keys=manifest['source_sha256']
    original={
        '3D_DRAM.cpp':next(p for p in keys if p.endswith('/3D_DRAM.cpp')),
        'ramulator/dram_controller/impl/generic_dram_controller.cpp':next(p for p in keys if p.endswith('/generic_dram_controller.cpp')),
        'ramulator/dram_controller/impl/scheduler/generic_scheduler.cpp':next(p for p in keys if p.endswith('/generic_scheduler.cpp')),
        'ramulator/dram_controller/impl/refresh/all_bank_refresh.cpp':next(p for p in keys if p.endswith('/all_bank_refresh.cpp')),
        'ramulator/memory_system/impl/generic_DRAM_system.cpp':next(p for p in keys if p.endswith('/generic_DRAM_system.cpp')),
    }
    for dest,source in original.items():copy(source,dest,keys[source])
    commands=manifest['commands'];compile_command=commands[0]
    includes=[Path(x[2:]) for x in compile_command if x.startswith('-I')]
    included=manifest['compile_dependencies_sha256'];new_includes=[]
    for index,folder in enumerate(includes):
        members=[Path(p) for p in included if Path(p).is_relative_to(folder)]
        # The generated PoC directory is supplied separately by build.py.
        if folder==build or not members:continue
        target=Path('include')/str(index);new_includes.append('-I${BUNDLE}/'+str(target))
        for member in members:copy(member,target/member.relative_to(folder),included[str(member)])
    flags=[x for x in compile_command[1:compile_command.index('-c')]
           if not x.startswith('-I')]
    # MMD/MF belong to the new invocation, not its frozen compiler prefix.
    flags=flags[:flags.index('-MMD')] if '-MMD' in flags else flags
    prefix=[compile_command[0]]+flags+new_includes
    link=commands[-1];objects=[]
    for index,word in enumerate(link):
        if not word.endswith(('.o','.a')) or Path(word)==build/'poc.o':continue
        objects.append(copy(word,Path('objects')/(str(index)+'_'+Path(word).name),keys[word]))
    portable=dict(format='dram-ff-frozen-inputs-v1',
                  scope='Frozen headers, physical sources and Linux support objects; no runtime parent-repository paths',
                  commands=[prefix+['-c','${BUNDLE}/placeholder.cc','-o','${BUNDLE}/placeholder.o'],
                            [link[0],'-O3','-DNDEBUG']+objects+['-lz','-o','${BUNDLE}/placeholder']],
                  origin_build_manifest_sha256=sha(build/'manifest.json'))
    (out/'manifest.json').write_text(json.dumps(portable,indent=2)+'\n')
    (out/'inventory.json').write_text(json.dumps(dict(files=inventory,origin_manifest_sha256=sha(build/'manifest.json')),indent=2)+'\n')
    print(json.dumps(dict(status='pass',files=len(inventory),bundle=str(out))))


if __name__=='__main__':main()
