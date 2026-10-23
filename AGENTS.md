# Research contract

- This repository owns DRAM host-simulator acceleration research. Its root is
  `/Users/haoning/project/dram-fast-forward`, separate from LeanWafer.
- Preserve frozen physical configuration, FR-FCFS decisions, refresh, addresses,
  command cycles, admission/backpressure, callback cycles and recovery state.
- Report host CPU/wall speed separately from simulated chip performance.
- Keep rule coverage separate from proved/executed safe batching coverage.
- Historical measurements in `results/20261023` are immutable archived evidence;
  new experiments receive new directories and manifests.
- Do not create Python environments, modify shared PyTorchSim/LeanWafer, touch
  RTL, or stop/reprioritize existing server experiments.
- Remote new work belongs under `/Orion/jian/jhn/dram-fast-forward`.
- Frozen build dependencies, raw traces, binaries and logs are ignored artifacts;
  keep hashes and restoration instructions, not large generated files, in Git.
- Avoid new algorithms or changed physical behavior during repository migration.
  Check relocation with real differential execution before claiming equivalence.
