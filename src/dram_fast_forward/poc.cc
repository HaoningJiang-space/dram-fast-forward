// Included implementation copies are frozen by build.py; original tick paths
// remain available in every mode. Visibility changes support state inspection.
#include "base/base.h"
#include "base/config.h"
#include "frontend/frontend.h"
#include "memory_system/memory_system.h"
#include "poc_hooks.hh"
#include "3D_DRAM.cpp"
#include "scheduler.cpp"
#include "refresh.cpp"
#include "controller.cpp"
#include "memory.cpp"
#include <json/json.hpp>
#include <chrono>
#include <ctime>
#include <filesystem>
#include <iomanip>
#include <limits>
#include <numeric>
#include <set>

using namespace Ramulator;
using J=nlohmann::json;
using C=GenericDRAMController;
using D=DRAM3D;
using M=GenericDRAMSystem;
using R=AllBankRefresh;
using Node=D::Node;
namespace fs=std::filesystem;

struct Sink {
  bool audit;std::ofstream output;uint64_t hash=14695981039346656037ull;
  std::array<uint64_t,4> counts{};
  Sink(bool enabled,const fs::path& path):audit(enabled) {if(audit)output.open(path,std::ios::binary);}
  void add(poc::Record row) {
    ++counts.at(row[0]);if(!audit)return;
    for(auto value:row)for(unsigned i=0;i<8;++i){hash^=uint8_t(uint64_t(value)>>(8*i));hash*=1099511628211ull;}
    output.write(reinterpret_cast<const char*>(row.data()),sizeof(row));
  }
};
J read_json(const fs::path& p){std::ifstream f(p);if(!f)throw std::runtime_error("Missing JSON");J j;f>>j;return j;}
void write_json(const fs::path& p,const J& j){std::ofstream f(p);f<<j.dump(2)<<'\n';}
uint64_t digest(const J& j){uint64_t h=14695981039346656037ull;for(unsigned char c:j.dump()){h^=c;h*=1099511628211ull;}return h;}

