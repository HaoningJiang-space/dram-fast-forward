#pragma once

// Online resource plans: independent bank roots or a shared channel. No future
// command order is consulted. Arrivals revalidate the certificate; relevant
// changes materialize the executed prefix. Global event dispatch stays exact.
struct BankPlan {
  bool active=false,preqs_populated=false,shared=false;
  size_t planned=0,issued=0;
  Clk_t first=0,delta=1,last_issued=-1;
  AddrVec_t address;
  std::vector<Node*> nodes;
  std::vector<std::vector<Node*>> node_paths;
};

struct BankStats {
  uint64_t reads=0,segments=0,reads_in_segments_ge2=0,attempts=0;
  uint64_t live=0,peak_live=0,reads_while_plans_coexist=0;
  uint64_t retained_arrival_attempts=0;
  std::map<std::string,uint64_t> exits;
  std::map<size_t,uint64_t> lengths;
};

void materialize_bank(Engine& e,BankPlan& p) {
  if(p.last_issued<0)return;
  const int rd=e.dram->m_commands("RD");
  std::map<Node*,Clk_t> latest;
  if(p.shared){
    for(size_t i=0;i<p.issued;++i)for(auto* node:p.node_paths[i])
      latest[node]=p.first+Clk_t(i)*p.delta;
  }else for(auto* node:p.nodes)latest[node]=p.last_issued;
  for(auto [node,last]:latest){
    auto& history=node->m_cmd_history[rd];
    if(!history.empty())history.front()=last;
    for(const auto& timing:e.dram->m_timing_cons[node->m_level][rd])
      node->m_cmd_ready_clk[timing.cmd]=std::max(node->m_cmd_ready_clk[timing.cmd],last+timing.val);
  }
}

bool finish_bank(Engine& e,BankPlan& p,BankStats& stats,const char* why) {
  if(!p.active)return false;
  materialize_bank(e,p);p.active=false;--stats.live;++stats.exits[why];
  if(!p.issued)return false;
  ++stats.segments;stats.reads+=p.issued;++stats.lengths[p.issued];
  if(p.issued>=2)stats.reads_in_segments_ge2+=p.issued;
  return true;
}

bool prepare_bank(Engine& e,size_t ci,BankPlan& p,BankStats& stats,bool affine_only) {
  auto* c=e.ctrls[ci];
  if(p.active||c->m_read_buffer.size()<2||c->m_active_buffer.size()||
     c->m_priority_buffer.size()||c->m_write_buffer.size())return false;
  ++stats.attempts;
  const int rd=e.dram->m_commands("RD"),pre=e.dram->m_commands("PRE");
  auto& buffer=c->m_read_buffer.buffer;const auto address=buffer.front().addr_vec;
  if(e.dram->get_preq_command(rd,address)!=rd)return false;
  auto path=e.path(address);Clk_t delta=1;bool pre_blocks=false;
  for(auto* node:path){
    if(e.dram->m_actions[node->m_level][rd])return false;
    for(const auto& timing:e.dram->m_timing_cons[node->m_level][rd]){
      if(timing.sibling||timing.window!=1||timing.blocked_offset>0)return false;
      if(timing.cmd==rd)delta=std::max(delta,Clk_t(timing.val));
    }
  }
  for(auto* node:path)for(const auto& timing:e.dram->m_timing_cons[node->m_level][rd])
    if(timing.cmd==pre&&timing.val>=delta)pre_blocks=true;
  if(!pre_blocks)return false;
  const Clk_t first=e.ready(rd,address);
  size_t n=0;const Addr_t stride=buffer[1].addr-buffer[0].addr;
  for(size_t i=0;i<buffer.size();++i){
    const auto& req=buffer[i];
    if(req.type_id!=Request::Type::Read||req.addr_vec[0]!=address[0]||req.addr_vec[4]!=address[4]||
       (affine_only&&req.addr!=buffer[0].addr+Addr_t(i)*stride))break;
    ++n;
  }
  if(n<2)return false;
  for(const auto& req:buffer){
    int cmd=e.dram->get_preq_command(req.final_command,req.addr_vec);
    if((cmd!=rd&&cmd!=pre)||e.ready(cmd,req.addr_vec)<first)return false;
  }
  for(size_t i=1;i<buffer.size();++i)if(buffer[i].arrive<buffer[i-1].arrive)return false;
  // Row state stays unchanged throughout this plan. These are exactly the
  // prerequisite fields the reference scheduler would recompute each tick.
  p.active=true;p.shared=false;p.preqs_populated=false;p.planned=n;p.issued=0;p.first=first;p.delta=delta;p.last_issued=-1;
  p.address=address;p.nodes=std::move(path);++stats.live;
  stats.peak_live=std::max(stats.peak_live,stats.live);return true;
}

