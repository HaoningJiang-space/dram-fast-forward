# Research contract

- 2026-10-23: Repository is explicitly public at the user's request. Active work
  is on `research/parametric-producers`; incremental/hybrid remain baselines.
- Current decision experiment is bounded multi-producer schedule compilation.
  Do not conflate finite unrolling with an arbitrary-length induction theorem.
  Treat region explosion and total cost as rejection criteria; reference command
  traces are validation outputs only. Whole-process CPU includes entry dispatch.
- Compile structured request/resource semantics, never oracle command order.
  Distinguish automatic instantiation of a supported proof rule from general
  controller synthesis. Include stride/RLE and non-polyhedral resource controls.
- Account for extraction, proof, code generation and C++ compilation costs;
  report a break-even count only when measured per-run savings are positive.
- Current study must include shared command/data bus contention, read/write
  turnaround, activation windows and refresh, not only independent-bank speedups.
- Keep fixed-order oracle graph diagnostics separate from online certification.
  Actual issue/completion timestamps must never be used as release constraints.
- After experiments freeze, organize native C++, shared Python IO/workloads,
  drivers and analysis, and verify rebuilding/relocation does not change results.

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