J req_state(const Request& r) {
  return J::array({r.addr,r.addr_vec,r.type_id,r.source_id,r.is_first,r.command,r.final_command,
                   r.arrive,r.depart,r.trace_arrive,r.trace_depart,r.trace_row_status,r.trace_open_row,r.trace_core_id});
}
template<class Queue> J queue_state(const Queue& q){J out=J::array();for(const auto& r:q)out.push_back(req_state(r));return out;}
J node_state(const Node* p) {
  J children=J::array();for(auto* c:p->m_child_nodes)children.push_back(node_state(c));
  return J::array({p->m_level,p->m_node_id,p->m_state,p->m_row_state,p->m_cmd_ready_clk,p->m_cmd_history,children});
}
struct Engine {
  IFrontEnd* frontend;M* memory;D* dram;std::vector<C*> ctrls;std::vector<R*> refresh;
  explicit Engine(const std::string& yaml) {
    auto config=Config::parse_config_file(yaml,{});config["Frontend"]["impl"]="LeanWaferExternal";
    frontend=Factory::create_frontend(config);memory=dynamic_cast<M*>(Factory::create_memory_system(config));
    frontend->connect_memory_system(memory);memory->connect_frontend(frontend);dram=dynamic_cast<D*>(memory->m_dram);
    if(!dram||!dram->m_direct_bank_access)throw std::runtime_error("PoC requires frozen direct-bank model");
    for(auto* base:memory->m_controllers) {
      auto* c=dynamic_cast<C*>(base);auto* r=dynamic_cast<R*>(c->m_refresh);
      if(!c||!r||!c->m_plugins.empty())throw std::runtime_error("Unsupported controller/refresh/plugin");
      ctrls.push_back(c);refresh.push_back(r);
    }
  }
  Clk_t clock()const{return memory->m_clk;}
  void set_clock(Clk_t t) {
    memory->m_clk=t;dram->poc_clock(t);
    for(size_t i=0;i<ctrls.size();++i){ctrls[i]->poc_clock(t);refresh[i]->m_clk=t;}
  }
  bool busy()const {
    for(auto* c:ctrls)if(!c->pending.empty()||c->m_active_buffer.size()||c->m_priority_buffer.size()||c->m_read_buffer.size()||c->m_write_buffer.size())return true;
    return false;
  }
  J state()const {
    J cs=J::array(),nodes=J::array();
    for(size_t i=0;i<ctrls.size();++i){auto* c=ctrls[i];auto* r=refresh[i];
      cs.push_back(J::array({c->poc_clock(),c->m_is_write_mode,queue_state(c->pending),queue_state(c->m_active_buffer.buffer),
        queue_state(c->m_priority_buffer.buffer),queue_state(c->m_read_buffer.buffer),queue_state(c->m_write_buffer.buffer),
        c->s_num_row_hits,c->s_num_row_misses,c->s_num_row_conflicts,r->m_clk,r->m_next_refresh_cycle}));}
    for(auto* node:dram->m_channels)nodes.push_back(node_state(node));
    return J{{"clock",clock()},{"dram_clock",dram->poc_clock()},{"counters",J::array({memory->s_num_read_requests,memory->s_num_write_requests,memory->s_num_other_requests})},{"controllers",cs},{"nodes",nodes}};
  }
  std::vector<Node*> path(const AddrVec_t& address)const {
    std::vector<Node*> out;auto* node=dram->m_channels.at(address[0]);
    while(true){out.push_back(node);if(node->m_child_nodes.empty())break;node=node->m_child_nodes.at(address.at(node->m_level+1));}
    return out;
  }
  Clk_t ready(int cmd,const AddrVec_t& address)const {
    Clk_t t=clock()+1;
    auto* n=dram->m_channels.at(address.at(0));
    while(true){
      t=std::max(t,n->m_cmd_ready_clk.at(cmd));
      if(n->m_level==dram->m_command_scopes[cmd]||n->m_child_nodes.empty()||address.at(n->m_level+1)<0)break;
      n=n->m_child_nodes.at(address.at(n->m_level+1));
    }return t;
  }
  Clk_t next_event(Clk_t arrival)const {
    Clk_t next=arrival;
    for(size_t i=0;i<ctrls.size();++i){auto* c=ctrls[i];next=std::min(next,refresh[i]->m_next_refresh_cycle);
      if(!c->pending.empty())next=std::min(next,std::max(clock()+1,c->pending.front().depart));
      if(next<=clock()+1)return clock()+1;
      // Even an otherwise idle tick may change read/write policy state.
      bool next_mode=c->m_is_write_mode;
      if(!next_mode){
        if(c->m_write_buffer.size()>c->m_wr_high_watermark*c->m_write_buffer.max_size||c->m_read_buffer.size()==0)next_mode=true;
      }else if(c->m_write_buffer.size()<c->m_wr_low_watermark*c->m_write_buffer.max_size&&c->m_read_buffer.size()!=0)next_mode=false;
      if(next_mode!=c->m_is_write_mode)return clock()+1;
      for(auto* buffer:{&c->m_active_buffer,&c->m_priority_buffer,&c->m_read_buffer,&c->m_write_buffer})
        for(const auto& req:*buffer){
          int cmd=dram->get_preq_command(req.final_command,req.addr_vec);next=std::min(next,ready(cmd,req.addr_vec));
          if(next<=clock()+1)return clock()+1;
        }
    }
    return std::max(clock()+1,next);
  }
};

struct PocStats {
  bool keep_intervals=false;
  uint64_t bulk_reads=0,bulk_segments=0,skipped_cycles=0,normal_ticks=0;
  std::vector<std::array<int64_t,8>> intervals;
  std::map<std::string,uint64_t> rejected;
  std::map<size_t,uint64_t> lengths;
  void fail(const char* reason){if(keep_intervals)++rejected[reason];}
};

