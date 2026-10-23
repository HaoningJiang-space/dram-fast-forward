# Exact DRAM fast-forward PoC

This is an isolated **host simulator acceleration** experiment. It does not
change the modeled DRAM bandwidth, accelerator throughput, ASTRA graph, or
shared PyTorchSim installation. It does not replace the production native
backend. Results and the decision about further work are in
[PoC results](POC_20261023.md).

## Four modes, one frozen physical implementation

`build.py` copies the existing direct-bank DRAM implementation, Generic memory
system/controller, FR-FCFS scheduler and AllBank refresh. It links their existing
support objects. It records source, generated source, compiler dependency and
binary hashes. Exact source substitutions fail on unsupported source drift.
Text copies normalize line endings; original byte identities are recorded too.
The original tick/scheduling implementation remains available in the binary.

* `reference`: ordinary cycle advancement and original scheduling decisions.
* `event`: skip cycles before the earliest possible command, response, arrival,
  refresh or read/write-policy transition. Ready requests still use FR-FCFS.
* `incremental`: cache only prerequisite-command decoding, invalidated by
  enqueue, priority injection and commands with state actions. **Time-dependent
  readiness and FR-FCFS comparison are still evaluated.** This is a minimal
  incremental prototype, not a fully incremental priority scheduler.
* `symbolic`: strictly guarded, affine same-row READ batches; ordinary exact
  ticks otherwise. It is not combined with event or incremental mode.

The frozen configuration has eight independent direct-bank channels per memory
instance, 1 KiB per row, 256 B transactions, four distinct transactions per row,
READ spacing 8 DRAM cycles, read latency 23 cycles and refresh interval 3900
cycles. This scope has **no shared cross-bank data bus**. C tests independent
bank execution and each bank's timing; it cannot validate an absent shared bus.

## What a READ batch proves

Let `t0` be the current clock and `R_RD` the maximum current RD-ready clock along
the addressed hierarchy. Let `d` be the maximum applicable RD→RD constraint.
For a legal prefix of `n` requests:

```
first = max(t0 + 1, R_RD)
issue[i] = first + i*d
depart[i] = issue[i] + read_latency
last = first + (n-1)*d
ready_after[j] = max(ready_before[j], last + timing(RD,j))
```

The guard checks an already open row, fixed address stride (including zero),
monotone arrival/FCFS order, no queued writes/active/priority work, settled idle
controller policies, and only one busy bank in one busy memory instance. RD has
no state action. Timing histories must have window one, no sibling constraints
and no blocked offset. PRE cannot issue in a gap between these READs. A pending
competing command cannot become ready before the first READ.

The batch ends **strictly before** the next external arrival, refresh or requested
inspection checkpoint. Closed-loop mode also stops before the earliest existing
or newly generated callback. Unsupported cases retain the original path.
The final history/timing update is aggregated once, but every command observable,
request and completion callback is still handled individually. This deliberately
does not claim constant work for externally observable callbacks.

The original controller serves at most one pending read callback per tick.
The batch preserves that behavior, including overdue responses. Its observable
departure field is distinguished from the actual callback cycle. The frozen
buffer accepts 65 entries because its enqueue condition is `size <= max_size`
with default 64; the PoC preserves that behavior rather than repairing it.

This is a sufficient guard for the frozen model, not a theorem covering every
Ramulator configuration, plug-in, scheduler, timing window or arbitrary callback.
Callbacks in the synthetic closed-loop driver may enqueue new work; arbitrary
callbacks that introspect all intermediate device fields are outside this ABI.

## Validation and timing

`run.py` first executes symbolic audit mode to obtain its actual exit cycles.
Reference, event and incremental modes must then match:

1. Raw 96-byte records for every command, admission/rejection and actual callback.
2. Literal full serialized states at **every symbolic exit**, not just hashes.
3. Final device/controller/queue/refresh state after a paid mixed recovery suffix
   for synthetic cases. The actual trace instead drains without an artificial
   suffix.

