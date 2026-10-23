#pragma once
#include <cmath>

// ABI between generated schedule kernels and the frozen physical simulator.
// Request admission, callbacks, refresh and unsupported regions use the same
// implementation as the reference. No oracle log is accessible here.
#include "generated_schedule.hh"

struct CompiledPlan {
  bool active=false, populated=false;
  int command=-1, type=-1;
  size_t planned=0, issued=0;
  Clk_t first=0, spacing=0, last_all=-1;
  std::array<Clk_t,8> last;
  std::array<std::vector<Node*>,8> paths;
  CompiledPlan() { last.fill(-1); }
};

struct CompiledStats {
  uint64_t attempts=0, admitted=0, commands=0, segments=0, fallback_ticks=0;
  uint64_t retained_arrivals=0, timing_materializations=0;
  std::map<std::string,uint64_t> rejection, exits;
  std::map<size_t,uint64_t> lengths;
};

void validate_compiler_model(Engine& e) {
  if (!e.shared_bus || e.ctrls.size()!=1) throw std::runtime_error("Compiler ABI requires eight-bank shared profile");
  J constraints=J::array();
  for(size_t l=0;l<e.dram->m_levels.size();++l)
    for(size_t c=0;c<e.dram->m_commands.size();++c)
      for(auto& t:e.dram->m_timing_cons[l][c])
        constraints.push_back(J::array({l,c,t.cmd,t.val,t.window,t.sibling,t.blocked_offset}));
  if (constraints!=J::parse(compiled_schedule::model_constraints))
    throw std::runtime_error("Compiled timing model mismatch; compile the changed semantics first");
  for(int cmd:{e.dram->m_commands("RD"),e.dram->m_commands("WR")})
    for(size_t l=0;l<e.dram->m_levels.size();++l)
      if(e.dram->m_actions[l][cmd]) throw std::runtime_error("Compiled command changes physical row state");
}

void materialize_compiled(Engine& e,CompiledPlan& p,CompiledStats& stats) {
  if(p.last_all<0) return;
  compiled_schedule::update(p.command,e.dram->m_channels[0],p.last_all);
  for(int b=0;b<8;++b) if(p.last[b]>=0)
    for(auto* node:p.paths[b]) if(node->m_level!=0)
      compiled_schedule::update(p.command,node,p.last[b]);
  ++stats.timing_materializations;
}

bool finish_compiled(Engine& e,CompiledPlan& p,CompiledStats& stats,const char* reason) {
  if(!p.active) return false;
  materialize_compiled(e,p,stats);p.active=false;++stats.exits[reason];
  if(!p.issued) return false;
  ++stats.segments;stats.commands+=p.issued;++stats.lengths[p.issued];return true;
}

