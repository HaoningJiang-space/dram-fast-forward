#pragma once
#include "parametric_schedule.hh"

struct ParametricPlan {
  bool admitted=false;
  std::string reason="no_region";
  size_t cursor=0;
  std::vector<parametric_schedule::Command> commands;
  uint64_t scheduler_selections=0;
};

bool admit_parametric(Engine& e,const J& config,ParametricPlan& plan) {
  if(!e.shared_bus || e.ctrls.size()!=1 || config.value("devices",1)!=1 ||
     config.value("closed_loop",false) || config.contains("followups")) {
    plan.reason="external_boundary";return false;
  }
  J constraints=J::array();
  for(size_t l=0;l<e.dram->m_levels.size();++l)
    for(size_t c=0;c<e.dram->m_commands.size();++c)
      for(auto& t:e.dram->m_timing_cons[l][c])
        constraints.push_back(J::array({l,c,t.cmd,t.val,t.window,t.sibling,t.blocked_offset}));
  if(constraints!=J::parse(parametric_schedule::constraints_json)) {
    plan.reason="timing_model";return false;
  }
  auto program=J::parse(parametric_schedule::program_json);
  int n=config.at("producer_length"),profile=config.at("row_profile");
  auto parameters=config.at("parameters").get<std::vector<long long>>();
  if(!parametric_schedule::select(n,profile,parameters,plan.commands))return false;
  J expected=J::array();std::array<int,8> rows;rows.fill(-1);
  int p=0;
  for(auto& producer:program["producers"]){
    long long offset=0;
    for(size_t i=0;i<parameters.size();++i)offset+=parameters[i]*producer["offset_coefficients"][i].get<int>();
    for(int i=0;i<n;++i){
      long long address=producer["local_addresses"][i];
      expected.push_back(J::array({offset+i*program.value("arrival_gap",0),address,0,p*1000+i}));
      int b=address/1024%8;
      if(profile && rows[b]<0)rows[b]=address/8192+(profile==2);
    }++p;
  }
  std::stable_sort(expected.begin(),expected.end(),[](auto&a,auto&b){return a[0]<b[0];});
  if(expected!=config["requests"] || J(rows)!=config.at("initial_rows")){
    plan.reason="producer_contract";return false;
  }
  if(plan.commands.empty() || plan.commands.back().cycle+e.dram->m_read_latency>=e.refresh[0]->m_next_refresh_cycle){
    plan.reason="refresh_boundary";return false;
  }
  // No ready test, prerequisite computation or FCFS scan in this hook. The
  // queue lookup executes the selected request identity, it does not select it.
  poc::scheduler_override=[&plan](void*,int,Clk_t now,ReqBuffer& active,ReqBuffer& reads,
                                  ReqBuffer::iterator& it,ReqBuffer*& buffer) {
    if(plan.cursor==plan.commands.size())return -1;
    auto& next=plan.commands[plan.cursor];
    if(now<next.cycle)return 0;
    if(now>next.cycle)throw std::runtime_error("Missed compiled command");
    for(auto* q:{&active,&reads})for(auto r=q->begin();r!=q->end();++r)
      if(r->trace_core_id==next.id){
        r->command=next.command;it=r;buffer=q;++plan.cursor;++plan.scheduler_selections;return 1;
      }
    throw std::runtime_error("Compiled producer was not admitted");
  };
  plan.admitted=true;plan.reason="compiled";return true;
}