bool prepare_shared(Engine& e,size_t ci,BankPlan& p,BankStats& stats,bool affine_only) {
  auto* c=e.ctrls[ci];auto& buffer=c->m_read_buffer.buffer;
  if(p.active||buffer.size()<2||c->m_active_buffer.size()||c->m_priority_buffer.size())return false;
  bool mode=c->m_is_write_mode;
  if(!mode&&c->m_write_buffer.size()>c->m_wr_high_watermark*c->m_write_buffer.max_size)mode=true;
  else if(mode&&c->m_write_buffer.size()<c->m_wr_low_watermark*c->m_write_buffer.max_size)mode=false;
  if(mode)return false;
  ++stats.attempts;
  const int rd=e.dram->m_commands("RD");Clk_t delta=1;
  std::vector<std::vector<Node*>> paths;
  for(const auto& req:buffer){
    if(e.dram->get_preq_command(rd,req.addr_vec)!=rd)return false;
    auto path=e.path(req.addr_vec);
    for(auto* node:path){
      if(e.dram->m_actions[node->m_level][rd])return false;
      for(const auto& timing:e.dram->m_timing_cons[node->m_level][rd]){
        if(timing.sibling||timing.window!=1||timing.blocked_offset>0)return false;
        if(timing.cmd==rd)delta=std::max(delta,Clk_t(timing.val));
      }
    }
    paths.push_back(std::move(path));
  }
  const Clk_t first=e.ready(rd,buffer.front().addr_vec);
  // Any ready request before `first` would invalidate FCFS dominance.
  for(const auto& req:buffer)if(e.ready(rd,req.addr_vec)<first)return false;
  for(size_t i=1;i<buffer.size();++i)if(buffer[i].arrive<buffer[i-1].arrive)return false;
  size_t n=0;const Addr_t stride=buffer[1].addr-buffer[0].addr;
  for(size_t i=0;i<buffer.size();++i){
    if(affine_only&&buffer[i].addr!=buffer[0].addr+Addr_t(i)*stride)break;
    if(e.ready(rd,buffer[i].addr_vec)>first+Clk_t(i)*delta)break;
    ++n;
  }
  if(n<2)return false;
  paths.resize(n);p.node_paths=std::move(paths);
  p.active=true;p.shared=true;p.preqs_populated=false;p.planned=n;p.issued=0;
  p.first=first;p.delta=delta;p.last_issued=-1;++stats.live;
  stats.peak_live=std::max(stats.peak_live,stats.live);return true;
}

// Called in original memory->channel order, after the device clock advances.
bool tick_bank(Engine& e,size_t ci,BankPlan& p,BankStats& stats) {
  auto* c=e.ctrls[ci];
  if(!p.active){c->tick();return false;}
  c->poc_clock(c->poc_clock()+1);
  c->serve_completed_reads();e.refresh[ci]->tick();
  c->m_is_write_mode=false;
  if(!p.preqs_populated){
    for(auto& req:c->m_read_buffer.buffer)req.command=e.dram->get_preq_command(req.final_command,req.addr_vec);
    p.preqs_populated=true;
  }
  const Clk_t issue=p.first+Clk_t(p.issued)*p.delta;
  if(c->poc_clock()!=issue)return false;
  auto& buffer=c->m_read_buffer.buffer;
  auto req=buffer.front();
  if(req.is_first){req.is_first=false;++c->s_num_row_hits;req.trace_row_status=0;}
  if(poc::selected_observer)poc::selected_observer(dynamic_cast<void*>(e.dram),int(ci),issue,req,2);
  if(poc::observer)poc::observer(dynamic_cast<void*>(e.dram),issue,e.dram->m_commands("RD"),req.addr_vec);
  ++poc::version;req.depart=issue+e.dram->m_read_latency;c->pending.push_back(std::move(req));
  buffer.erase(buffer.begin());p.last_issued=issue;++p.issued;
  if(stats.live>1)++stats.reads_while_plans_coexist;
  if(p.issued==p.planned)return finish_bank(e,p,stats,"prefix_end");
  return false;
}