// Strict sufficient guard. Other controllers must have no queued work, and
// every skipped tick precedes external arrival and every refresh deadline.
bool bulk(Engine& e,Clk_t horizon,bool closed_loop,PocStats& stats) {
  C* c=nullptr;size_t ci=0;
  for(size_t i=0;i<e.ctrls.size();++i){auto* x=e.ctrls[i];
    if(x->m_read_buffer.size()||x->m_active_buffer.size()||x->m_priority_buffer.size()||x->m_write_buffer.size()||!x->pending.empty()){
      if(c){stats.fail("other_channel_work");return false;}c=x;ci=i;
    }}
  if(!c||c->m_read_buffer.size()<2){stats.fail("too_few_reads");return false;}
  if(c->m_active_buffer.size()||c->m_priority_buffer.size()||c->m_write_buffer.size()){
    stats.fail("active_priority_or_write");return false;}
  for(auto* r:e.refresh)horizon=std::min(horizon,r->m_next_refresh_cycle);
  if(closed_loop&&!c->pending.empty())horizon=std::min(horizon,std::max(e.clock()+1,c->pending.front().depart));
  int rd=e.dram->m_commands("RD"),pre=e.dram->m_commands("PRE");
  auto& buffer=c->m_read_buffer.buffer;const auto address=buffer.front().addr_vec;
  if(e.dram->get_preq_command(rd,address)!=rd){stats.fail("row_not_open");return false;}
  auto path=e.path(address);Clk_t delta=1;bool pre_blocks=false;
  for(auto* node:path){
    if(e.dram->m_actions[node->m_level][rd]){stats.fail("rd_state_action");return false;}
    for(auto& timing:e.dram->m_timing_cons[node->m_level][rd]){
      if(timing.sibling||timing.window!=1||timing.blocked_offset>0){stats.fail("unsupported_timing");return false;}
      if(timing.cmd==rd)delta=std::max(delta,Clk_t(timing.val));
    }}
  // PRE cannot slip into an otherwise idle RD spacing interval.
  for(auto* node:path)for(auto& timing:e.dram->m_timing_cons[node->m_level][rd])
    if(timing.cmd==pre&&timing.val>=delta)pre_blocks=true;
  if(!pre_blocks){stats.fail("precharge_can_intervene");return false;}
  Clk_t first=e.ready(rd,address),last=horizon-1;
  if(closed_loop)last=std::min(last,first+e.dram->m_read_latency-1);
  size_t n=0;Addr_t stride=buffer[1].addr-buffer[0].addr;
  for(size_t i=0;i<buffer.size();++i){const auto& req=buffer[i];
    if(req.type_id!=Request::Type::Read||req.addr_vec[0]!=address[0]||req.addr_vec[4]!=address[4]||
       req.addr!=buffer[0].addr+Addr_t(i)*stride||first+Clk_t(i)*delta>last)break;
    ++n;
  }
  if(n<2){stats.fail("short_affine_or_boundary");return false;}
  for(const auto& req:buffer){
    int cmd=e.dram->get_preq_command(req.final_command,req.addr_vec);
    if((cmd!=rd&&cmd!=pre)||e.ready(cmd,req.addr_vec)<first){stats.fail("other_command_before_first");return false;}
  }
  for(size_t i=1;i<buffer.size();++i)if(buffer[i].arrive<buffer[i-1].arrive){stats.fail("non_fcfs_arrival");return false;}
  for(size_t i=0;i<e.ctrls.size();++i)if(i!=ci&&e.ctrls[i]->m_is_write_mode==false){stats.fail("idle_mode_unsettled");return false;}
  // Populate prerequisite fields exactly as the original scheduler would.
  for(auto& req:buffer)req.command=e.dram->get_preq_command(req.final_command,req.addr_vec);
  c->m_is_write_mode=false;const Clk_t old=e.clock();Clk_t last_callback=old;
  auto serve=[&](Clk_t until){
    Clk_t next=last_callback+1;
    while(!c->pending.empty()){
      next=std::max(next,c->pending.front().depart);if(next>until)break;
      e.set_clock(next);c->serve_completed_reads();last_callback=next;++next;
    }
  };
  // Command/callback observables remain per-request. The device state update
  // below is one affine aggregate; no per-command timing/scheduler call.
  for(size_t i=0;i<n;++i){Clk_t t=first+Clk_t(i)*delta;serve(t);e.set_clock(t);
    auto req=buffer[i];if(req.is_first){req.is_first=false;++c->s_num_row_hits;req.trace_row_status=0;}
    if(poc::observer)poc::observer(dynamic_cast<void*>(e.dram),t,rd,req.addr_vec);
    ++poc::version;req.depart=t+e.dram->m_read_latency;c->pending.push_back(std::move(req));
  }
  const Clk_t end=first+Clk_t(n-1)*delta;
  for(auto* node:path){
    auto& history=node->m_cmd_history[rd];if(!history.empty())history.front()=end;
    for(const auto& timing:e.dram->m_timing_cons[node->m_level][rd])
      node->m_cmd_ready_clk[timing.cmd]=std::max(node->m_cmd_ready_clk[timing.cmd],end+timing.val);
  }
  buffer.erase(buffer.begin(),buffer.begin()+n);e.set_clock(end);
  if(stats.keep_intervals)stats.intervals.push_back({old,first,end,int64_t(n),delta,horizon,int64_t(ci),closed_loop});
  stats.bulk_reads+=n;++stats.bulk_segments;stats.skipped_cycles+=end-old;++stats.lengths[n];return true;
}

