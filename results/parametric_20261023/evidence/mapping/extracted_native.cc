#include <cstdint>
#include <iostream>
using u64=uint64_t;
static unsigned mapping_shift = 9; // Fixed per simulated case, never per requesting core.
static int bank_color_shift = -1;
static unsigned color_banks = 0;
static u64 weight_region_end = 0;
static unsigned weight_shift = 9, data_shift = 9;
unsigned address_shift(u64 addr) { return addr<weight_region_end?weight_shift:data_shift; }
unsigned endpoint(u64 addr,unsigned cores) {
  unsigned bits=cores==64?6:5, poly=cores==64?0x43:0x25, r=0;
  u64 b=addr>>address_shift(addr);
  for (int i=63; i>=0; --i) { r=(r<<1)|((b>>i)&1); if(r&(1u<<bits)) r^=poly; }
  return r;
}
u64 local_address(u64 addr,unsigned cores) {
  const unsigned bits=cores==64?6:5;
  unsigned shift=address_shift(addr);
  u64 local=((addr>>(shift+bits))<<shift)|(addr&((u64(1)<<shift)-1));
  if(bank_color_shift<0)return local;
  const u64 block=local/1024,row=block/color_banks;
  const unsigned bank=(block%color_banks)^((row>>bank_color_shift)&(color_banks-1));
  return (row*color_banks+bank)*1024+(local%1024);
}


int main(){u64 a;while(std::cin>>a)std::cout<<endpoint(a,64)<<" "<<local_address(a,64)<<"\n";}
