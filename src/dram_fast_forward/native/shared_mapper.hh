#pragma once
#include "dram_controller/addr_mapper.h"

namespace Ramulator {
class PoCSharedBankMapper final : public IAddrMapper,public Implementation {
  RAMULATOR_REGISTER_IMPLEMENTATION(IAddrMapper,PoCSharedBankMapper,"PoCSharedBank","Eight banks on one shared channel; 1KiB rows and 256B requests.");
  public:
    void init()override{}
    void setup(IFrontEnd*,IMemorySystem*)override{}
    void apply(Request& req)override {
      const auto line=req.addr/1024;
      req.addr_vec={0,0,0,int(line%8),int(line/8),int((req.addr%1024)/16)};
    }
};
}