bool prepare_compiled(Engine& e,CompiledPlan& p,CompiledStats& stats,int match_mode) {
  auto* c=e.ctrls[0];
  if(p.active) return true;
  if(c->m_active_buffer.size()||c->m_priority_buffer.size()) return false;
  bool mode=c->m_is_write_mode;
  if(!mode && (c->m_write_buffer.size()>c->m_wr_high_watermark*c->m_write_buffer.max_size || !c->m_read_buffer.size())) mode=true;
  else if(mode && c->m_write_buffer.size()<c->m_wr_low_watermark*c->m_write_buffer.max_size && c->m_read_buffer.size()) mode=false;
  auto& q=mode?c->m_write_buffer.buffer:c->m_read_buffer.buffer;
  if(q.size()<2) return false;
  ++stats.attempts;
  auto fail=[&](const char* why){++stats.rejection[why];return false;};
  int cmd=e.dram->m_commands(mode?"WR":"RD");
  size_t n=q.size();
  // Stop before hysteresis can select a different queue. This is a controller
  // boundary, separate from the generated shared/private timing certificate.
  if(mode && c->m_read_buffer.size())
    n=std::min(n,size_t(std::max(0.0,std::floor(double(q.size())-double(c->m_wr_low_watermark*c->m_write_buffer.max_size)))+1));
  if(n<2) return fail("short_policy_region");
  // mode 3 is the strong control: identical generated timing/proof kernel,
  // but resources are grouped from the current queue without an affine model.
  bool matches=match_mode==3;
  if(match_mode==0){
    size_t longest=1;
    for(auto stride:compiled_schedule::strides){
      size_t prefix=1;
      while(prefix<q.size() && q[prefix].addr==q.front().addr+Addr_t(prefix)*stride)++prefix;
      longest=std::max(longest,prefix);
    }
    if(longest<2)return fail("short_stride_or_rle");
    n=std::min(n,longest);matches=true;
  }
  if(!matches)for(auto stride:compiled_schedule::strides) {
    bool match=true;
    for(size_t i=0;i<q.size();++i) {
      bool same=match_mode==0?q[i].addr==q.front().addr+Addr_t(i)*stride:
        q[i].addr_vec[3]==((q.front().addr+Addr_t(i)*stride)/1024)%8;
      if(!same) {match=false;break;}
    }
    if(match) {matches=true;break;}
  }
  if(!matches&&match_mode==2) for(const auto& word:compiled_schedule::resource_words){
    for(size_t phase=0;phase<word.size();++phase){
      int shift=(q.front().addr_vec[3]-word[phase]+8)%8;bool match=true;
      for(size_t i=0;i<q.size();++i)if(q[i].addr_vec[3]!=(word[(phase+i)%word.size()]+shift)%8){match=false;break;}
      if(match){matches=true;break;}
    }
    if(matches)break;
  }
  if(!matches) return fail("outside_affine_bank_projection");
  std::array<long long,8> positions;positions.fill(-1);
  std::array<int,8> rows;rows.fill(-1);
  compiled_schedule::Entry entry;entry.now=e.clock();
  entry.shared_ready=e.dram->m_channels[0]->m_cmd_ready_clk[cmd];entry.private_ready.fill(-1);
  std::array<std::vector<Node*>,8> paths;
  for(size_t i=0;i<q.size();++i) {
    const auto& req=q[i];int b=req.addr_vec[3];
    if(i && req.arrive<q[i-1].arrive) return fail("non_fcfs_ages");
    if(positions[b]<0) {
      positions[b]=i;rows[b]=req.addr_vec[4];paths[b]=e.path(req.addr_vec);
      if(e.dram->get_preq_command(cmd,req.addr_vec)!=cmd) return fail("row_state");
      for(auto* node:paths[b]) if(node->m_level!=0)
        entry.private_ready[b]=std::max(entry.private_ready[b],(long long)node->m_cmd_ready_clk[cmd]);
    }else if(rows[b]!=req.addr_vec[4]) return fail("cross_row");
  }
  long long first;
  // All queued competitors participate in the certificate, even if hysteresis
  // limits the number of commands that this invocation will execute.
  if(!compiled_schedule::certify(cmd,entry,positions,q.front().addr_vec[3],first)) return fail("generated_guard");
  p=CompiledPlan();p.active=true;p.command=cmd;p.type=mode?Request::Type::Write:Request::Type::Read;
  p.planned=n;p.first=first;p.spacing=compiled_schedule::delta(cmd);p.paths=std::move(paths);
  ++stats.admitted;return true;
}

bool retain_compiled_arrival(Engine& e,CompiledPlan& p,Addr_t address,int type) {
  if(!p.active || !p.issued || type!=p.type) return false;
  Request mapped(address,type,-1,{});e.memory->m_addr_mapper->apply(mapped);
  return e.dram->get_preq_command(p.command,mapped.addr_vec)==p.command;
}

bool tick_compiled(Engine& e,CompiledPlan& p,CompiledStats& stats) {
  auto* c=e.ctrls[0];
  if(!p.active) {c->tick();++stats.fallback_ticks;return false;}
  c->poc_clock(c->poc_clock()+1);c->serve_completed_reads();e.refresh[0]->tick();
  c->m_is_write_mode=p.type==Request::Type::Write;
  auto& buffer=p.type==Request::Type::Read?c->m_read_buffer.buffer:c->m_write_buffer.buffer;
  if(!p.populated) {for(auto& req:buffer) req.command=p.command;p.populated=true;}
  Clk_t issue=p.first+Clk_t(p.issued)*p.spacing;
  if(c->poc_clock()!=issue) return false;
  auto req=buffer.front();
  if(req.is_first) {req.is_first=false;++c->s_num_row_hits;req.trace_row_status=0;}
  if(poc::selected_observer) poc::selected_observer(dynamic_cast<void*>(e.dram),0,issue,req,p.type==Request::Type::Read?2:3);
  if(poc::observer) poc::observer(dynamic_cast<void*>(e.dram),issue,p.command,req.addr_vec);
  ++poc::version;
  req.depart=issue+(p.type==Request::Type::Read?e.dram->m_read_latency:e.dram->m_write_latency);
  c->pending.push_back(std::move(req));
  p.last[buffer.front().addr_vec[3]]=issue;p.last_all=issue;++p.issued;buffer.erase(buffer.begin());
  if(p.issued==p.planned) return finish_compiled(e,p,stats,"region_end");
  return false;
}
