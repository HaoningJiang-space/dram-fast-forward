"""Copy a frozen DRAM model and controller sources; never edit shared builds."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
if __package__:
    from .profile_patch import patch as profile_patch
else:
    from profile_patch import patch as profile_patch


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def change(text,old,new):
    if text.count(old)!=1:raise ValueError(('Unsupported source drift',old))
    return text.replace(old,new,1)


def build(source,ramulator,output,compiled_header=None):
    output=output.resolve();output.mkdir(exist_ok=False,parents=True)
    # A standalone frozen-input bundle uses a relocatable root token. Legacy
    # native manifests remain supported for reproducing the original experiment.
    prior=json.loads((source/'manifest.json').read_text().replace('${BUNDLE}',str(source.resolve())))
    dependencies={}
    files={'3D_DRAM.cpp':source/'3D_DRAM.cpp',
           'controller.cpp':ramulator/'dram_controller/impl/generic_dram_controller.cpp',
           'scheduler.cpp':ramulator/'dram_controller/impl/scheduler/generic_scheduler.cpp',
           'refresh.cpp':ramulator/'dram_controller/impl/refresh/all_bank_refresh.cpp',
           'memory.cpp':ramulator/'memory_system/impl/generic_DRAM_system.cpp'}
    for name,path in files.items():
        dependencies[str(path.resolve())]=sha(path);text=path.read_text()
        (output/('original_'+name)).write_text(text)
        # Inspection visibility only. No original branch or service algorithm changes.
        text=text.replace('  private:','  public:').replace('  protected:','  public:')
        if name in ('3D_DRAM.cpp','controller.cpp'):
            text=change(text,'    void init() override {',
                        '    void poc_clock(Clk_t t){m_clk=t;}\n    Clk_t poc_clock()const{return m_clk;}\n    void init() override {')
        if name=='3D_DRAM.cpp':
            text=change(text,'    void issue_command(int command, const AddrVec_t& addr_vec) override {',
                        '    void issue_command(int command, const AddrVec_t& addr_vec) override {\n      bool poc_mutates=false;if(poc::incremental)for(size_t level=0;level<m_levels.size();++level)if(m_actions[level][command])poc_mutates=true;\n      poc::command(dynamic_cast<void*>(this),m_clk,command,addr_vec,poc_mutates);')
        if name=='controller.cpp':
            first=text.index('    bool send(Request& req) override {');last=text.index('    bool priority_send',first)
            body=text[first:last]
            body=change(body,'    bool send(Request& req) override {','    bool send(Request& req) override {\n      auto poc_id=poc::wrap(dynamic_cast<void*>(m_dram),m_channel_id,req,&m_clk);')
            body=body.replace('return true;','poc::arrival(dynamic_cast<void*>(m_dram),m_channel_id,req,m_clk,poc_id,true);return true;')
            body=body.replace('return false;','poc::arrival(dynamic_cast<void*>(m_dram),m_channel_id,req,m_clk,poc_id,false);return false;')
            text=text[:first]+body+text[last:]
            old='      is_success = m_priority_buffer.enqueue(req);'
            if old not in text:old='      bool is_success = m_priority_buffer.enqueue(req);'
            text=change(text,old,old+'if(is_success){poc::changed(dynamic_cast<void*>(m_dram),m_channel_id);if(poc::priority_observer)poc::priority_observer(dynamic_cast<void*>(m_dram),m_channel_id,m_clk,req);}')
            text=change(text,'        m_dram->issue_command(req_it->command, req_it->addr_vec);',
                        '        if(poc::selected_observer)poc::selected_observer(dynamic_cast<void*>(m_dram),m_channel_id,m_clk,*req_it,buffer==&m_active_buffer?0:buffer==&m_priority_buffer?1:buffer==&m_read_buffer?2:3);\n        m_dram->issue_command(req_it->command, req_it->addr_vec);')
            start=text.index('    void set_write_mode() {');stop=text.index('\n    };',start)
            body=text[start:stop]
            body=body.replace('    void set_write_mode() {','    void set_write_mode() {\n      const bool poc_old_mode=m_is_write_mode;',1)
            body+='\n      if(poc::policy_observer && poc_old_mode!=m_is_write_mode){std::vector<int> reads,writes;for(auto& q:m_read_buffer)reads.push_back(q.trace_core_id);for(auto& q:m_write_buffer)writes.push_back(q.trace_core_id);poc::policy_observer(dynamic_cast<void*>(m_dram),m_channel_id,m_clk,m_is_write_mode,reads,writes);}\n'
            text=text[:start]+body+text[stop:]
        if name=='scheduler.cpp':
            text=change(text,'    IDRAM* m_dram;','    IDRAM* m_dram;\n    int poc_channel=-1;\n    std::map<ReqBuffer*,uint64_t> poc_versions;')
            text=change(text,'      m_dram = cast_parent<IDRAMController>()->m_dram;',
                        '      m_dram = cast_parent<IDRAMController>()->m_dram;poc_channel=cast_parent<IDRAMController>()->m_channel_id;')
            text=change(text,'      for (auto& req : buffer) {\n        req.command = m_dram->get_preq_command(req.final_command, req.addr_vec);\n      }',
                        '      auto generation=poc::incremental?poc::generation(dynamic_cast<void*>(m_dram),poc_channel):0;\n      if(!poc::incremental||poc_versions[&buffer]!=generation) {\n        for(auto& req:buffer)req.command=m_dram->get_preq_command(req.final_command,req.addr_vec);\n        if(poc::incremental)poc_versions[&buffer]=generation;++poc::preq_scans;\n      }else ++poc::preq_skips;')
        text=profile_patch(name,text,change)
        (output/name).write_text(text)
    here=Path(__file__).parent
    shutil.copy2(__file__,output/'build_generator.py');dependencies[str(Path(__file__).resolve())]=sha(__file__)
    for name in ('poc_hooks.hh','poc.cc','bank_symbolic.hh','shared_mapper.hh','profile_patch.py'):
        source_file=here/name if name.endswith('.py') else here/'native'/name
        shutil.copy2(source_file,output/name);dependencies[str(source_file.resolve())]=sha(source_file)
    if compiled_header:
        shutil.copy2(compiled_header,output/'generated_schedule.hh')
        dependencies[str(compiled_header.resolve())]=sha(compiled_header)
        source_file=here/'native/compiler_adapter.hh'
        shutil.copy2(source_file,output/source_file.name)
        dependencies[str(source_file.resolve())]=sha(source_file)
    cmd=prior['commands'][0];prefix=cmd[:cmd.index('-c')]
    prefix=[x for x in prefix if not (x.startswith('-I') and x[2:]==str(source))]
    if compiled_header:prefix.append('-DENABLE_SCHEDULE_COMPILER')
    command=prefix+['-I'+str(output),'-MMD','-MF',str(output/'dependencies.d'),'-c',str(output/'poc.cc'),'-o',str(output/'poc.o')]
    link=prior['commands'][-1]
    excluded=('domain.o','dram.o','generic_DRAM_system.cpp.o','generic_dram_controller.cpp.o','all_bank_refresh.cpp.o','generic_scheduler.cpp.o')
    objects=[x for x in link if x.endswith(('.o','.a')) and not any(Path(x).name.endswith(n) for n in excluded)]
    for x in objects:dependencies[x]=sha(x)
    link_command=[link[0],'-O3','-DNDEBUG',str(output/'poc.o')]+objects+['-lz','-o',str(output/'dram_poc')]
    with (output/'build.log').open('w') as log:
        subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
        subprocess.run(link_command,stdout=log,stderr=subprocess.STDOUT,check=True)
    if dependencies!={p:sha(p) for p in dependencies}:raise RuntimeError('Build inputs changed')
    included={}
    for word in (output/'dependencies.d').read_text().replace('\\\n',' ').split():
        path=Path(word)
        if path.is_absolute() and path.is_file():included[str(path)]=sha(path)
    result=dict(scope=__doc__,source_sha256=dependencies,compile_dependencies_sha256=included,
                generated_sha256={p.name:sha(p) for p in output.iterdir() if p.suffix in ('.cpp','.cc','.hh','.py')},
                commands=[command,link_command],binary_sha256=sha(output/'dram_poc'))
    (output/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(status='pass',binary_sha256=result['binary_sha256'])))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('source','ramulator','output'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--compiled-header',type=Path)
    a=p.parse_args();build(a.source,a.ramulator,a.output,a.compiled_header)


if __name__=='__main__':main()