int main(int argc,char**argv) {
  try {
    if(argc!=4)throw std::runtime_error("Usage: dram_poc CONFIG.json MODE OUTPUT");
    auto config=read_json(argv[1]);std::string mode=argv[2];fs::path out=argv[3];fs::create_directory(out);
    if(mode!="reference"&&mode!="event"&&mode!="incremental"&&mode!="symbolic")throw std::runtime_error("Unknown mode");
    spdlog::set_level(spdlog::level::off);
    std::vector<std::unique_ptr<Engine>> engines;
    for(unsigned i=0;i<config.value("devices",1u);++i){
      engines.push_back(std::make_unique<Engine>(config.at("dram_yaml")));
      poc::device(dynamic_cast<void*>(engines.back()->dram));
    }
    auto& engine=*engines.at(0);
    auto world_state=[&](){J out=J::array();for(auto& e:engines)out.push_back(e->state());return out;};
    auto world_busy=[&](){for(auto& e:engines)if(e->busy())return true;return false;};
    auto world_clock=[&](Clk_t t){for(auto& e:engines)e->set_clock(t);};
    bool audit=config.value("audit",true),closed=config.value("closed_loop",false);
    const bool symbolic=mode=="symbolic",event_driven=mode=="event",allow_symbolic=config.value("allow_symbolic",true);
    const Clk_t max_cycles=config.value("max_cycles",1000000000ll);
    Sink sink(audit,out/"events.bin");PocStats stats;stats.keep_intervals=audit;poc::incremental=mode=="incremental";
    poc::observer=[&](void* device,Clk_t t,int cmd,const AddrVec_t& address){poc::Record row{};row[0]=2;row[1]=poc::device(device);row[2]=address[0];row[3]=t;row[4]=cmd;for(size_t i=0;i<address.size();++i)row[5+i]=address[i];sink.add(row);};
    struct Input {Clk_t at;Addr_t address;int type,id;unsigned device=0;};std::deque<Input> arrivals;
    for(const auto& row:config.at("requests"))arrivals.push_back({row[0],row[1],row[2],row[3],row.size()>4?row[4].get<unsigned>():0u});
    uint64_t accepted=0,completed=0,rejected=0;auto total=arrivals.size();
    auto enqueue=[&](Input item){
      auto& local=*engines.at(item.device);
      Request req(item.address,item.type,-1,[&,id=item.id,device=item.device,source=&local](Request& done){
        poc::Record row{};row[0]=3;row[1]=device;row[2]=done.addr_vec[0];row[3]=source->clock();row[4]=id;row[5]=done.addr;row[6]=done.type_id;sink.add(row);++completed;
        if(closed&&config.contains("followups")){
          auto key=std::to_string(id);if(config["followups"].contains(key)){
            const auto& f=config["followups"][key];Input next{source->clock()+f[0].get<Clk_t>(),f[1],f[2],f[3],device};
            auto pos=std::upper_bound(arrivals.begin(),arrivals.end(),next.at,[](Clk_t t,const Input& i){return t<i.at;});arrivals.insert(pos,next);++total;
          }}
      });
      req.trace_core_id=item.id;
      bool ok=local.memory->send(req);poc::Record row{};row[0]=1;row[1]=item.device;row[2]=(item.address/1024)%local.ctrls.size();row[3]=local.clock();row[4]=item.id;row[5]=item.address;row[6]=item.type;row[7]=ok;sink.add(row);
      if(ok)++accepted;else ++rejected;return ok;
    };
    std::set<Clk_t> checkpoints;
    if(config.contains("checkpoints"))for(auto t:read_json(config["checkpoints"].get<std::string>()))checkpoints.insert(t.get<Clk_t>());
    J checkpoint_rows=J::array();
    std::ofstream state_stream(out/"checkpoint_states.jsonl");
    auto record_checkpoint=[&](){
      auto state=world_state();checkpoint_rows.push_back(J::array({engine.clock(),digest(state)}));
      state_stream<<J({{"cycle",engine.clock()},{"state",state}}).dump()<<'\n';
    };
    const auto start=std::chrono::steady_clock::now();auto cpu_start=std::clock();
    while(!arrivals.empty()||world_busy()){
      while(!arrivals.empty()&&arrivals.front().at<=engine.clock()){
        auto item=arrivals.front();if(!enqueue(item))break;arrivals.pop_front();
      }
      Clk_t horizon=arrivals.empty()?std::numeric_limits<Clk_t>::max()/4:std::max(engine.clock()+1,arrivals.front().at);
      if(!checkpoints.empty())horizon=std::min(horizon,*checkpoints.begin()+1);
      bool jumped=false;
      if(symbolic&&allow_symbolic){
        Engine* candidate=nullptr;bool safe=true;
        for(auto& e:engines){
          if(e->busy()){if(candidate){safe=false;break;}candidate=e.get();}
          else for(auto* c:e->ctrls)if(!c->m_is_write_mode){safe=false;break;}
        }
        if(safe&&candidate){
          for(auto& e:engines)for(auto* r:e->refresh)horizon=std::min(horizon,r->m_next_refresh_cycle);
          jumped=bulk(*candidate,horizon,closed,stats);if(jumped)world_clock(candidate->clock());
        }else stats.fail("other_device_work_or_unsettled");
      }
      if(jumped){if(audit)record_checkpoint();}
      else {
        if(event_driven){
          Clk_t next=horizon;
          for(auto& e:engines){next=std::min(next,e->next_event(horizon));if(next<=engine.clock()+1)break;}
          if(!checkpoints.empty())next=std::min(next,*checkpoints.begin());
          if(next>engine.clock()+1){stats.skipped_cycles+=next-engine.clock()-1;world_clock(next-1);}
        }
        for(auto& e:engines)e->memory->tick();++stats.normal_ticks;
      }
      if(checkpoints.erase(engine.clock()))record_checkpoint();
      if(engine.clock()>max_cycles)throw std::runtime_error("PoC drain limit exceeded");
    }
    auto seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    auto cpu_seconds=double(std::clock()-cpu_start)/CLOCKS_PER_SEC;
    if(accepted!=total||completed!=total)throw std::runtime_error("Unfinished requests");
    if(!checkpoints.empty())throw std::runtime_error("Missed requested state checkpoint");
    write_json(out/"state.json",world_state());write_json(out/"checkpoints.json",checkpoint_rows);
    write_json(out/"intervals.json",stats.intervals);
    J report={{"status","pass"},{"mode",mode},{"requests",total},{"accepted",accepted},{"completed",completed},{"rejected_attempts",rejected},
      {"end_cycle",engine.clock()},{"host_seconds",seconds},{"host_cpu_seconds",cpu_seconds},{"commands",sink.counts[2]},{"event_fnv1a64",sink.hash},
      {"normal_ticks",stats.normal_ticks},{"skipped_cycles",stats.skipped_cycles},{"bulk_reads",stats.bulk_reads},{"bulk_segments",stats.bulk_segments},
      {"segment_lengths",stats.lengths},{"guard_failures",stats.rejected},{"preq_scans",poc::preq_scans},{"preq_skips",poc::preq_skips},
      {"devices",engines.size()},{"channels",engine.ctrls.size()},{"nBL",engine.dram->m_timing_vals("nBL")},{"read_latency",engine.dram->m_read_latency},{"nREFI",engine.refresh[0]->m_nrefi},
      {"command_ids",{{"RD",engine.dram->m_commands("RD")},{"WR",engine.dram->m_commands("WR")},{"ACT",engine.dram->m_commands("ACT")},{"PRE",engine.dram->m_commands("PRE")},{"REFab",engine.dram->m_commands("REFab")}}}};
    write_json(out/"summary.json",report);std::cout<<report.dump()<<'\n';return 0;
  }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