State snapshots include clocks, request counters, write mode, all queue entries,
row-hit/miss/conflict counters, refresh deadlines and all DRAM node row states,
timing-ready arrays and command histories. The full stream is compared byte for
byte; hashes are only evidence indexes. After comparison one raw stream and the
state snapshots are retained losslessly compressed.

`--validation-reference` can reuse an already compared literal reference archive
if the workload and fast exit cycles match exactly. It does **not** reuse timing
measurements. All four modes are benchmarked again in fresh processes, three
times, in alternating order. Logging/full snapshots are off in timed passes.
Results distinguish simulation-loop CPU, whole-process CPU and wall time.

## Inputs and scope

`run.py` generates A same-row repeated reads, B alternating rows, C interleaved
banks, and D mixed/bursty reads/writes. B/C/D disable symbolic batching, so their
symbolic results measure fallback cost. Additional A tests cover four-column
piecewise affine reads, an interrupting write, callback-created followups and
queue backpressure. `fuzz.py` adds 20 seeded arrival/refresh/callback stress cases.

A uses zero stride as its longest legal same-row stream: this hardware row holds
only four distinct transactions. `A_affine4` separately tests positive stride
within the four columns. A is deliberately a best case, not a realistic model of
an indefinitely long unique accelerator stream.

E is captured from a completed real-width native FFN: three Up/Gate calls,
M32/N1792/K8192, paid core Split-K4. `build_capture.py` instruments a private
native copy; `capture.py` verifies its stage replies, events, lifetimes and results
against the completed source run. `check_native_replay.py` additionally checks
the complete accepted stream replay against the native capture per independent
device, preserving all command/admission/callback cycles. Only independent
devices' host record order is canonicalized. E remains **open loop**. Its complete
224,896-request window is primary; E at one million requests is explicitly a
periodic extension of that measured window, not a new longer native execution.

`analyze_trace.py` describes address regularity. `analyze_commands.py` describes
necessary-condition command windows. Neither statistic is a safe batching
certificate; executed guarded coverage is reported separately.
`summarize.py` collects the completed frozen experiment groups into a small
machine-readable report without scanning their raw traces.

## Reproduction

Use the existing server environment; no new environment or shared source edits.
Set `PYTHONPATH=$PWD/src` from this standalone repository root first:

```sh
PY=/home/jian/miniconda3/envs/pytorchsim_env/bin/python
# SRC contains the frozen native build manifest and original 3D_DRAM.cpp.
# RAM contains copies of the four frozen Ramulator translation units.
$PY -m dram_fast_forward.build --source "$SRC" --ramulator "$RAM" --output "$BUILD"
$PY -m dram_fast_forward.run --binary "$BUILD/dram_poc" --dram-yaml "$YAML" \
  --output "$OUT" --patterns A B C D E --counts 10000 100000 1000000 \
  --real-trace "$CAPTURE/accepted_requests.json" --repeats 3
$PY -m dram_fast_forward.run --binary "$BUILD/dram_poc" --dram-yaml "$YAML" \
  --output "$EDGES" --patterns A_affine4 A_interrupt A_closed A_pressure \
  --counts 10000 --repeats 3
$PY -m dram_fast_forward.run --binary "$BUILD/dram_poc" --dram-yaml "$YAML" \
  --output "$REAL" --patterns E --counts 224896 \
  --real-trace "$CAPTURE/accepted_requests.json" --repeats 3
$PY -m dram_fast_forward.fuzz --binary "$BUILD/dram_poc" --dram-yaml "$YAML" \
  --output "$FUZZ" --seeds 20
```

The report's remote evidence root contains the frozen build inputs, compiled
binary, exact configuration, receipts, logs and compressed raw comparisons.
Paths are explicit artifacts, not production imports or a new installed runtime.

## Next decision

Evaluate actual guarded coverage and whole-process time before implementing
multi-bank symbolic transitions. High same-row locality alone is insufficient.
An event-driven clock, incremental prerequisite decoding and symbolic batches
solve different costs; their measured speedups must not be multiplied.
