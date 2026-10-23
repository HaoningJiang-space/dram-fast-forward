"""Explicit shared-bus validation fixture; direct-bank timing is unchanged.

This is an experimental timing profile, not a calibrated DDR4 product model.
Both precise and symbolic executions use the same generated physical code.
"""

SHARED_TIMINGS=r'''
      if (m_config["org"]["shared_bus_validation"] && m_config["org"]["shared_bus_validation"].as<bool>()) {
        m_write_latency = m_timing_vals("nCWL") + m_timing_vals("nBL");
        #define V(timing) (m_timing_vals(timing))
        populate_timingcons(this, {
          {.level="channel", .preceding={"RD","RDA"}, .following={"RD","RDA"}, .latency=V("nBL")},
          {.level="channel", .preceding={"WR","WRA"}, .following={"WR","WRA"}, .latency=V("nBL")},
          {.level="channel", .preceding={"RD","RDA"}, .following={"WR","WRA"}, .latency=V("nCL")+V("nBL")-V("nCWL")+V("nRTW")},
          {.level="channel", .preceding={"WR","WRA"}, .following={"RD","RDA"}, .latency=V("nCWL")+V("nBL")+V("nWTRS")},
          {.level="channel", .preceding={"ACT"}, .following={"ACT"}, .latency=V("nRRDS")},
          {.level="channel", .preceding={"ACT"}, .following={"ACT"}, .latency=V("nFAW"), .window=4},
          {.level="channel", .preceding={"ACT"}, .following={"PREA"}, .latency=V("nRAS")},
          {.level="channel", .preceding={"RD","RDA"}, .following={"PREA"}, .latency=std::max(V("nRTPL"),V("nBL"))},
          {.level="channel", .preceding={"WR","WRA"}, .following={"PREA"}, .latency=V("nCWL")+V("nBL")+V("nWR")},
          {.level="channel", .preceding={"PREA"}, .following={"ACT","REFab"}, .latency=V("nRP")},
          {.level="channel", .preceding={"REFab"}, .following={"ACT","RD","WR","RDA","WRA","PRE","PREA","REFab"}, .latency=V("nRFC")}
        });
        #undef V
      }
'''


def patch(name,text,change):
    if name=='3D_DRAM.cpp':
        text=change(text,'      // Populate the timing constraints\n',SHARED_TIMINGS+'\n      // Populate the timing constraints\n')
        text=change(text,'      // Sanity check: is the calculated channel density the same as the provided one?',
                    '      if(m_config["org"]["shared_bus_validation"] && m_config["org"]["shared_bus_validation"].as<bool>()) m_data_payload_bytes=256;\n      // Sanity check: is the calculated channel density the same as the provided one?')
    if name=='refresh.cpp':
        text=change(text,'      if (m_dram->m_direct_bank_access && m_num_ranks < 0) m_num_ranks = 1;',
                    '      // Both explicit 3D validation profiles have one pseudo-rank, no rank level.\n      if (m_num_ranks < 0) m_num_ranks = 1;')
    return text
