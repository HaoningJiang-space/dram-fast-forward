#pragma once
#include <array>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <map>
#include <string>
#include <vector>
#include "base/request.h"

namespace poc {
using Record=std::array<int64_t,12>;
inline std::ofstream capture;
inline std::map<const void*,unsigned> devices;
inline uint64_t version=1,sequence=0;
inline bool incremental=false;
inline std::map<std::pair<void*,int>,uint64_t> generations;
inline uint64_t generation(void* p,int channel){return generations[{p,channel}];}
inline void changed(void* p,int channel){++version;if(incremental)++generations[{p,channel}];}
inline uint64_t preq_scans=0,preq_skips=0;
inline std::function<void(void*,Ramulator::Clk_t,int,const Ramulator::AddrVec_t&)> observer;
inline unsigned device(const void* p) {
  auto [it,inserted]=devices.emplace(p,devices.size());return it->second;
}
inline void capture_record(const Record& row) {
  if(capture.is_open())capture.write(reinterpret_cast<const char*>(row.data()),sizeof(row));
}
inline void configure_capture() {
  if(auto* path=std::getenv("LEANWAFER_POC_TRACE"))capture.open(path,std::ios::binary|std::ios::trunc);
}
inline const bool capture_initialized=(configure_capture(),true);
inline uint64_t wrap(void* dram,int channel,Ramulator::Request& req,Ramulator::Clk_t* clk) {
  if(!capture.is_open())return 0;
  uint64_t id=++sequence;auto old=req.callback;auto d=device(dram);
  req.callback=[old,id,d,channel,clk](Ramulator::Request& done) {
    Record row{};row[0]=3;row[1]=d;row[2]=channel;row[3]=*clk;row[4]=id;row[5]=done.addr;row[6]=done.type_id;
    capture_record(row);if(old)old(done);
  };return id;
}
inline void arrival(void* dram,int channel,const Ramulator::Request& req,Ramulator::Clk_t clk,uint64_t id,bool accepted) {
  if(accepted)changed(dram,channel);
  if(!capture.is_open())return;
  Record row{};row[0]=1;row[1]=device(dram);row[2]=channel;row[3]=clk;row[4]=id;row[5]=req.addr;row[6]=req.type_id;row[7]=accepted;
  capture_record(row);
}
inline void command(void* dram,Ramulator::Clk_t clk,int cmd,const Ramulator::AddrVec_t& address,bool mutates=true) {
  ++version;if(incremental&&mutates)++generations[{dram,address.at(0)}];
  if(observer)observer(dram,clk,cmd,address);
  if(!capture.is_open())return;
  Record row{};row[0]=2;row[1]=device(dram);row[2]=address.at(0);row[3]=clk;row[4]=cmd;
  if(address.size()>7)throw std::runtime_error("Capture address exceeds PoC record");
  for(size_t i=0;i<address.size();++i)row[5+i]=address[i];capture_record(row);
}
}
