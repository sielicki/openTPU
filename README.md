# openTPU

**An open-source AI accelerator, developed by AI.**

openTPU brings the lessons of [auto-arch-tournament](https://github.com/FeSens/auto-arch-tournament)
to AI accelerators. It asks two questions: how far can AI agents go at hardware design, and can
they build the chip that runs their own inference?

![otpu-chat on LFM2.5-230M with otpu-smi watching the card](docs/img/card-chat-smi.gif)

*`otpu-chat` running LFM2.5-230M on the FPGA card (left), with `otpu-smi` showing the card's
utilization and DRAM bandwidth (right).*

## A place to learn

openTPU is also a learning project. The whole accelerator lives in one small monorepo that you
can read end to end: the hardware design (SystemVerilog), the instruction set, a bit-exact
simulator, a kernel language and its compiler, and the host software that drives a real PCIe
card. If you want to understand how an AI accelerator works, from a matmul in Python down to
the wires, this is a good place to start.

## Native Sparkle port (in progress)

The native Lean hardware sources are in [`OpenTPU/`](OpenTPU), using the local
`../sparkle` checkout and its Lean 4.32.1 toolchain. They construct
Sparkle circuits directly with its typed netlist builder. Production circuits currently
do not use SystemVerilog import; an importer-assisted migration experiment is described below. The existing Python ISA, compiler, and host interfaces
continue to serve as the software interface and reference.

Current production status: native implementations exist for all eleven major
implementation children, and their evidence is bound to the Gen1, Gen2 and CLI
FPGA assemblies. The completed module-definition applicability join accounts for
95/95 Gen1 definitions and 99/99 Gen2/CLI definitions, including the four formerly
uncovered wrappers/shells. Elaborated specialization bindings now cover Gen1,
Gen2 and the CLI bundle. Runtime qualification includes all 119 cases in the
broader original Top inventory (116 native, three external-reference cases),
all 40 small-model cases, and the Board and native-memory suites detailed below.
Real-checkpoint workloads, physical FPGA qualification, and the explicitly
documented formal startup/address assumptions remain open.
The detailed evidence and its assumptions are recorded below.

Run every build, simulator and proof through `python3 tools/sparkle_bounded.py --
COMMAND`, with compiler parallelism one. The gate serializes heavy work and
enforces a 3 GiB process-tree limit with zero swap; see `AGENTS.md`.

The Sparkle frontend feasibility probe is reproducible with
`python3 tools/probe_sparkle_importer.py` (Lean, Yosys and `read_slang` required).
It leaves the sibling Sparkle checkout untouched. Direct ACT RAM, behavioral DRAM
and MXU imports currently hit parser limitations. A three-stage skew helper can
be elaborated with Slang, normalized to ANSI ports and simple identifiers, then
imported into Sparkle and emitted back to RTL. The probe checks that round trip
against the original helper with corresponding pipeline states. This experiment
does not yet generate editable Lean circuit source or replace production modules.

Implemented so far:

- `AsyncFifo.lean`: native dual-clock FIFO, including out-of-order slot commits
  and optional registered write readiness. Five configurations pass complete
  retained-state digital equivalence for independent write/read edge choices;
  output corruption and an intentionally wrong register clock are rejected.
  Evidence: `build/sparkle/formal_async_fifo/`. These proofs do not model analog
  metastability. All five configurations also retain the original `ASYNC_REG`,
  distributed RAM, and write-address fanout hints, with unchanged functional
  tokens (`build/sparkle/async_fifo_physical/`). Generate a core with
  `async-fifo-core W DEPTH OOO RWR OUTPUT.sv`. Board integration is present;
  CDC placement/timing qualification remains pending.
  An independent-clock/reset simulation comparison also passes all five
  configurations (100,000 steps total), with all four edge combinations and
  traffic coverage enforced: `make test-sparkle-async-fifo`, evidence under
  `build/sparkle/check_async_fifo/`.
- `DmaSplit.lean`: native ingress register slice, ordered AXI channel splitter,
  and two egress register slices. Full-state proofs pass four configurations
  covering bypass/registered modes and 32/128/512-bit data; both corruption checks
  are rejected. Evidence: `build/sparkle/formal_dma_split/`. The generator accepts
  `dma-split-core REG IDW DW OUTPUT.sv` and `axi-split-core IDW DW OD OUTPUT.sv`.
  `dma-split REG IDW DW OUTPUT.sv` adds the original module ABI. Twelve existing
  board memory-channel scenarios pass with this native replacement: six scenarios
  each in bypass and registered modes, retaining internal FIFO monitors and
  traffic counters. Evidence: `build/sparkle/check_dma_split/summary.json`.
  Production board hierarchy selection and wrapper applicability are checked
  for Gen1, Gen2 and the CLI bundle (`build/sparkle/remaining-abi-v3/summary.json`).
  Both board split generators retain the three ordering FIFOs' distributed RAM
  hints. Seven configurations pass emitted-logic comparison against authenticated
  proofs and Yosys attribute inspection (`build/sparkle/board_split_physical/`).
- `AxiSplit.lean`: native two-channel address splitter, including independent
  write-data, write-response, and read-response ordering FIFOs. Full-state
  equivalence passes three configurations (32/128/512-bit data, outstanding
  depths 2/16/8), and two output mutations are rejected. Evidence is under
  `build/sparkle/formal_axi_split/`. The splitter is integrated in the native
  board hierarchy.
- `Vpu.lean` assembles the native control and datapath behind the full VPU port
  boundary. `VpuABI.lean` adapts the original typed/unpacked interface for
  qualification. `OTPU_SPARKLE=vpu-test` selects it in the stream bench and
  system simulation harness (`make test-sparkle-vpu`);
  `all` now selects this complete native VPU too; all 28 combined-system
  regression cases pass in 559.44 seconds (`all-native-with-vpu-summary.json`). All ten stream/VOP integration cases pass
  (LANES=8, CL=2, both write-buffer modes). The adapter restores address-mode,
  decoder alignment, A/Q capture, duplicate root, and write-buffer consistency
  diagnostics; all ten cases pass with these checks enabled. Evidence is recorded
  in `build/sparkle/vpu-full-integration-summary.json`.
  Four system tests also pass (4/16-lane application workloads and single/two-slice
  fuzz seed 0), recorded in `vpu-system-integration-summary.json`. Six assembled
  structural configurations pass in `build/sparkle/check_vpu/summary.json`.
  After matching synthesized row-buffer address truncation and restoring local
  delay/RAM hints, a fresh combined run passes all 14 tests in 32.16 seconds;
  `build/sparkle/vpu-stable-integration-summary.json` records the final result.
  `tools/check_sparkle_vpu.py` checks port widths, hierarchy, drivers, and absence
  of combinational loops. `build/sparkle/vpu_qualification.json` authenticates
  all six current emissions against the component proof closure and independently
  checks assembly connections, rejecting twelve wiring mutations. This is a
  composition audit with explicit decoder-invariant and undefined-address scope,
  not an unrestricted monolithic theorem. Full FPGA physical qualification remains
  outstanding.
  The decoder invariant now has an explicit reset-induction proof: the actual
  `m0`/`m0d` register cone satisfies `m0d = fdec(m0.func)` after reset and on
  every subsequent edge, implying a one-hot-or-zero function mask. Five
  configurations pass, including production `(LANES, CL, streams) = (8, 2, true)`
  with all 143 cone state bits retained. Unrestricted next-state correspondence
  also passes; 12 reset/update/stream faults and 20 executable extraction guard
  mutations are rejected. Evidence is in
  `build/sparkle/formal_vpu_decoder_reachability/driver-guards5/summary.json`.
  This proves decoder reachability, not whole-VPU startup equivalence.
  Both qualification audits consume that receipt, comparing exact datapath
  module bodies, directive context, configurations and reference hashes. Fresh
  passing results are `build/sparkle/vpu_datapath_qualification_decoder_reachability.json`
  and `build/sparkle/vpu_qualification_decoder_reachability.json` (all six
  whole-VPU configurations); earlier receipts remain available. The receipt
  consumer and extraction checks pass 33 Python guards.
  An additive startup audit now establishes the same invariant from the actual
  declared production state: `m0 = 0`, `m0d = 0x101 = fdec(0)`, with all 143 bits
  checked and no sampled-reset premise. It authenticates the existing unrestricted
  transition proofs and checks a new initial-state SAT obligation; both actual
  initializer mutations yield counterexamples. Evidence is
  `build/sparkle/vpu-decoder-initial-second/summary.json` (1.57 seconds, 77 MiB,
  no limit events); 13 guards pass. The first attempt failed because the decoder
  ROMs needed mapping before SAT and is preserved. Production binding now passes
  for the exact reached datapath in Gen1, Gen2 and CLI, preserving full module
  tokens, attributes, incoming directives and the inherited induction evidence.
  Evidence is `build/sparkle/vpu-decoder-initial-consumer-binding-first/qualification.json`;
  32 guards pass. Binding took 100.81 seconds, reached the 3 GiB cap with 55,725
  reclaim events, and recorded zero OOMs/kills. Initialization of the rest of
  the VPU and whole-board composition remain separate obligations.
- `NativeSys.lean` connects the native DMA splitter, two memory channels and
  the board through their structural ABI wrappers. Three parameter configurations
  pass all boundary wiring and parameter checks, and three clock/data mutations
  are rejected. Its emitted shell requires the Board/Slice bundle separately;
  these composition proofs do not establish complete system behavioral closure.
  `NativeSysCompleteABI.lean` additionally emits the complete native Board/Slice
  bundle with that shell. The four-lane configuration retains full default
  memory sizes and passes 79-module uniqueness, complete ABI lint, exact shell
  retention, and all system-boundary pin/parameter checks. Run
  `make check-sparkle-native-sys-complete`; results and behavioral coverage limits
  are in `build/sparkle/check_native_sys_complete/summary.json`.
- `Board.lean` assembles native board signals, control, trace, collective and
  native DRAM around an explicit slice boundary. Three configurations pass
  composition equivalence for all 92 board state bits, every child input and
  external output, with independently checked parameter and array layout.
  Three wiring mutations are rejected. This is a wiring/state proof with
  arbitrary child outputs, not a claim of complete behavioral closure for
  unqualified child configurations. The `board-assembly` generator preserves
  these exact qualified tokens; `board-assembly-test` selects the assembly in
  simulation while retaining the original slice and memory channels. All 15
  observability integration tests pass with unchanged captured source hashes;
  evidence is in `build/sparkle/board-assembly-integration-summary.json`.
  The combined `board-channel-test` mode also replaces the memory channels:
  all 15 observability tests pass with unchanged source hashes, recorded in
  `build/sparkle/board-channel-clean.summary.json`. This mode still uses the
  original slice. `BoardNativeABI.lean` now emits a complete native board/Slice
  bundle. Its 53-module bundle passes typed ABI lint, parameter/connection checks,
  a reset-connection mutation, and all 92 local board-state bits at the exact small
  D128/LANES4 configuration. Run `make check-sparkle-board-native`; evidence is in
  `build/sparkle/check_board_native_abi/summary.json`. Complete native board runtime
  qualification now includes the audited control, observability, functional and
  model suites described below; all eleven production implementation children
  have matching proof-applicability records. Broader runtime coverage remains open.
  The `board-native` generator uses the same arguments as `board-assembly` and
  emits all 53 qualified module definitions unchanged. `OTPU_SPARKLE=board-native-test`
  selects native board/Slice and memory channels with explicit external memory
  models; `make test-sparkle-board-native` runs its observability suite.
  Use `OTPU_VERILATOR_JOBS=1` inside the bounded runner. Simulations and formal
  solvers share the same gate and run one heavy job at a time.
- `Top.lean` and `TopABI.lean` assemble the native Slice, collective, and DRAM
  or native memory adapter. Four composition configurations cover AXI0/1/2 and
  one to three slices; reset, flush, grant and SID mutations are rejected.
  Focused two-slice execution passes both direct initialization and DRAM boot,
  including load, barrier, gather, store, halt, argument registers and trace tags.
  Evidence is in `build/sparkle/{formal_top_composition,test_top_abi}/`.
  `OTPU_SPARKLE=top-test` selects this complete native hardware in the existing
  simulation harness. Six ISA comparison tests pass with unchanged source inputs:
  one/two slices, four/sixteen lanes, and direct/DRAM-boot argument loading.
  Evidence is in `build/sparkle/native-top-integration.summary.json`; broader
  ISA regressions remain to be run. AXI1/2 simulation
  memory models remain explicit external dependencies.
- `Slice.lean` assembles all native units and local control. Five configurations
  cover LANES4/8/16, ULANES4/8, D32/64/128, one/two slices, all three MXU variants,
  streaming enabled/disabled, and both arbiter paths. Every local state bit,
  external output and input to the seven functional units is checked. ABI lint,
  parameter projection checks and a local error-output mutation pass. Evidence
  is in `build/sparkle/slice_composition_qualification.json`; this composition
  proof relies on separate child proofs for complete behavioral closure.
  The D128 cases include the exact small native-board bundle and its board-mask
  arbiter variant. `python3 tools/prove_sparkle_slice.py --matrix` regenerates the
  entire proof, ABI, parameter and mutation matrix without development artifacts.
- `SliceArbiter.lean` passes unrestricted combinational equivalence at six
  LANES/RPB/WPB configurations, including the 16-lane board mask path. Both
  general-count and mask-path output mutations are rejected. Checked intermediate
  mask/admission points and Boolean mapping make the wide proof tractable;
  every intermediate equivalence obligation must pass. Evidence is under
  `build/sparkle/formal_slice_arbiter/`.
- `SlicePorts.lean` implements TMEM request assembly and the DRAM port mux.
  Exact original-snippet equivalence passes five DRAM depths and seven
  LANES/ULANES combinations, including partial lane populations. Both families
  reject mutations; channel parity is verified to be computed before selection.
- `SlicePerf.lean` implements activity/window/halt counters and the packed perf
  output. Five configurations pass complete state equivalence (690–700 bits,
  no pruning); runtime window values are unconstrained. `SlicePerfABI.lean`
  retains the original bucket guards and trace diagnostics, with token checks,
  a rejected diagnostic mutation and Verilator lint.
- `SliceRld.lean` implements the local RLD pipeline and collective request
  retention. An unrestricted transition proof pairs all 216 retained state bits
  against the original slice logic, including float-to-integer conversion,
  RAW/MUL flags, partial products, reset holds and overlapping start/grant events.
  A result-valid mutation is rejected. This module is included in native Slice.
- `SliceLoader.lean` implements HALT CHAIN, accumulated instruction counts,
  program loading, loader arbitration signals, and the per-unit reset tree.
  All 232 retained state bits pass unrestricted transition equivalence at
  D=32/64/96/128/256, including the non-power-of-two instruction-row division.
  A request-output mutation is rejected; all four unit-reset fanout constraints
  are checked. Evidence is under `build/sparkle/formal_slice_loader/`.
  The loader is included in the native Slice assembly.
- `BoardSignals.lean` implements the board-local calibration and I2C synchronizers,
  stable temperature sampling, core/collective reset stages, heartbeat and LEDs.
  All 92 state bits pass arbitrary-state transition equivalence; an LED mutation
  is rejected. The six `ASYNC_REG` attributes and reset fanout limit of 256 are
  checked in the synthesized netlist. Evidence is in
  `build/sparkle/formal_board_signals/`. The component is integrated in native
  Board; physical clock-crossing/timing qualification remains pending.
- `Control.lean` implements the host AXI-Lite register map, loader/run controls,
  trace controls, argument registers, per-run counters, free-running counters,
  and atomic snapshots. Two configurations pass full retained-state transition
  equivalence (2,421 bits each), with arbitrary inputs and a rejected read-ready
  mutation. The proof explicitly packs the original unpacked argument interface
  by index. Evidence is under `build/sparkle/formal_control/`. ABI checks pass 188,055 cycles across three configurations, covering the full
  byte-address map, all write strobes, stalls, snapshots, resets, and trace-address
  increment/write collisions. `build/sparkle/check_control/` records the results.
  `OTPU_SPARKLE=board-test` selects native control, trace, and asynchronous FIFOs
  in the host board simulator; all 15 observability integration tests pass.
- `Trace.lean` implements the board trace recorder: event capture, bundle queue,
  ordered record unpacking, saturating counters, and the two-cycle ring read port.
  `TraceABI.lean` preserves the original typed interface and PC-width diagnostic.
  All retained-state transition proofs pass DEPTH/QD/WIN 4/2/16 and 16/4/8
  (6,802 and 10,129 bits), after conservatively removing structurally unobservable
  state; an output mutation is rejected. Differential ABI checks pass 60,000
  cycles across 4/2/16, 64/4/8, and the production 16384/32/16 configuration.
  Current emissions match the authenticated proof/test artifacts; structural
  checks pass and the queue/ring retain distributed/block RAM attributes.
  Evidence is under `build/sparkle/{formal_trace,check_trace,trace_physical}/`.
  Run `make test-sparkle-trace`. Native board selection is tested; placed timing
  remains pending.
- `BoardFifo.lean` and `AxiSlice.lean`: native board skid buffer, synchronous FIFO
  (both output modes) and five-channel AXI register slice (registered or wires).
  All-state proofs cover eight skid/FIFO configurations and four AXI configurations,
  including reset-cycle data writes, RAM contents and 512-bit channels; deliberate
  valid-output mutations fail. FIFO memory retains its distributed-RAM hint.
  Generator commands are `skid-core W OUTPUT.sv`, `sfifo-core W DEPTH RO OUTPUT.sv`
  and `axi-slice-core REG IDW DW OUTPUT.sv`. These cores are not yet selected by
  the board hierarchy. Evidence is under `build/sparkle/formal_board_fifo/` and
  `formal_axi_slice/`.

- `VpuDecode.lean` and `VpuIssue.lean`: native function decoding, issue addresses,
  lane enables, masks and composite stall control. Unrestricted combinational
  equivalence covers every decoder input and three issue configurations
  `(LANES,CL,HAS_SE)=(8,8,1),(4,2,0),(16,4,0)`; deliberate output mutations fail.
  `VpuCommand.lean` adds the two-entry command queue, issue eligibility and chunk
  geometry. Its proof checks all 483 retained state bits and outputs in the same
  three configurations, with unrestricted inputs and a rejected chunk-count mutation.
  The exact 8/2/true command stage also passes initialized trace refinement at
  `build/sparkle/vpu-command-initial-first/summary.json`: all 483 state bits and
  770 output/next-state bits, strong explicit-undefined totality/equality, and
  actual emitted output/reset/undefined-source fault counterexamples. The original
  full RTL and queue-writer/reset/setup fragments are checked before extraction;
  one legal original startup witness matches the native state without a reset
  assumption. Its `nfill` output is the extracted combinational setup value,
  not the original registered value on every cycle. The run verifies 290 inputs
  in 8.54 seconds, peaks at 1.56 GiB with no limit events, and passes five guard
  tests. Combined-control composition remains open; production binding is recorded below.
  `VpuSequence.lean` implements the main issue/reduction sequencer; transition
  proofs cover all 676/673/683 state bits in those configurations and reject a
  completion-output mutation. Exact 8/2/true sequence initialization also passes
  at `build/sparkle/vpu-sequence-initial-second/summary.json`: all 676 bits across
  44 independently checked compiled state fields and all 1,352 output/next-state
  coordinates per side, including registered `nfill`. Strong explicit-undefined
  definedness/equality and three actual emitted-source fault controls pass
  (294 inputs, 15.60 seconds, 1.35 GiB peak, no limit events; five guard tests).
  The first attempt remains incomplete because its undefined-output fault made
  one register dead; the corrected fault targets an internally used register,
  preserving the full state requirement. Queue/setup and datapath interfaces
  remain unrestricted proof inputs; combined-control composition remains separate.
  `VpuWriteBuffer.lean` covers direct and queued writes, including
  the stream mode's four-slot queue; all-state proofs pass five configurations
  (1,722/868/439/426/214 state bits) and reject a completion-output mutation.
  Exact native configuration `<8,true,true>` now also passes initialized
  refinement at `build/sparkle/vpu-write-buffer-initial-first/summary.json`:
  all 1,700 RAM plus 22 control bits and all 2,150 output/next-state coordinates
  per side, with arbitrary shared inputs and no added empty-queue/zero-RAM/reset
  assumptions. Strong definedness/equality and four actual emitted-source faults
  pass, including a reset-time RAM-write fault with a reset-high counterexample
  (314 inputs, 21.98 seconds, 446 MiB peak, no limit events; five guard tests).
  Combined-control composition remains separate; production binding is recorded below.
  `VpuWriteSelect.lean` preserves write arbitration for elementwise, maximum/index,
  sum and row-buffer flush results. Its unrestricted proofs cover 2/4/8/16 lanes,
  overlapping completions and a rejected lane-enable mutation. These components
  are now wired into the complete native VPU described above. `VpuStream.lean` adds stream grant
  arbitration, two-stage input alignment and the reduction-kind FIFO. Its transition
  proof covers all 1,350 state bits and outputs with unrestricted tail/tree inputs,
  including reset-time data capture, and rejects a grant-output mutation. The tail
  arithmetic and metadata-alignment delay remain separate composition boundaries.
  The stronger initialized stream refinement passes at
  `build/sparkle/vpu-stream-initial-third/summary.json`: all 1,350 state bits and
  2,170 output/next-state coordinates per side, with arbitrary tail/tree inputs
  and no reset assumption. Strong explicit-undefined definedness/equality and
  four actual emitted-source faults pass, including a reset-time capture fault
  with a reset-high counterexample. The run takes 7.23 seconds, peaks at 423 MiB,
  and records no limit events; ten guard tests pass. Earlier attempts remain
  incomplete at unsupported native mux-cell audits; the local checker now
  validates `$demux`, `$bwmux` and `$bmux` without rewriting those cells and pins
  their actual solver semantics. Combined-control composition remains open.
  `VpuControl.lean` connects these components with checked signal widths and unique
  drivers. `opentpu-gen vpu-control LANES CL HAS_SE WBUF OUTPUT.sv` emits this
  combined control circuit with the original fanout hints. Its structural checker
  validates five configurations, explicit datapath boundary ports, complete hierarchy,
  driver consistency, absence of combinational loops, and functional-token preservation
  by the physical emitter. That structural check alone is not full-VPU behavioral
  equivalence; the separate composition and leaf qualifications supply the
  behavioral evidence under their recorded assumptions.
  All four local initialized contracts now have production applicability at
  `build/sparkle/vpu-control-initial-binding-second/summary.json`: command 483,
  sequence 676, write buffer 1,722 and stream 1,350 bits, totaling 4,231 bits per
  assembly across Gen1, Gen2 and the CLI bundle. The binder checks full module
  bodies and directive contexts, every ordered child pin, reached specialization
  and containing definition. Five exact production fanout hints also pass fresh
  complete pre-clean graph/state/initialization comparisons. It authenticates
  17,151 inputs in 368.13 seconds, peaks at 3 GiB with 84,992 reclaims and no
  OOMs/kills; eight guard tests pass. The first attempt remains incomplete at
  a temporary-source attribute-delimiter parse error. The corrected renderer
  verifies the entire token sequence before extraction. These are four bound
  local contracts, not a combined 4,231-bit inductive proof: full-original VPU
  boundary correspondence, control feedback, and control/datapath composition
  remain separate obligations.
  Fresh exact-config issue (8/2/true) and write-selection (eight lanes)
  combinational proofs also pass at
  `build/sparkle/vpu-control-comb-third/summary.json`: all 555 and 424 output
  bits respectively are defined and equal for arbitrary defined inputs, with
  no state or memory. Actual wrong-value and undefined-output mutations are
  rejected for both circuits. Both imports defer process lowering to explicit
  `proc -noopt -norom`, preserving the original case/default logic as muxes;
  the first two incomplete attempts preserve the frontend-inferred ROM diagnosis.
  Seven guard tests pass. The proof takes 74.88 seconds, peaks at 1.84 GiB and
  records no memory-limit or OOM events. The local lane adapters remain explicit;
  full-original lane ordering, production binding and joint control composition
  are not established by this local result.
  The command/sequence joint stage now passes at
  `build/sparkle/vpu-joint-control-initial-fifth/summary.json`: all 1,159 state
  bits and 2,122 output/next-state observations per side, using the untouched
  original sequencing process and the actual reached native child connections.
  A coherent original initial witness and arbitrary defined external boundaries
  require no sampled reset, legal traffic or equality between the command's
  head-fill observer and the sequence's retained fill count. Acceptance-path,
  geometry-connection and retained-fill mutations all produce counterexamples
  after passing definedness. Fourteen guards pass; 17,250 inputs are authenticated.
  Qualification takes 253.96 seconds, peaks at 3 GiB with 57,235 reclaims and no
  OOMs/kills. Earlier provenance, declaration-order and mutation-formatting
  attempts remain incomplete. The whole 4,231-bit control partition and complete
  VPU composition remain unproved.
  Original-root inventory work has preserved the full 8/2/WBUF1/HAS_SE1
  extraction at `build/sparkle/vpu-original-control-inventory-second/summary.json`,
  retaining original child declarations as explicit black boxes and the typed
  AST. Resumes reuse that extraction. Strict local array/scope handling now
  handles array types and reached instance scopes; unresolved packed layouts
  remain explicit. The inventory completes at
  `build/sparkle/vpu-original-control-inventory-seventh/summary.json`, identifying
  all 4,231 candidate control-storage bits with no unresolved storage fields.
  All 23 child occurrences and declared parameter values are checked against
  typed AST evidence; specialized integral port widths are checked per instance,
  with representative black-box declaration differences preserved. VTree's
  nondeclared `j/k/q` exports and nonintegral port layouts remain explicitly
  unresolved and cannot serve as proof premises. Twenty-one guards pass;
  17,268 inputs are authenticated in 149.79 seconds, with a 3 GiB peak,
  65,621 reclaims and no OOMs or kills. Earlier incomplete attempts are retained.
  This complete inventory does not establish the full control partition or
  combined behavioral equivalence.
  The subsequent command/sequence storage-and-boundary inventory passes at
  `build/sparkle/vpu-joint-partition-first/summary.json`: all 1,159 selected bits
  are accounted for as 679 register bits and 480 memory bits. It preserves
  9,811 owners and records 2,455 outward uses, 437 boundary bits and 1,431
  dependency cells. Ten guards pass; the run takes 142.00 seconds, peaks at
  3 GiB, and records 71,099 reclaims with no OOMs or kills. Exact public-output
  binding, physical layout, memory mapping and transition equivalence remain
  pending; this is a structural inventory only.
  Public-coordinate checking passes at
  `build/sparkle/vpu-joint-observation-first/summary.json`: 930 direct output
  coordinates are recorded, including 678 selected-state coordinates, and
  actual scalar begin-expression owners are identified. Nine guards pass;
  the run takes 135.80 seconds, peaks at 3 GiB, and records 62,992 reclaims
  with no OOMs or kills. The 32 geometry bits, begin-guard use sites, extra
  crossings, physical layout and behavioral correspondence remain unproved.
  A focused semantic bridge passes at
  `build/sparkle/vpu-joint-geometry-first/summary.json`: the actual original
  and archived joint-model `nch`/`nfill` next-state vectors (32 bits per side)
  are defined and equal for all 275 shared, defined underlying boundary/state
  inputs. All actual buffers are retained; 550 boundary-alias bits are also
  proved defined and equal to those inputs, for 614 total observations.
  Inverted-D, forced-hold and undefined-D faults are detected. Eleven guards
  pass; the run takes 149.13 seconds, peaks at 3 GiB, and records 81,500 reclaims
  with no OOMs or kills. No reset or traffic restriction is assumed. Boundary
  producers, packed layout, initialization and whole-control composition remain
  separate obligations; this does not equate guarded temporaries with the
  unconditional geometry observers.
  The subsequent precise dependency probe at
  `build/sparkle/vpu-joint-physical-bits-first.log` closes both dependency
  frontiers for all 679 selected register next-state bits and their actual
  boundary aliases, without new cuts. Five guards pass; the probe takes
  1.19 seconds and peaks at 71 MiB without limit events. This is dependency
  evidence only. The subsequent complete conditional proof passes at
  `build/sparkle/vpu-joint-physical-proof-first/summary.json`: all 679 actual
  register next-state pairs and 1,256 boundary-alias pairs are defined and equal
  across 121 partitions. Actual inverted-update, forced-hold and undefined-D
  faults are detected. Ten slicing/model guards and eight integration guards
  pass. The run takes 310.68 seconds, peaks at 3 GiB, and records 83,156 reclaims
  with no OOMs or kills. This retains the explicit shared, defined boundary;
  480 queue-memory bits, actual boundary producers, packed layouts, coherent
  initialization, outward crossings and whole-control trace composition remain
  separate obligations.
  The queue-memory bridge subsequently passes at
  `build/sparkle/vpu-joint-cq-proof-first/summary.json`: all 480 memory next-state
  bits and the 240-bit head read match the actual joint model. The run proves
  482 control-knownness observations, checks the mapped memory against a
  separate one-writer memory law, and verifies state-only head dependencies.
  Disabled-write unknown values remain intact. Actual write-address,
  read-address and reset-write faults are detected, including a reset-active
  witness for the last fault. Six control, six mapping and six driver guards
  pass. The run takes 308.48 seconds, peaks at 3 GiB, and records 90,530 reclaims
  with no OOMs or kills. Composition with the 679-register theorem, coherent
  initialization, external layouts/providers and outward crossings remain
  separate obligations.
  The initialized composition audit at
  `build/sparkle/vpu-joint-initialized-composition-first/summary.json` then
  requalifies 523 positive queries and joins all 679 register bits and 480
  memory bits into a conditional initialized 1,159-state relation. The actual
  state-only head read and preserved buffer paths discharge the symbolic head
  input; a coherent original startup witness shares arbitrary queue words.
  Six guards pass. The audit takes 174.85 seconds, peaks at 3 GiB, and records
  74,144 reclaims with no OOMs or kills. External/state and constant/input
  equalities remain explicit per-cycle environment conditions. Packed layout,
  actual external producers, all outward observations and whole 4,231-state
  control composition remain unproved by this result.
  The actual issue bridge at
  `build/sparkle/vpu-issue-bridge-second/summary.json` subsequently proves all
  555 issue outputs and 211 raw-input alias obligations in 48 partitions,
  including all 528 public issue-output crossings. It removes exactly 27
  normalized internal conditions from the selected-state composition and
  checks the reached native provider in all three production assemblies.
  Nine guards pass; actual flipped and undefined outputs are rejected.
  Certification takes 210.91 seconds, peaks at 3 GiB, and records 68,821
  reclaims with no OOMs or kills. The first attempt remains incomplete after
  a diagnostic-only import failed the source-ownership check; the second
  separates proof pins from diagnostic imports without relaxing authentication.
  The remaining per-cycle interface has 243 top-level bits, two internal
  control bits and 66 datapath bits, including the actual `c_hold` input.
  That input's producer equality, the other 3,072 control-state bits, remaining
  crossings and whole-control composition are still separate obligations.
  The next diagnostic at `build/sparkle/vpu-remaining-state-diagnostic-first.log`
  qualifies the remaining 3,072 state coordinates: 1,350 stream register bits,
  22 write-buffer register bits and 1,700 write-buffer memory bits, retaining
  complete memory accesses and local reference/native coordinates. Its disjoint
  union with the earlier partition covers all 4,231 original bits (2,051
  physical register bits and 2,180 memory bits). The `en`, `ss_rq` and actual
  composite `hold` providers are recorded without claiming their equality.
  Six guards pass; the diagnostic takes 1.37 seconds and peaks at 89.5 MiB,
  with no limit or OOM events. Transition equality, layout and initialized
  correspondence remain separate proofs.
  The actual original-to-native stream bridge at
  `build/sparkle/vpu-stream-root-bridge-first/summary.json` then proves all
  1,350 next-state bits and 820 exported bits, plus boundary aliases: 4,348
  comparisons in 272 partitions. Both actual cones close without extra cut
  inputs; original buffers and selector-bearing cells are retained. Seven
  guards pass, and actual next-state flip, hold and unknown faults are detected.
  The run takes 587.10 seconds, peaks at 3 GiB, and records 111,269 reclaims
  with no OOMs or kills. This remains conditional on the explicit shared
  boundary relation; the original initialization witness, external providers,
  write-buffer bridge and whole-control composition remain pending.
  The write-buffer bridge subsequently passes at
  `build/sparkle/vpu-write-root-bridge-first/summary.json`: all 1,722 next-state
  bits, 428 outputs and boundary aliases (4,304 comparisons in 269 partitions).
  It checks 856 memory-control definedness obligations and an independent
  1,700-bit four-word transition law with both 425-bit read ports. Disabled
  unknown controls, actual read identities and reset-time writes are retained;
  actual graph faults are rejected. Six guards pass. The run takes 692.96
  seconds, peaks at 3 GiB, and records 108,005 reclaims with no OOMs or kills.
  Together the local root bridges cover all 4,231 control next-state bits,
  but their cross-boundary conditions and whole-control trace still require
  composition. The simultaneous startup audit subsequently passes at
  `build/sparkle/vpu-full-initial-product-second/summary.json`: all 4,231 native
  coordinates are joined injectively to the original 2,051 register and 2,180
  memory coordinates, including exact stream bit ordering. For every defined
  native startup satisfying its actual initial predicates, a compatible original
  startup exists. The actual native artifact constrains all 4,231 coordinates;
  the original has no initial constraints. This does not assume original memories
  are zero or establish transition/layout correspondence. Twenty-two guards pass.
  The run takes 160.84 seconds, peaks at 3 GiB, and records 57,884 reclaims with
  no OOMs or kills. Complete internal-provider and outward-consumer connections,
  followed by trace composition, remain pending.
  The complete six-child connection inventory passes at
  `build/sparkle/vpu-control-provider-closure-second/summary.json`. It records
  3,167 child input coordinates: 250 exact original-endpoint candidates, 280
  internal to the existing joint theorem, 2,121 external parent-input occurrences,
  91 write-select input coordinates without an actual-root domain bridge, and
  425 missing provider observations (`busy` plus 424 write-select output bits).
  Endpoint candidates retain buffer obligations; this is not semantic discharge.
  A fresh inventory covers all 4,231 storage coordinates and their complete
  next-state/memory-access dependency closure: 2,159 dependency cells, 2,698
  frontier bits and 5,857 outward consumer occurrences. Separate public-output
  cones still need coverage. Eight guards pass; the run takes 14.46 seconds,
  peaks at 207 MiB, and records no limit or OOM events. The first attempt's
  tuple/list directive-serialization mismatch is preserved as incomplete;
  the correction preserves every directive token, order and line boundary.
  The missing `busy` provider is then proved at
  `build/sparkle/vpu-busy-root-bridge-first/summary.json`. Both actual cones
  close on nine related current-state bits, with no external input premise.
  Eleven observations cover raw `busy`, the exact normalized stream input and
  nine state aliases. Both native consumers remain recorded: the sequence edge
  is internal to the existing joint theorem, and the stream premise is newly
  discharged. Actual output inversion and undefined-output faults are detected.
  Four guards pass. The run takes 182.17 seconds, peaks at 3 GiB, and records
  76,780 reclaims with no OOMs or kills. Write-select's 424 provider bits and
  complete control composition remain pending.
  The write-select mapping probe at
  `build/sparkle/vpu-write-select-root-diagnostic-first.log` records those 424
  raw outputs, all 424 exact writer endpoints and 1,076 input-alias observations,
  including 91 already-related sequence-state inputs. Its native dependency
  frontier is empty; conservative whole-cell traversal of the original leaves
  108 bits unresolved. Packed-vector dependency refinement must establish
  whether those are traversal overapproximations before the equivalence proof
  can proceed. No extra input assumptions are introduced. Three guards pass;
  the diagnostic takes 2.28 seconds, peaks at 195 MiB, and records no limit or
  OOM events. Packed-field and lane-order candidates remain unproved here.
  The precise follow-up at
  `build/sparkle/vpu-write-select-root-diagnostic-precise-first.log` closes both
  dependency frontiers over the same 1,924 observations and unchanged boundary.
  Exact buffer/mux/priority-mux coordinate rules retain all branches and
  selectors; the 108 extra bits were whole-cell traversal overapproximations.
  It retains 249 original and 318 native cells without rewriting the graphs.
  Four guards pass; the run takes 2.31 seconds, peaks at 144 MiB, and records
  no limit or OOM events. Actual projection and equivalence remain pending.
  The full write-select proof subsequently passes at
  `build/sparkle/vpu-write-select-root-bridge-second/summary.json`: 1,924
  comparisons in 121 partitions prove all 424 actual outputs and their 424
  normalized writer endpoints, with the 91 state inputs joined to the full
  startup relation. Complete source/extraction and three-assembly topology
  identities are checked; actual output inversion and undefined-output faults
  are detected. Five proof guards pass. The run takes 375.75 seconds, peaks
  at 3 GiB, and records 69,281 reclaims with no OOMs or kills. The first attempt
  remains incomplete after rejecting an unregistered diagnostic helper; the
  rerun explicitly pins that reviewed implementation without inventing a
  historical owner. Connected-provider dependency order, remaining buffer links,
  genuine external datapath contracts and whole-control trace remain pending.
- `Dram.lean` / `DramABI.lean` and `NativeDram.lean` / `NativeDramABI.lean`:
  behavioral and hardware DRAM interfaces, exposed through `dram[-core]` and
  `native-dram[-core]` generator commands. Four behavioral and three hardware-adapter
  configurations pass arbitrary-state transition proofs, with output mutations rejected.
  Three behavioral ABI tests cover images/pokes/dumps; four native ABI configurations
  pass 24,000 cycles, including production defaults, stalls and all per-channel statistics.
  `dram` and `native-dram` select them individually; `all` selects the appropriate
  implementation for `rtlsim.build_top`'s memory path. All six native-channel
  integration cases pass, covering boot loading, hazard/random programs, high stalls,
  long read latency and WAITW after a store. The expanded 28-test suite with native
  behavioral DRAM, MXU and VPU also passes. FPGA builds are not yet switched.
  `build/sparkle/dram_qualification.json` records source/artifact hashes and the
  explicitly recovered provenance audit; current emitted cores match the proved cores
  byte for byte.

- `Collective.lean`: complete BAR/GATHER unit, specialized for slice/lane counts,
  with the original read/write stages, grant stalls, and acknowledgement timing.
- `Float.lean`: the two-stage FP32 multiplier, four-stage FP32 adder, and duplicate
  adder output, preserving rounding, NaNs, signed zeros, and flush-to-zero.
- `FloatConvert.lean`: native float ordering, signed-integer conversion, signed-byte
  quantization, and floor helpers. Standalone builders with unrestricted stage
  equivalence checks; native VPU and streaming-engine callers use these helpers.
- `QuantScale.lean`: native quantizer scale/inverse pipeline, including three
  separately rounded Newton steps, flags, tags, resettable delay endpoints, and
  grant stalls. Selected by `qscale` or `all`.
- `QuantRead.lean`: native quantizer prescale, delayed read metadata/address, and
  two-stage absolute-maximum tree. Selected by `qread` or `all`.
- `QuantWrite.lean`: native quantizer multiply, signed-byte rounding/saturation,
  and write metadata/scale pipeline. Available independently through `qwrite`.
- `Quant.lean`: complete quantizer command/reader control, streaming block buffers,
  two-pass QST, writeback arbitration, completion, and profiling, composed with the
  three native datapaths. Selected by `quant` or `all`; it replaces `otpu_quant.sv`.
  Controller/storage composition checks cover seven configurations, including
  exact D128 board geometries with eight lanes (17,967 state bits) and four lanes
  (17,963 bits). These proofs check every read/scale/write pipeline input against
  arbitrary pipeline outputs. `qualify_sparkle_quant_board.py` binds both board
  configurations to the exact separately proved datapaths and embedded FP units,
  and checks fresh emission of all eight modules. FP induction applies after
  enabled pipeline fill. Results are in `build/sparkle/formal_quant/summary.json`
  and `build/sparkle/quant_board_qualification/summary.json`.
- `Dma.lean`: native LD/ST/WAITW and the DMA side of DSTEP/STREAM, including
  descriptor decoding, fill sequencing, burst buffers, output gathering, and write
  acknowledgements. Selected by `dma` or `all`; strict resource counts pass.
  All five formal configurations and both mutation checks pass after optimizing
  fill-table initialization.
  Current generation accepts power-of-two `D >= 4`, power-of-two lanes with
  `min(D/4, LANES) < 256`, and power-of-two `DEPTH >= 32`.
- `ActRam.lean`: activation bytes and scales, three-cycle write pipeline, duplicate
  rows, grouped/paired reads, read-before-write behavior, and in-flight-write checking.
  The emitter explicitly clears simulation memory, matching the reference; synthesis
  retains the reference's uninitialized RAM behavior.
- `TMem.lean`: banked scratchpad, general/contiguous routing, shared read copies,
  multiple writes per bank, pending-write bypass, and lane holds. `TMemABI.lean`
  preserves the simulation contract checks, zeroed RAM startup, and memory dumps.
- `VTree.lean`: folding 64-term sum tree, including the eight-lane two-adder
  schedule, general shared lane levels, duplicate root, and schedule checks.
- `Seq.lean`: complete native sequencer, composed from `SeqFetch`, `SeqDispatch`,
  `SeqWindow`, `SeqSchedule`, and `SeqLogic`. Includes instruction RAM, scalar
  registers, nested loops, RLD rendezvous, HALT/CHAIN, command queues, dependency
  tracking, MXU release, and cycle-accurate trace events. Selected by `seq` or `all`
  in `rtlsim`. Instruction RAM currently requires a whole, power-of-two row count
  of at least two; each row holds `D/32` instructions.
- `Backend.lean`: structurally combines compatible byte banks into wide RAMs with
  independent byte write enables. `MemoryProofs.lean` proves the abstract storage
  correspondence for arbitrary write traces; it does not verify the emitter or controller.
- `Physical.lean`: typed `keep`, `shreg_extract`, and `max_fanout` constraints for
  duplicate results, delay endpoints, ACT RAM stages, and TMEM writes/rotations.
  Missing or invalid register targets fail generation.
- `ISA.lean`: packed command representation, a kernel-checked packing roundtrip
  proof, and the RLD conversion specification.
- `Generate.lean`: Verilog emission and adapters for the existing module interfaces.
- `SeMicrocode.lean`: native composite-stage control ROMs for EXP2, EXP2SUB,
  RECIP, RSQRT, and LOG2, including pass counts and stage operand-use masks.
  All class/pass encodings are formally checked for 1, 2, 3, 4, 7, and 10 stages;
  negation and pass-count mutations are rejected. This is a standalone building
  block also used by the native composite engine and VPU. Evidence is under
  `build/sparkle/formal_se_microcode/`.
- `SeHelpers.lean`: composite-function seed preparation, range-reduction floor,
  9-bit integer conversion, and result fixups. Formal checks cover unrestricted
  input bit patterns, including behavior outside the intended arithmetic domains;
  floor and result-sign mutations are rejected. `SeComposite` uses these helpers;
  the complete native VPU includes that composite engine. Evidence is under
  `build/sparkle/formal_se_helpers/`.
- `SeComposite.lean`: native composite-function loop, control/metadata delays,
  operand selection, and range reduction. With external arithmetic (`EXT=1`),
  four configurations pass complete state/output checks, including eight lanes
  and three stages (18,802 state bits); a completion mutation is rejected.
  Internal arithmetic (`EXT=0`) passes the same four configurations: every FP
  interface is checked, and the embedded arithmetic matches the separately proven
  pipelines, under a matched initial-state relation. Both paths reject a completion
  mutation. The interface adapter passes 15 standalone tests and 10 VPU/stream
  interaction tests. Selected by `secomp` or `all`; all 18 combined native-system
  regressions pass with this addition (`all-native-integration-composite.log`). Evidence is under
  `build/sparkle/formal_se_composite/`, `se-composite-tests.log`, and
  `se-composite-vpu-tests.log` (logs are under `build/sparkle/`).
- `SeTail.lean`: native stream-tail vector memories, row-scalar FIFO, segment
  delay RAM, metadata, and shared U/Q arithmetic pipelines. The default
  configuration passes a complete 82,820-bit non-FP state/interface composition
  check and rejects an output mutation; two additional timing configurations also
  pass. Arithmetic modules match the separately proven FP pipelines. All thirteen
  VPU and full-system stream tests pass through its interface adapter. Selected by
  `setail` or `all`; the combined native regression passes all 28 tests with both
  stream units and the corrected ACT RAM enabled. Evidence is under `build/sparkle/formal_se_tail/` and
  `build/sparkle/se-tail-integration.log`.

```sh
lake update                         # fetch Sparkle's pinned LSpec dependency
make sparkle                        # compile Lean and the generator/test executables
make test-sparkle                    # Lean checks + Verilator differential tests
make prove-sparkle                   # Yosys with read_slang: induction + checker self-tests
make prove-sparkle-seq               # sequencer stages, storage, full core, stack safety
make check-sparkle-physical          # inspect attributes and compare to prior proof inputs
python3 tools/synth_sparkle_actram.py --check # compare and gate Kintex-7 resource counts
python3 tools/synth_sparkle_tmem.py --check  # TMEM resource parity gate
python3 tools/synth_sparkle_seq.py           # sequencer counts; --check flags a LUT regression
python3 tools/synth_sparkle_se.py --unit composite --check # stream composite resource gate
python3 tools/synth_sparkle_se.py --unit tail --check      # stream tail resource gate
python3 tools/synth_sparkle_quant.py --check # complete quantizer resource comparison
python3 tools/prove_sparkle_dma.py --self-test # complete DMA state/output checks
python3 tools/synth_sparkle_dma.py --check   # DMA resource comparison
make sparkle-rtl SPARKLE_S=2 SPARKLE_LANES=8

# Run existing RTL/ISA checks with every currently ported unit selected:
OTPU_SPARKLE=all python3 -m pytest -q tests/test_rtl.py
# OTPU_SPARKLE=collective, float, actram, tmem, vtree, seq, qscale, qread, qwrite, quant, dma, secomp, setail, dram, or native-dram selects one component; default is 0.
# Set OTPU_SIM_TMP to a writable directory if the default simulation directory is unsuitable.
```

Run the build, simulation, synthesis, and proof commands above through the
resource gate, for example `python3 tools/sparkle_bounded.py -- make prove-sparkle`.
It permits one heavy job across all agents, caps the entire process tree at
3 GiB RAM and two CPUs, disables swap, and limits compiler parallelism to one.
It requires noninteractive sudo for systemd scope creation; the actual job runs
as the workspace user. If the limits cannot be verified, it refuses to launch.
A busy gate returns 75; a job killed for exceeding its memory limit remains an
incomplete check. Do not retry outside the gate or increase the ceiling.
See [AGENTS.md](AGENTS.md) for the workspace resource policy.

The differential tests check 90,000 collective cycles across five configurations,
200,000 FP pipeline cycles across two latency configurations, and 10,000 cycles
of latency padding, duplicate outputs, and the separately rounded multiply/add
composites, plus 140,000 activation-RAM cycles across seven configurations (including
one column, three columns, three row groups, 96-byte blocks, single-lane operation,
and unaligned boundary writes). ACT RAM tests use randomized Verilator startup;
a self-test removes the memory clearing and requires a data mismatch.
Another 140,000 TMEM cycles across seven configurations
check both the RTL and an independent logical-memory scoreboard, including
read/write collisions, pending-write bypass, shared guests, grant stalls, and
two writes per bank (including sixteen lanes). This includes the project's original standalone TMEM bench
through the native ABI with randomized Verilator startup. Generation runs through Lake's
dependency checks, and emitted RTL contents participate in the Verilator build cache.
The folding-tree bench checks seven `(LANES, LA)` configurations: `(1,4)`, `(2,4)`,
`(4,4)`, `(8,4)`, `(16,4)`, `(8,5)`, and `(4,7)`. Each runs 30,000 cycles with
random stalls and resets, drains outstanding rows, then checks 2,000 cycles of
invalid schedules. Results are compared to both the RTL and the specified
64-term addition order, including NaNs, infinities, signed zeros, and subnormals.

The formal FP miter checks unrestricted 32-bit operands and clock enables, including
stall sequences. It proves the base case and an inductive stage correspondence;
outputs are compared after the relevant unreset pipeline has filled. The collective
miter compares control, pipeline state, and outputs after a synchronous reset, with
commands, grants, request masks and return data otherwise unrestricted. Proofs cover
the collective configurations `(S, LANES) = (1, 1), (2, 4), (4, 8)` and the
base FP pipeline latencies, not arbitrary parameter values. Checker self-tests
intentionally corrupt an output and require proof failure. Logs and source hashes
are saved under `build/sparkle/formal/`.

The conversion/ordering proof checks all 16 standalone helper outputs, including
both integer-to-float and signed-byte-quantization stages with independent,
unrestricted packed stage inputs. It also checks floor's bit behavior outside
its intended arithmetic domain. Corrupting the greater-than comparator must yield
a SAT counterexample. Evidence is in `build/sparkle/formal_float_convert/`.

The scale-pipeline bench checks 90,000 cycles across `(LM,LA,TW)=(2,4,2),(3,5,1),
(2,7,5)`, including random stalls, resets, signed zeros, NaNs, infinities, subnormals,
and saturation boundaries. Thirteen integration cases with `OTPU_SPARKLE=all`
cover single- and two-slice fuzzing plus the D=128 attention kernel.
Its composition proof checks every non-arithmetic state bit, every FP operand and
enable, and all outputs from equal current state with shared arbitrary FP results.
The actual embedded FP add/multiply pipelines are separately proven by unbounded
induction after their enabled pipeline fills, including all padding stages.
Both a control-output mutation and an FP-result mutation must yield counterexamples.
Evidence is in `build/sparkle/formal_qscale/`; this is a compositional proof, not
an assertion of equivalence from independently chosen initial pipeline states.

The quantizer read and write datapaths each have 90,000 differential-test cycles
across 4, 8, and 16 lanes, with arbitrary metadata, random grant stalls, and FP
corner cases. Writer tests also cover synchronous metadata reset during stalls.
Their composition proofs check all non-FP state, all multiplier operands/enables,
and every output; each actual embedded multiplier is independently proven by
unbounded induction after two enabled edges. Output and multiplier mutations must
fail. The reference fragments are extracted only by proof/test tools; production
circuits are built entirely in Lean. Evidence is under `formal_qread/` and
`formal_qwrite/` within `build/sparkle/`. These share the scale proof's initial-state
scope: equal non-FP state and separately filled arithmetic pipelines.

The enabled-fill scope cannot be replaced by an unconditional single-reset
startup claim. `tools/check_quant_reset_scope.py` checks the original
`otpu_qdly` at the writer's four-stage delay, projecting its independent valid
bit. SAT finds a trace where an arbitrary upstream bit survives a reset with
enable low and reaches the output on the next enabled edge, despite zero input.
A separate control proves zero output after four consecutive enabled zero-input
shifts. Archived inputs, scripts, logs and the counterexample are recorded in
`build/sparkle/quant-reset-scope-first/summary.json` (71 MiB peak, no limit/OOM
events). This diagnoses the original delay's startup contract, not a native
mismatch or a whole-quantizer startup theorem.

An additive FP leaf proof now establishes equivalence from corresponding
pipeline states without an enabled-fill mask. `tools/prove_sparkle_fp_state.py`
checks all retained state for multiply latencies 2/3 (125/157 bits), add
latencies 4/5/7 (191/223/287 bits), and duplicated-output add latency 4
(223 bits). It proves immediate output equality and one-step preservation for
arbitrary operands and enables, including stalls. The multiplier's special
value field is related only when its special-case flag is set, matching its
observability in the reference. No state bits are removed from the audit.

The proof also constructs a reference initial-state witness from the actual
native initializers and checks all reference-defined bits. This is initialization
refinement, not equality between independently arbitrary initial states.
All 18 initialization/output/preservation obligations pass and all 12 actual
output/hold-enable faults are rejected; 14 guard tests pass. The receipt is
`build/sparkle/formal_fp_state/attempt2/summary.json` (7.93 seconds, 206 MiB peak,
no limit events). The first extraction failure is preserved. Existing after-fill
proofs remain separate. A consistent complete parent initialization relation
and its composition with these FP relations remain pending.

The additive consumer binding now authenticates this theorem against all 12 FP
definitions and 145 reachable FP instances in each Gen1, Gen2 and CLI assembly.
It preserves all module tokens and incoming directives, with one explicit
physical-attribute bridge: `keep="true"` on the VTREE duplicated adder's
`result_copy` register. The production stream composite uses shared VPU lane
arithmetic; its standalone private multiplier/adder are absent and are not
claimed by this receipt. The initial source-only count of 14 definitions was
corrected against the elaborated production inventory; that incomplete attempt
is preserved. Evidence is
`build/sparkle/fp-state-consumer-binding-second/qualification.json` and
`summary.json`; 21 guards pass. The binding took 105 seconds, reached the 3 GiB
cap with 114,729 reclaim events, and recorded zero OOMs/kills. This adds leaf
applicability alongside the existing after-fill evidence; it explicitly does
not claim whole-parent initialized equivalence.

The production quantizer writer now has its own complete product-relation
proof, including concrete arithmetic: LANES8/LM2, all 2,308 state bits per
design (1,308 non-FP plus eight 125-bit multipliers). Initialization refinement,
immediate equality of every output, and one-step preservation pass under
arbitrary inputs, enables and resets, without fill masks or arithmetic
cutpoints. Actual output corruption, broken input hold, and removed metadata
reset each yield counterexamples. Ten guards pass. Evidence is
`build/sparkle/formal_qwrite_product/attempt1/summary.json` (23 seconds,
1.73 GiB peak, no limit events); all 186 recorded live input hashes were
independently checked. This is the writer theorem, not yet a complete
initialized-Quant composition theorem.

Exact production-instance binding now passes for this complete writer theorem:
one writer and its eight reachable multiplier instances in each Gen1, Gen2 and
CLI assembly. Both complete module token streams and incoming directives match,
with no name or attribute normalization. Current `QuantWrite.lean` and
`Float.lean` source hashes also match the theorem. The receipt is
`build/sparkle/qwrite-product-consumer-binding-first/qualification.json`;
21 guards pass. Binding took 97 seconds, reached the 3 GiB cap with 80,174
reclaim events, and recorded zero OOMs/kills. Its scope remains writer
initialization refinement; the complete production-Quant composition is described below.

The production reader also passes a complete product-relation proof at
LANES8/LM2/QL5: 4,290 retained state bits per design (2,290 non-FP plus sixteen
125-bit multipliers). Initialization refinement, immediate equality of every
output, and preservation under arbitrary inputs/enables pass without fill masks
or arithmetic cutpoints. The reader has no reset port; none is assumed.
Actual output, hold-enable and row-factor-selection mutations are rejected;
11 guards pass. Evidence is
`build/sparkle/formal_qread_product/attempt1/summary.json` (52.5 seconds,
1.81 GiB peak, no limit events). All 185 live receipt input hashes were
independently checked. Exact production-instance binding now passes for one
reader and its sixteen reachable row/column multipliers in each Gen1, Gen2 and
CLI assembly, preserving complete module tokens and incoming directives.
Evidence is `build/sparkle/qread-product-consumer-binding-first/qualification.json`;
21 guards pass. Binding took 101 seconds, reached the 3 GiB cap with 93,716
reclaim events, and recorded zero OOMs/kills. This establishes applicability of
the reader initialization-refinement theorem; complete production-Quant composition
is described below.

The production scale pipeline also passes its complete product-relation proof
at LM2/LA4/TW2: all 4,111 state bits (2,538 local, eight concrete multipliers,
and three concrete adders). Initialization, immediate output agreement, and
one-step preservation pass with arbitrary inputs, enables and resets. The
initial witness preserves the seven nonzero `k0` sign-bit initializers; no
fill mask or positivity assumption is used. Output, hold-enable, and reset
mutations are rejected; 12 guards pass. Evidence is
`build/sparkle/formal_qscale_product/attempt1/summary.json` (56 seconds,
2.76 GiB peak, no limit events). Exact production-instance binding now passes
for the scaler, eight multipliers and three adders in each Gen1, Gen2 and CLI
assembly, with all module attributes and incoming directives preserved.
Evidence is `build/sparkle/qscale-product-consumer-binding-first/qualification.json`;
27 guards pass. Binding took 93.74 seconds, reached the 3 GiB cap with 55,478
reclaim events, and recorded zero OOMs/kills.

Whole-Quant initialized product composition now passes at D128/LANES8, accounting
for all 28,676 state bits: 17,967 controller/storage bits plus the concrete
reader, writer and scale relations above. The 16,960 unspecified initial RAM
bits remain shared arbitrary values. The checker authenticates the parent
transition theorem, reconstructs complete state and initialization mappings,
checks the reference array adapters and parameters, verifies state-only child
output cones, and binds a fresh compiled Lean emission. Completion, buffer-write
and reader-enable faults each produce actual SAT counterexamples; 36 guards
pass. Evidence is `build/sparkle/quant_product/attempt2/summary.json`, with 379
authenticated inputs (217.29 seconds, 3 GiB peak, 1,191 reclaim events, zero
OOMs/kills). The first metadata-schema failure is preserved. This establishes
refinement from the recorded related initial states for this configuration;
other configurations and whole-board startup remain separate obligations.
The additive production audit also binds this theorem to Gen1, Gen2 and CLI:
all eight module definitions, the three owned pipeline products and 35 reachable
FP children match exactly, including attributes and incoming directives.
Evidence is `build/sparkle/quant-product-consumer-binding-first/qualification.json`;
30 guards pass. Binding took 94.46 seconds, reached the 3 GiB cap with 52,830
reclaim events, and recorded zero OOMs/kills. The supporting generic Lean composition rule is
kernel-checked, but these concrete SAT premises are not instantiated in Lean.

The concrete MXU epilogue now passes initialized product refinement at
D128/C4/IMPL2/CL16: all 8,197 state bits (4,523 local, eight multipliers and
fourteen adders). Initialization, immediate output agreement and one-step
preservation pass without arithmetic cuts, state pruning, fill masks or a
reset schedule. Actual output, hold-enable and reset faults yield SAT
counterexamples; 25 guards pass. Evidence is
`build/sparkle/mxu_epilogue_product/attempt1/summary.json` (198.86 seconds,
3 GiB peak, 8,496 reclaim events, zero OOMs/kills). Its concrete native
initialization is matched by an existential reference witness. Production
consumer binding also passes for Gen1, Gen2 and CLI: the complete epilogue
and its 22 reached arithmetic instances match the authenticated theorem,
including each specialization, module attributes and incoming directives.
Evidence is
`build/sparkle/mxu-epilogue-product-consumer-binding-first/qualification.json`;
42 guards pass. Binding took 92.96 seconds, reached the 3 GiB cap with 56,416
reclaim events, and recorded zero OOMs/kills. Whole-MXU RAM, control and DSP
initialization, C2 applicability and whole-board startup remain separate
obligations.
The remaining physical-MXU proof needs more than the epilogue result: existing
DSP transition proofs and dot extractions discard initialization, and PREG0
cascade outputs depend on current inputs. The new leaf initializer audit below
closes the leaf base obligation. Dot-local initialization and the acyclic cascade
dependencies now also have separate certificates below; their complete initialized
composition remains open. The controller proof
also omits 1,508 unobserved register bits per side; those need explicit accounting
before any full-state claim. The source/receipt assessment is recorded in
`build/sparkle/mxu_initialization_next/ASSESSMENT.txt`; it is a plan, not a proof.

All nine DSP leaf configurations now pass an additive initialization audit:
eight FIRST/LAST/WREG combinations and the SW23 column end. Fresh extraction
retains initialization, checks every retained state bit, and matches the entire
transition graph to the authenticated prior theorem under a bijective bit
renaming. Native undefined bits remain arbitrary (18 or 48 per PE; 192 per
column end); the reference witness shares those values. All nine native-only
Br2 initializer mutations are rejected specifically by the initial-predicate
check after successful extraction and transition-graph matching. There are
44 passing guards. Evidence is
`build/sparkle/mxu-dsp-initial-second/summary.json` (6.63 seconds, 2.47 GiB peak,
no limit events). Slang cannot read a net in the original CARRYOUT initializer;
the checked frontend bridge expands only its parameter-selected constant RHS,
preserving every `x` bit and all synchronous behavior. This establishes static,
parameter-elaborated formal initialization constraints, not four-state time-zero
simulation equivalence or physical device startup. The initial extraction
failure is preserved. Production consumer binding now passes for Gen1, Gen2
and CLI: all nine proven helper definitions match, and all 528 reached DSP
terminals are covered through their authenticated occurrence projections.
The seven reached helper kinds account for 102,516 concrete leaf state bits
per assembly; `pe_110` and `pe_111` are proven definitions without production
occurrences. Complete parameters, pins and omitted outputs are checked.
Evidence is
`build/sparkle/mxu-dsp-initial-consumer-binding-second/qualification.json`;
43 guards pass. Binding took 93.83 seconds, reached the 3 GiB cap with 49,614
reclaim events, and recorded zero OOMs/kills. The first binding attempt's
directive-serialization mismatch is preserved. A concrete cascade dependency
certificate now passes for the authenticated C4/IMPL2/CL16 physical-dot pair:
all 512 PE and four column-end helper occurrences (528 DSPs) admit a common
original/native output dependency order. The checker traverses all eighteen
concrete leaf graphs and both actual parent graphs, checking drivers, clocks,
complete cut contracts and internal combinational cycles. Exact empty helper
blackbox declarations are validated separately from their concrete behavior.
Evidence is `build/sparkle/mxu-cascade-second/summary.json`; 29 guards pass.
The check took 7.81 seconds, peaked below 3 GiB and recorded no limit events.
The first parser failure on auxiliary declarations is preserved. This certifies
noncircularity rather than initialized MXU equivalence by itself. The initialized
dot composition and production parent binding are completed below; outer-MXU
composition remains open.
An actual source-wiring mutation is now detected: one LAST-PE cascade input is
connected to its own 48-bit output, freshly extracted, and rejected with an
explicit self-dependency witness. All 516 helper instances and 61,323 local
state bits remain audited; exact helper `keep` annotations prevent optimization
from deleting the disconnected upstream cascade. Evidence is
`build/sparkle/mxu-cascade-mutation-third/summary.json`; 16 mutation guards pass.
The check took 7.16 seconds, used 1.85 GiB peak and recorded no limit events.
The earlier provenance-lookup and optimized-away-helper failures are preserved.
This is a concrete structural negative control, not an arithmetic counterexample
or a whole-MXU initialization theorem.

The physical-dot local parent now passes an initialization/observational-quotient
bridge under shared arbitrary DSP helper outputs. Fresh initializer-preserving
extraction matches the complete authenticated transition graphs under bijective
net renaming. All 61,323 native local Q bits have defined initial values and an
explicit matching reference witness. All 2,048 additional reference Q bits are
independently excluded from every output, retained next-state cone and helper
input; their initial witnesses respect actual reference constraints. Disk-backed
graph processing preserves all initializer aliases and complete Q/D relations.
Evidence is `build/sparkle/mxu-dot-initial-first/summary.json` (437 inputs,
58.80 seconds, 3 GiB peak, 8,951 limit reclaims, no OOM); 55 guards pass.
This is the local parent theorem, not composition with concrete DSP outputs,
current production-parent binding, four-state startup or whole-MXU equivalence.
An actual conflicting-reference-initializer control now passes: a private source
copy adds `initial wd[0] = 16'h0001`, preserves the complete transition graph,
and is rejected specifically because that constraint conflicts with native zero.
The target is located through all 16 paired source/native alias bits in the
actual numbered state relation, not an assumed field name. Every other physical
reference initializer remains checked. Evidence is
`build/sparkle/mxu-dot-initial-mutation-first/summary.json` (58.25 seconds,
3 GiB peak, 13,039 limit reclaims, no OOM); 21 guards pass. This is a deliberately
changed-reference fault test, not an original-source counterexample. Changing
native initialization alone need not violate an unconstrained reference witness.
The reused legacy transition proofs also retain their SAT encoding scope:
without explicit undef modelling, literal X/Z values are mapped to zero. Their
passes do not establish universal equality across arbitrary resolutions of those
values. Whole-dot initialized composition still requires an explicit definedness
or coherent-unknown semantics bridge in addition to the initialization and DAG
certificates; neither new initialization receipt claims to close that obligation.
An explicit-undef probe completed all 18 DSP leaf-side checks with every output
and mapped next-state bit defined for arbitrary defined state/input ports. The
full parent query exceeded the bounded 3 GiB scope during SAT import and was
killed; no parent result or complete probe receipt is claimed. The unchanged
partial receipt and logs are archived in `build/sparkle/mxu-dot-definedness-first/`,
with `interruption.json` recording the scope-local OOM and completed leaf checks.
Partitioned parent checks now establish definedness for the first 46,208 gold
output/next-state bits in 361 complete partitions. The third attempt authenticated
and reused 329 earlier partitions, then proved 32 more. It preserves unused mux
sibling bits as undriven internal wires and independently rejects omitted state
on every actual observed dependency path; 46 checker guards pass. The next
partition, `[46208,46336)`, exceeded the same 3 GiB scope during SAT processing.
The incomplete receipt, solver inputs and scope OOM evidence are preserved in
`build/sparkle/mxu-dot-definedness-partitioned-third/`, including an interruption
record. That attempt establishes no complete parent result. Its failure required
reducing the representation of wide cells while preserving every obligation and
reusing completed checks at the unchanged resource ceiling.
The fourth attempt completes this definedness check:
`build/sparkle/mxu-dot-definedness-partitioned-fourth/summary.json` (8,210 inputs,
207.84 seconds, 3 GiB peak, 2,881 limit reclaims, no OOM; 60 checker guards).
Each parent side has all 100,726 output/next-state bits checked in 787 exhaustive
partitions, alongside the 18 completed DSP leaf-side checks. All are defined for
arbitrary defined state/input ports. The run reuses all 361 earlier partitions
with exact graph identity; new partitions project only required mux coordinates,
preserving their A/B/Y bits and common selector under the audited explicit-undef
model. Other primitives remain intact. This closes the definedness probe, not
whole-dot initialized equivalence: lifting historical X-to-zero transition
proofs still requires an actual primitive-semantics audit (definedness alone
does not justify that lift for X-sensitive operations), followed by concrete
DSP composition and production-parent binding.
The actual primitive inventory now covers all 20 helper/parent sides:
`build/sparkle/mxu_dot_primitive_inventory/actual-first/summary.json` (2.36 seconds,
110 MiB peak, no limit events). It finds `$eqx` in five helper configurations on
both sides and no literal Z anywhere. Thus the historical binary proof cannot
be lifted merely by assuming X-sensitive primitives are absent. The next proof
stage will check strict gold/native equality directly with explicit undefined
values, retaining all outputs and mapped next-state obligations.
The first direct paired attempt is preserved at
`build/sparkle/mxu-dot-paired-undef-first/summary.json`. All 16 checker guards pass,
but the first complete `pe_000` query reaches its unchanged 180-second SAT
timeout without a result (186.10 seconds overall, 1.68 GiB peak, no limit events).
It remains incomplete, with exact inputs and logs preserved. The smaller second
attempt, `build/sparkle/mxu-dot-paired-undef-second/summary.json`, passes four
16-bit `pe_000` partitions covering [0,64), then times out on [64,80). Complete
coverage remains required; the successful prefix is preserved for authenticated
reuse (365.56 seconds overall, 1.12 GiB peak, no limit events; 82 guards).
The bounded diagnostic at `build/sparkle/mxu-arithmetic-diagnostic-first/summary.json`
finds exactly matching, structurally defined 43-bit multiplier expressions on
both sides of that timed-out cone (0.41 seconds, 30 MiB peak; seven guards).
That diagnostic does not rewrite the graph or establish equality. Subsequent
exact-source model authentication and 13 guards pass after fetching the installed
Yosys derivation's exact source tree and checking its recursive hash. The
certificate at `build/sparkle/mxu-defined-sharing-first/summary.json` removes nine
duplicate defined expressions and substitutes 212 output bits, preserving all
observations without new inputs or assumptions (31.32 seconds, 3 GiB peak,
3,337 reclaims, no OOM). Unknown-valued expression outputs remain separate.
`build/sparkle/mxu-shared-query-first/summary.json` then independently replays
that certificate/model and proves strict explicit-undef equality for the original
`pe_000` [64,80) interval (7,186 inputs, 24.17 seconds, 3 GiB peak, 1,206 reclaims,
no OOM). The initial source-acquisition receipt remains incomplete because a
literal model-body check first rejected whitespace differences; exact-source
model validation subsequently passed without re-fetching. Full nine-helper and
parent coverage subsequently passes with this representation at
`build/sparkle/mxu-dot-paired-shared-first/summary.json`: all nine helper
configurations and all 100,726 parent output/next-state bits (787 parent
partitions), with four authenticated earlier intervals reused. The run verifies
14,004 inputs, takes 562.65 seconds, reaches 3 GiB with 17,671 reclaims and no OOMs
or kills; 43 guards pass. No timeout or memory ceiling was increased. This closes
direct explicit-undefined equality. The model-existence certificate also passes
at `build/sparkle/mxu-model-extension-first/summary.json`: 20 complete graphs,
98,186 cells and all 15 actual primitive types, with exact source-model,
driver, schema and acyclicity checks (14,049 inputs, 85.28 seconds, 3 GiB peak,
9,157 reclaims, no OOMs or kills; 37 guards). It preserves literal-X semantics
and all 2,048 original-only state roots without added constraints. The
source-reviewed constructive model argument and mechanical graph certificate
close nonvacuity in the pinned Yosys model; this is not a Lean-kernel theorem.
The initialized dot composition subsequently passes at
`build/sparkle/mxu-dot-initialized-composition-first/summary.json` (14,056 inputs,
80.84 seconds, 3 GiB peak, 15,202 reclaims, no OOMs or kills; 19 guards). It
replays full physical Q/D and initialization correspondence, all 516 helper
occurrences, and the 1,028-node cascade with 64 dependency edges. One legal
reference initial witness covers all 163,839 mapped state bits (61,323 parent
plus 102,516 helper bits) and 2,048 reference-only bits, which evolve under their
actual transitions. Full parent/helper equality and exact dependency independence
establish synchronous trace refinement under shared inputs. This is an external
composition checker with a reviewed induction argument, not a concrete
Lean-kernel instantiation. Production parent applicability also passes at
`build/sparkle/mxu-dot-initialized-applicability-first/summary.json` (16,744 inputs,
383.86 seconds, 3 GiB peak, 92,977 reclaims, no OOMs or kills; five guard tests).
Each Gen1/Gen2/CLI assembly binds the reached monomorphic dot definition and all
17 actual parent connections, 516 helper occurrences and 528 terminal DSP
occurrences, including containing-module identities and directive contexts.
Exact original-reference reconstruction, current primitive model and current
generator source closure are checked. This qualifies the initialized dot in
those assemblies; outer-MXU/controller/RAM composition, device power-up,
four-state simulation and physical timing remain outside this theorem.
The next outer-MXU initialization audit is incomplete at
`build/sparkle/mxu-outer-initial-first/summary.json`: the legacy receipt lacks
the generating-source manifest expected by the draft (29 guard tests pass).
Its RTL and flat/cut/mapped/step graphs are authenticated, but historical
generation-source identity must not be invented. A bounded graph diagnostic
also identifies 11 residual original memories after the eight large RAM cuts:
33 words totaling 2,297 bits, all with unspecified initial contents. Their
mapping into registers/muxes needs an explicit bridge before the retained-state
initialization result can be claimed; the draft's direct graph-isomorphism
assumption is insufficient. The second attempt rejects dynamic high address
bits on eight `mk` reads; the third preserves those bits and out-of-range X
outcomes but stops at absent floating-point port-direction metadata. The fourth
attempt resolves those directions from exact authenticated blackbox declarations,
then stops at an ordinary-cell metadata mismatch during the lowering comparison
(`build/sparkle/mxu-outer-initial-fourth/summary.json`; 2.26 seconds, 387 MiB
peak, no limit events). The fifth validates resolved directions independently
of their serialization, then rejects a memory read-mux equation mismatch
(`build/sparkle/mxu-outer-initial-fifth/summary.json`; 16.23 seconds, 139 MiB
peak, no limit events). All attempts remain incomplete; 102 latest guard tests pass.
The bounded read-equation diagnostic confirms that mapped `mk` read port 4
discards the third address bit: the original returns unknown data out of range,
while the mapped graph selects a word using only the low two bits. This is a
semantic mismatch, not redundant graph metadata. A contextual proof that the
difference cannot affect observations, or a justified directional refinement,
is required; no in-range input assumption has been added.
The revised finite memory
coordinate checker must not be treated as raw SAT value/undefined-model identity;
that correspondence is still a separate obligation. No outer-MXU initialization
or trace proof is claimed.
The independently scoped initialization-only certificate now passes at
`build/sparkle/mxu-outer-initial-ownership-fourth/summary.json` (114 authenticated
inputs, 32.31 seconds, 275 MiB peak, no limit events; 52 guard tests pass).
It verifies all 33 residual words/2,297 bits and complete physical-state
initial constraints, eight arbitrary RAM arrays totaling 1,204,224 bits, and
the mapped graph's 5,928 retained/1,508 omitted bits per side. All 2,553 original
read coordinates are classified: 2,297 coordinate equations match and 256
known `mk` differences remain explicitly unresolved. Earlier attempts remain
incomplete at a removed live shift-register alias, relocated initializer
annotations, and unsupported `$bmux` dependency auditing. The completed checker
reconstructs only exact constant-address word references, verifies every consuming
write equation, compares the complete physical initial predicates across all
aliases, and checks every selector input and the full combinational dependency
graph. This certificate applies to authenticated archived graphs; current
production binding, the original collected-memory quotient, read-transition
semantics and outer trace refinement remain unproved.
The auxiliary memory-control experiment now completes at
`build/sparkle/mxu-outer-control-definedness-first/summary.json`, but finds an
undefined-control witness rather than proving totality: 32 `mk.WR_EN`
coordinates are undefined in the returned model. Its shared arbitrary
read-value/undefined-bit abstraction overapproximates actual memory reads, so
this alone is not a hardware counterexample. The actual 16-row SatGen mask
coverage and full primitive model-extension audit pass; 58 guards pass. The
run takes 20.14 seconds, peaks at 1.51 GiB and records no memory-limit or OOM
events. Exact memory expansion, all-D definedness and outer refinement remain
unproved; the witness must be diagnosed before using a defined-control bridge.
The authenticated follow-up diagnostic at
`build/sparkle/mxu-outer-control-witness-diagnostic-first.json` identifies an
inadmissible undefined choice for `mk` read port 1, bit 0, at constant address 1
(original offset 0). Defined word state makes that read defined. This rules out
directly instantiating this particular auxiliary assignment as a real-memory
witness; it does not prove control totality or exclude other witnesses. The next
abstraction must bind such reads to their actual shared word state and repeat
the complete query.
That refined auxiliary stage now passes at
`build/sparkle/mxu-outer-constant-read-controls-first/summary.json`: all 3,609
original read-address/write-enable bits are defined, retaining all 7,436 state
bits and every original read identifier/fanout. Exactly 2,169 constant in-range
read bits use their existing shared word-Q coordinates; the remaining 384 read
bits retain unrestricted shared value/undefined choices. The independently
authenticated asynchronous read rule, complete driver/DAG audit and actual
16-row SatGen mask coverage pass, along with 69 guards. Qualification takes
15.07 seconds, peaks at 1.30 GiB and records no memory-limit or OOM events.
The lemma requires defined full Q and defined external RAM/FP boundary returns;
child-output definedness is not discharged. No in-range, command or mask
assumption is introduced. Exact original memory expansion, all next-state
definedness, original-context quotient, production binding and outer trace
refinement remain separate obligations.

The first complete-memory transition experiment is preserved as incomplete at
`build/sparkle/mxu-outer-memory-expansion-first/summary.json`. It constructs
all original array reads and masked writes, including out-of-range unknowns,
and preserves all 7,436 Q/D coordinates on each side. Both complete next-state
definedness queries finish without a counterexample, but the combined
5,928-bit retained-state equality query reaches its 180-second solver limit.
The overall run takes 212.75 seconds, peaks at 2.33 GiB, and records no
memory-limit or OOM events; 26 guards pass. Overall theorem flags remain false.
The immutable graphs, relation, query scripts and logs are retained for an
authenticated partitioned continuation rather than another extraction.
The first partitioned continuation is also preserved as incomplete at
`build/sparkle/mxu-outer-partitioned-D-first/summary.json`: 140 disjoint
16-bit queries finish without counterexamples, covering retained-D coordinates
[0,2240), before the [2240,2256) query reaches its solver timeout. It takes
216.27 seconds, peaks at 804 MiB and records no memory-limit or OOM events.
Fifteen guards pass. These partial results do not establish full retained-state
equality; authenticated resume can reuse them while splitting the remaining
obligations more finely, with the same original roots and complete cones.
The one-bit continuation at
`build/sparkle/mxu-outer-partitioned-D-second/summary.json` authenticates those
140 results and proves nine additional coordinates, covering [0,2249), before
coordinate 2249 times out. It takes 281.68 seconds, peaks below 860 MiB and
records no memory-limit or OOM events. Full equality remains unresolved; the
next step is inspection of that exact arithmetic cone, not another identical
solver retry.
The resulting operand lemma passes at
`build/sparkle/mxu-outer-operand-lemma-first/summary.json`: all 128 actual input
bits of the two unsigned 32-bit multipliers are defined, and all 64 corresponding
operand bits are equal on the unchanged original roots. Both undefined-input
and wrong-value negative controls are detected. Exact dependency projection,
primitive semantics and multiplier identities are authenticated; 16 combined
diagnostic/operand guards pass. Qualification takes 6.79 seconds, peaks at
287 MiB and records no memory-limit or OOM events. Multiply substitution and
the original retained-D query remain unproved; this lemma supplies a premise
for a separately checked representation change, not full MXU equivalence.
That representation change now passes for the stalled coordinate at
`build/sparkle/mxu-outer-mul-congruence-first/summary.json`. It requalifies the
operand queries, authenticates deterministic multiplication semantics and
checks replacement of all 32 output coordinates across the complete query
graph. The unchanged D[2249] mismatch query then finishes without a
counterexample. Eight guards pass; qualification takes 3.68 seconds, peaks at
83 MiB and records no memory-limit or OOM events. Together with the earlier
partitions, coverage reaches [0,2250); complete 5,928-bit equality and applying
the lemma to further dependency cones remain separate obligations.
The complete-coverage continuation is preserved as incomplete at
`build/sparkle/mxu-outer-complete-D-first/summary.json`. It reconstructs the
original full graph, checks the operand-lemma lift and one full-graph
substitution, then requalifies the earlier 2,250-bit coverage. Ten further
16-bit intervals pass, reaching [0,2410), before [2410,2426) times out.
Thirteen guards pass. The run takes 203.02 seconds, peaks at 1.16 GiB and
records no memory-limit or OOM events. Global theorem flags remain false;
immutable resume retains the completed intervals and all remaining obligations.
The next graph simplification is certified at
`build/sparkle/mxu-outer-generic-sharing-first/summary.json`: full-graph
defined-expression sharing removes 4,353 of 22,480 cells and substitutes 31,434
output coordinates, preserving unknown choices, all observations and metadata.
Thirteen guards pass; certification takes 19.95 seconds, peaks at 1.32 GiB,
and records no memory-limit or OOM events. This certifies only the transformation;
requalifying the original proof chain and checking the remaining 3,518 D bits
on the shared graph remain separate obligations.
The first continuation at `build/sparkle/mxu-outer-shared-D-first/summary.json`
requalifies all 160 earlier intervals covering [0,2410) and the complete sharing
transformation, but [2410,2426) still reaches the solver timeout. The reduced
query contains 52,919 variables versus 111,703 previously. Twenty guards pass;
the run takes 210.18 seconds, peaks at 1.82 GiB, and records no memory-limit or
OOM events. It remains incomplete with all global theorem flags revoked.
The one-bit resume at `build/sparkle/mxu-outer-shared-D-second/summary.json`
retains that baseline and proves D[2410] and D[2411], reaching [0,2412).
D[2412] times out and remains unresolved. The run takes 209.74 seconds,
peaks at 692 MiB, and records no memory-limit or OOM events; its global theorem
flags remain false and all inputs and partial results are preserved.
The first reversed-comparator operand lemma passes at
`build/sparkle/mxu-outer-predicate-operands-first/summary.json`: all 128 actual
operands of original `gold:$755` and native `gate:$2309` are defined, and all
64 swapped operand pairs are equal. Undefined and inverted-operand faults are
detected. Fourteen guards pass; the run takes 11.66 seconds, peaks at 1.15 GiB,
and records no memory-limit or OOM events. Comparator congruence, the full-graph
substitution and the remaining retained-D coverage still require separate proofs.
The eight-pair batch passes at
`build/sparkle/mxu-outer-predicate-batch-first/summary.json`: all 1,024 actual
operand bits are defined and all 512 swapped pairs are equal, without assuming
earlier predicate equality. Both fault controls pass. Seven guards pass;
the run takes 12.59 seconds, peaks at 1.97 GiB, and records no memory-limit or
OOM events. The separate actual-SatGen rule at
`build/sparkle/mxu-outer-predicate-rule-first/summary.json` proves both outputs
defined and unsigned 32-bit `gt(A,B) = lt(B,A)` for all defined inputs, with a
wrong-orientation counterexample. Four guards pass; the run takes 0.72 seconds
and peaks at 75 MiB without limit events. Full-graph lifting and substitution
remain separate obligations; these certificates do not add retained-D coverage.
The full-graph lift and eight-predicate substitution pass at
`build/sparkle/mxu-outer-predicate-congruence-first/summary.json`. It replays all
seven operand/rule queries, verifies complete target bodies and dependency
paths, preserves every remaining owner and alias, and checks the transformed
graph for cycles. Nine guards pass; certification takes 17.39 seconds, peaks at
1.20 GiB, and records no memory-limit or OOM events. Original-lineage and prior
coverage requalification, remaining D equality, and whole-MXU refinement remain
separate obligations.

The predicate-graph continuation at
`build/sparkle/mxu-outer-predicate-D-first/summary.json` requalifies the complete
chain and all 162 earlier intervals through bit 2,411. Two new 16-bit intervals
pass, extending retained-D coverage to [0,2444); [2444,2460) times out. Nineteen
guards pass after correcting one test's expected exception class. The run takes
213.72 seconds, peaks at 781 MiB, and records no memory-limit or OOM events.
The result remains incomplete, with inputs and successful intervals preserved.
The immutable single-bit resume at
`build/sparkle/mxu-outer-predicate-D-second/summary.json` preserves that prefix
and times out on bit 2,444 alone (45,901 variables, 123,625 clauses). It takes
213.66 seconds, peaks at 793 MiB, and records no limit or OOM events. The
read-only follow-up at
`build/sparkle/mxu-outer-predicate-single-diagnostic-first/summary.json` passes
after 12 guards, taking 12.59 seconds and peaking at 489 MiB without limit
events. It authenticates the exact failed query and predicate-transformed
graph; it neither adds proved bits nor promotes candidate equalities.
The next eight actual comparator pairs are recorded in an explicit SHA-pinned
configuration. Their operand proof passes at
`build/sparkle/mxu-outer-configured-predicate-operands-first/summary.json`:
all 1,024 operand bits are defined and all 512 swapped pairs are equal, with
both fault controls detected. Fourteen guards pass. The run takes 16.66 seconds,
peaks at 2.42 GiB, and records no limit or OOM events. Full-graph substitution
and additional retained-D coverage remain separate obligations.
The configured full-graph substitution then passes at
`build/sparkle/mxu-outer-configured-congruence-first/summary.json`. It replays
the operand and comparison-rule evidence, lifts every actual target and root
to the predecessor graph, and checks the complete simultaneous substitution
and resulting dependency graph. The certificate and continuation have 28
passing guards. Certification takes 20.72 seconds, peaks at 2.85 GiB, and records
no limit or OOM events. Additional retained-D coverage requires the continuation.
That continuation at `build/sparkle/mxu-outer-configured-D-first/summary.json`
requalifies 164 earlier intervals and proves two additional 16-bit intervals,
extending the preserved prefix to [0,2476). The next interval [2476,2492)
times out, so the result remains incomplete. It takes 220.66 seconds, peaks
at 902 MiB, and records no limit or OOM events. All inputs and successful
intervals are preserved for subsequent work.
The read-only whole-graph inventory at
`build/sparkle/mxu-outer-full-predicate-inventory-first/summary.json` then records
every comparator in the configured graph, including 18 eligible original and
105 eligible native comparisons. Its exact-vector criterion shortlists 66 of
1,890 schema-compatible opposite pairs; ambiguous and unmatched owners remain
explicit. Thirteen guards pass. Inventory takes 17.34 seconds, peaks at 1.87 GiB,
and records no limit or OOM events. Candidate selection is not an operand proof
and adds no retained-D coverage.
Actual literal-selector paths resolve the ambiguous retained-word candidates.
The full-graph operand batches at
`build/sparkle/mxu-outer-fullgraph-operands-word2-first/summary.json`,
`build/sparkle/mxu-outer-fullgraph-operands-word3-first/summary.json`, and
`build/sparkle/mxu-outer-fullgraph-operands-other-first/summary.json` all pass,
covering 8, 8 and 2 pairs respectively. Each proves complete operand definedness
and swapped equality with actual fault controls; the final batch also resolves
the pair whose 16 operand coordinates remained opaque to the diagnostic.
Fourteen full-graph operand guards and five selector-path guards pass. The runs
take 13.97/16.36/12.96 seconds, peak at 356/243/230 MiB, and record no limit or
OOM events. Simultaneous full-graph substitution and remaining retained-D
coverage still require separate certificates.
The simultaneous certificate at
`build/sparkle/mxu-outer-all-predicates-first/summary.json` then passes: it
replays all three operand batches and the exact unsigned comparison rule,
verifies coverage of all 18 remaining eligible original comparisons, and
checks complete-owner substitution and the resulting dependency graph.
Six guards pass. Certification takes 21.60 seconds, peaks at 2.91 GiB, and
records no limit or OOM events. This certifies the transformation; remaining
next-state coverage and whole-MXU refinement are still separate obligations.
The continuation at `build/sparkle/mxu-outer-all-predicate-D-first/summary.json`
now proves all 5,928 retained next-state bits equal. It requalifies all 166
earlier intervals and proves 216 additional intervals, covering [0,5928)
without gaps; original full-D definedness and the complete transformation chain
are also requalified. Nineteen guards pass. The run takes 90.37 seconds, peaks
at 2.11 GiB, and records no limit or OOM events. The original collected-memory
bridge/quotient, public outputs, RAM/FP child-definedness assumptions, initialized
trace composition and current-production binding remain unproved by this result.
The subsequent certificate at
`build/sparkle/mxu-outer-memory-bridge-third/summary.json` passes the explicit
discrete memory-model extension and retained-transition quotient. It reconstructs
the complete graphs, physical manifests and state relation, checks their exact
serialized identities against the archived proof inputs, and requalifies the
control and full-D premises. Out-of-range reads retain their unknown values and
shared read identities; no in-range assumption is added. Thirty-five guards
pass. Certification takes 23.75 seconds, peaks at 1.09 GiB, and records no limit
or OOM events. Two earlier attempts remain incomplete: exact diagnostics found
integer versus JSON string dictionary keys, resolved through complete serialized
artifact identity checks. This result still assumes defined full state and
RAM/FP returns. Source SystemVerilog/event semantics, public observations,
initialization, child-return definedness and current-production binding remain
separate obligations.
The complete boundary inventory at
`build/sparkle/mxu-outer-observation-inventory-first/summary.json` then qualifies
130 actual ports with 5,829 bit occurrences per side: 2,187 top outputs,
3,122 RAM inputs and 520 FP inputs. It preserves constants, aliases and the
complete original paired graph while adding observation ports. Eight guards
pass. The run takes 25.95 seconds, peaks at 3 GiB, and records 9,941 reclaims
with no OOMs or kills. This establishes complete observation coordinates;
their definedness and equality still require separate queries.
One source-level discrepancy under investigation is the RMAX `mk` read:
`rtl/mxu/otpu_mxu.sv` retains `MW = clog2(MCOLS) + 1` address bits, whereas
`OpenTPU/MxuControlDatapath.lean` reads using `clog2(columns)` bits. An
out-of-range original read can therefore differ from the native wrapped read
on enabled TMEM write data. The native comment describing this truncation as
unpacked-array semantics is not a source-semantics proof. An arbitrary-state
witness would still need initialized reachability analysis; the documented
RMAX command bound is not an assumption of the current unrestricted queries.
For the archived `ROWS=MCOLS=4`, `LANES=8` specialization, the RTL's
`M <= ROWS` check is a simulation-only `$fatal` under `ifndef SYNTHESIS`;
accepted command fields are not clamped or rejected by hardware. A future
reachability proof must establish the actual per-lane property
`mx_go && mxm[k] -> unsigned(MW'(mx_i+k)) < MCOLS` through command, queue and
drain transitions, rather than treating that assertion as an input constraint.
The first complete-observation definedness run at
`build/sparkle/mxu-outer-observation-definedness-first/summary.json` terminates
with a counterexample after proving 120 partitions covering [0,1920).
The next partition includes `ram0_RD_CLK`, a literal `X` on both sides.
This disproves blanket pin definedness, not an initialized TMEM-write mismatch;
the asynchronous RAM consumer's treatment of the clock pin must be qualified
separately. Fourteen guards and seven actual-solver semantic regressions pass.
The run takes 35.99 seconds, peaks at 2.15 GiB, and records no limit or OOM
events. Strict equality uses `-prove equal 1`: review rejected an earlier,
unexecuted `-set equal 0` query because it could exclude undefined outputs.
Full definedness/equality and initialized reachability remain unproved.
The continuation at
`build/sparkle/mxu-outer-observation-diagnostic-ledger-first/summary.json`
requalifies those results and completes all 365 intervals over 5,829 coordinates:
340 intervals prove definedness and 25 contain concrete unknown-value witnesses.
Decoded witnesses identify all eight asynchronous RAM read-clock pins on both
sides and 175 original `t_wdata` bit occurrences. These witnesses do not
enumerate every possible unknown assignment or establish initialized reachability.
A separately authenticated discrete RAM consumer law confirms read-clock
non-influence for the exact asynchronous modes and reset constants; all clock
`X` occurrences remain in the ledger. Enabled-write effects need a targeted
query relating the actual write enable to its data. Fourteen guards pass after
correcting two test exception-type expectations. The run takes 60.47 seconds,
peaks at 1.36 GiB, and records no limit or OOM events. Full definedness, strict
equality and whole-controller refinement remain unproved.
The targeted lane-0 query at
`build/sparkle/mxu-outer-enabled-write-first/summary.json` finds an enabled
undefined-data event: both actual write enables are one, the original
`mk4_address` is 4 and its read/data are all `X`, while native write data is
defined `0xFFFFFFFF`. Native enable/data were observed, not constrained.
The query retains all address bits and actual cone roots. This confirms an
arbitrary-state enabled boundary difference, not initialized reachability or
a proof that conservative read ancestry alone establishes causality. Ten
guards pass. The run takes 34.54 seconds, peaks at 3 GiB, and records 12,214
reclaims with no OOMs or kills. Initialized reachability and any coherent
directional trace refinement through memory consumers remain pending.
The initialized alignment check at
`build/sparkle/mxu-outer-initialized-hazard-second/summary.json` then proves that
the native `mx_i` low three bits start at zero and remain zero under the actual
next-state logic. Under the explicit coupled Boolean-state relation, the full
original lane-0 address is zero, excluding the captured lane-0/address-4 witness.
Its startup statement is existential on the original side: each defined native
startup has a compatible original startup, not every unspecified original startup
being aligned. The proof uses no mandatory reset or in-range assumption and its
query roots exclude child returns. Twelve guards pass, including an actual
next-state driver fault. The run takes 41.83 seconds, peaks at 3 GiB, and records
9,300 reclaims with no OOMs or kills. Lane-4 safety, closed whole-MXU reachability,
source event semantics and production applicability remain unproved.
The lane-4 sequential dependency audit then passes at
`build/sparkle/mxu-outer-lane4-sequential-inventory-second/summary.json`. Its
conservative whole-cell closure contains 14,601 cells, 6,060 physical-state
roots and 513 child-return bits (`lv2`, `rowr` and three RAM read ports), with
eight candidate original reads in the data ancestry. These are conservative
dependencies, not a proof that each is necessary. All 7,436 physical Q/D
coordinates per side are retained in the underlying mapping; direct RAM-return
D wires are joined to existing paired inputs rather than omitted. Seventeen
guards pass. The audit takes 29.75 seconds, peaks at 2.05 GiB, and records no
limit or OOM events. A precise dependency refinement or explicit child-state
composition is needed before a closed initialized lane-4 trace claim; no address
hazard or data effect has yet been proved reachable. The first incomplete
mapping attempt and its exact missing-D diagnostic remain preserved.
The subsequent mux-coordinate refinement passes at
`build/sparkle/mxu-outer-lane4-bit-closure-first/summary.json`. Following each
demanded mux output bit while retaining both arms and its selector reduces the
closure to 1,154 cells, 353 physical-state roots, one candidate original read
and one child-return bit, `lv2`. Exact cell/root/state subset checks link both
data ancestry and sequential closure to the earlier inventory. Every other
primitive retains all input dependencies; no path, reset or command restriction
is assumed. Eleven guards pass. The run takes 34.78 seconds, peaks at 3 GiB,
and records 13,363 reclaims with no OOMs or kills. Closing the actual `lv2`
producer and proving an initialized trace remain separate obligations.

The streaming VPU lane/composite proof has a completed extraction stage at
production configuration 8/2/true:
`build/sparkle/vpu-streamlane-stage-third/summary.json` (305 inputs, 5.93 seconds,
223 MiB peak, no limit events). It authenticates the archived historical reference
recipe, reproduces its old wrapper exactly, compares complete fresh module bodies
and directives, and preserves the full hierarchy with streaming owner inventories.
Raw historical lanes and annotated production lanes are checked separately;
annotated-versus-raw graph correspondence remains a later obligation. Twelve
stage guards pass. Earlier live-helper drift and Slang path-quoting failures are
preserved. This is extraction only: initialization, combined-parent equality,
concrete FP composition, initialized decoder applicability and missing composite
simulation diagnostics remain unproved. Later stages can consume the preserved
hierarchy without repeating extraction.
The next state/init audit also passes:
`build/sparkle/vpu-streamlane-parent-first/summary.json` (353 inputs, 20.42 seconds,
1.84 GiB peak, no limit events; 16 guards). It consumes the preserved hierarchy,
keeps the composite concrete, audits all 24 FP interfaces, and confirms the full
18,982-bit parent Q/D and initializer mapping with no unaccounted state. Concrete
FP circuits are preserved separately before abstraction. This is a structural
and initialization audit only; FP relations/Moore properties, strict parent
definedness/equality, decoder applicability and annotated production graph
correspondence remain pending.
The first paired parent-cone attempt is preserved at
`build/sparkle/vpu-streamlane-parent-cones-first/summary.json`. It exposes the full
24,427-bit obligation vector but stops before SAT because the global driver audit
finds undriven bit 430409 (16.38 seconds, 938 MiB peak, no limit events).
Its checker guards pass (13 tests and 10 subtests). Source/abstraction provenance
for that bit must be resolved without adding a defined-input assumption; no
parent transition equivalence is established by this attempt.
The read-only trace in `build/sparkle/vpu_streamlane_undriven_diagnostic/trace.log`
identifies bit 430409 as undriven reference `memory_map` padding in a 105-bit
`uco` read mux. Exact mux-coordinate fanout reaches no checked obligation;
whole-cell fanout overestimates that dependency. The reference graph contains
30,615 consumed undriven wire IDs, so this one-bit diagnosis is insufficient to
permit a general exemption. The complete audit at
`build/sparkle/vpu_streamlane_undriven_diagnostic/union/summary.json` confirms that
all missing wires already exist undriven in the original parent, but their
mux-coordinate fanout can reach 15,433 obligations. It validates all 83,679
reference and 1,604 native mux schemas (6.07 seconds, 76 MiB peak, no limit
events). No blanket irrelevance exemption is justified. The next checker must
preserve the undriven internal semantics and prove definedness, without new
defined inputs or zero substitutions.
The actual solver semantics checks now pass at
`build/sparkle/vpu-streamlane-undriven-semantics-first/summary.json`: six queries
cover observed undefined wires, masked branches, same-wire alias identity, and
both primary-input values (0.32 seconds, 72 MiB peak, no limit events).
The updated parent checker also passes 21 guards and 17 subtests. It independently
matches all missing-wire identities to original parent uses/aliases without
drivers or initializers, then preserves them as internal wires. These checks do
not alone establish the complete parent theorem. The subsequent complete run at
`build/sparkle/vpu-streamlane-parent-cones-second/summary.json` passes all 24,427
definedness/equality obligations in 773 partitions (469.58 seconds, 1.78 GiB peak,
no limit events). It preserves the original undriven internal wires without new
constraints and covers 18,982 parent state bits. The receipt SHA-256 is
`cfd649c79bbb8370f4177a41fae5c5a51fbd823be328cad66522980f1ecec054`.
The subsequent concrete FP composition passes at
`build/sparkle/vpu-streamlane-fp-product-second/summary.json`: all 24 actual units
(16 mul2, eight add4) pass complete definedness, initialization, output and
transition checks, with actual Moore-output and acyclic transition-graph audits.
All 1,546 parent properties are reauthenticated. The local initialized product
covers 22,510 retained state bits (18,982 parent plus 3,528 FP); 96 leaf queries
pass across 7,679 authenticated inputs (79.44 seconds, 476 MiB peak, no limit
events; seven checker guards). Receipt SHA-256:
`4e749057b648372993947a366456c0c7090fcbeab3099f98828bb29a26f00dc8`.
The first attempt was cleanly interrupted during repeated receipt-index
normalization and archived as incomplete; indexing each authenticated receipt
once fixes that bookkeeping cost without changing obligations or final hashes.
This remains a local normalized-reference result: external composite arithmetic
inputs stay arbitrary shared inputs. Actual hardware mutation controls, original
unique-case decoder applicability, and annotated production graph applicability
were left pending by that receipt. The decoder premise is now bound as described
below; this does not establish whole-VPU equivalence.

The conditional original-versus-normalized case fragment lemma now passes at
`build/sparkle/vpu-unique-case-fragment-third/summary.json` (376 inputs, 2.76
seconds, 79 MiB peak, no limit events; seven guards). Under the explicit
`onehot0(decoded[27:8])` premise, all 160 outputs agree and all 320 observed
bits are defined. Two actual source mutations remain defined and produce
strict-equivalence counterexamples. The actual original negative-zero constant
is retained; only scope metadata is suppressed during flattening. The first
two extraction failures remain archived as incomplete. The subsequent exact
use-site binding passes at `build/sparkle/vpu-decoder-use-site-first/summary.json`
(5,063 inputs, 154.56 seconds, 3 GiB peak, 89,392 reclaims, no OOM; five guards).
It binds the initialized 143-bit decoder (m0=0, m0d=257) to the complete ordered
25-pin lane instance in Gen1, Gen2 and CLI, with full parent/child module,
attribute, directive and assembly-lineage checks. Thus the one-hot premise holds
at the actual lane inputs from startup, without a sampled reset or a new traffic
restriction. Raw-to-annotated lane implementation correspondence now passes at
`build/sparkle/vpu-lane-annotation-second/summary.json` (11,958 inputs, 227.25
seconds, 3 GiB peak, 72,501 reclaims, no OOMs or kills; six guard tests). It permits
only the exact two register hints on the initialized 33-bit metadata register,
checks complete pre-clean graph identity including all 1,255 local lane state
bits and every initializer, and joins the 22,510-bit initialized component to
Gen1, Gen2 and CLI lane/FP definitions and the installed composite diagnostic
bridge. The first attempt remains incomplete after a direct-versus-transitive
receipt lookup failure; the corrected explicit assembly receipt join rejects
changed paths, hashes and cases. External composite arithmetic closure,
remaining VPU state and production hardware mutation controls remain separate
obligations; physical mapping and four-state diagnostic equivalence are not
claimed.

The isolated composite diagnostic candidate also passes qualification at 8/21/3/2
with EXT enabled: `build/sparkle/se-composite-diagnostic-candidate-second/summary.json`
(651 inputs, 34.26 seconds, 2.10 GiB peak, no limit events; 43 checker guards).
The checker binds 486 containing state bits and 349 diagnostic support bits to the
completed parent inventory, compiles the Lean helper, and proves definedness and
strict equality of all 648 source/native observer bits with arbitrary defined
inputs. Explicit ROM mapping leaves 3,031 combinational cells, no state, memories
or initializer constraints. The complete preclean SYNTHESIS graphs match, and
34 actual-core diagnostic/SYNTHESIS simulation fixtures pass. These forced-state
fixtures do not establish legal-traffic reachability. The first unsupported-ROM
attempt remains preserved. That receipt is a candidate-only result; installation
is qualified separately below. Four-state/event qualification and production
assembly/runtime binding remain pending.
Three actual compiled Lean mutation controls now pass at
`build/sparkle/se-composite-diagnostic-mutations-first/summary.json` (52.65 seconds,
3 GiB peak, 497 limit reclaims, no OOM; 18 guards). Each mutant changes exactly
one emitted observer instruction, keeps all 648 observed bits defined, and
produces the expected strict-equivalence counterexample: collision enable gating
removed, return threshold changed from `>=` to `>`, or one stage-zero ROM bit
flipped. Only the ROM negative-witness search selects an address; the positive
theorem remains unrestricted. These controls qualify checker sensitivity and do
not themselves apply the candidate to production.
The exact reviewed core/ABI change is now installed. The compiled installation
bridge passes at
`build/sparkle/se-composite-installation-installed-first/summary.json` (13.27 seconds,
444 MiB peak, no limit events; 17 guards). The preceding compiled ABI baseline
also passes (6.17 seconds, 559 MiB peak). Installed core emission is identical to
the qualified candidate, the ABI changes only by removing the checked legacy
observer block, and the reached production module and directive context match.
This restores diagnostics on the native-core production path. Complete Gen1,
Gen2 and CLI assembly correspondence now passes at
`build/sparkle/se-composite-assemblies-first/summary.json` (4,971 authenticated
inputs, 172.26 seconds, 3 GiB peak, 71,535 limit reclaims, no OOM; 21 guards).
All remaining assembly tokens, module attributes, directives, complete parameter
vectors and ordered support units match after removing only the qualified
diagnostic blocks for comparison. CLI emission also matches the generated bundle.
This is source correspondence, not fresh whole-design elaboration or physical
signoff. The fresh composite runtime suite now passes after this installation:
`build/sparkle/runtime_refresh/top-vops-composites-composite-core-first/summary.json`
records all seven exact cases passing, including lanes 4/8/16 and overlapping
small composites. All seven simulator build events are authenticated (four cache
hits); captured core/ABI hashes match the installed diagnostic bridge, with no
changed sources, tools or dependencies. The complete run took 454.01 seconds,
reached the 3 GiB cap with 2,200 reclaims, and had no OOMs or kills. The fresh
STREAM descriptor suite also passes all three exact cases at
`build/sparkle/runtime_refresh/top-stream-descriptors-composite-core-first/summary.json`
(618.69 seconds, 3 GiB peak, 3,708 reclaims, no OOMs or kills). Its authenticated
simulator audit, unchanged inputs/tools/dependencies and captured installed
core/ABI hashes pass the acceptance audit. Mixed STREAM programs also pass all
four exact cases at
`build/sparkle/runtime_refresh/top-stream-mixed-programs-composite-core-first/summary.json`
(283.82 seconds, 3 GiB peak, 3,523 reclaims, no OOMs or kills), with the same
provenance and simulator acceptance checks. DSTEP also passes all three exact
cases at
`build/sparkle/runtime_refresh/top-dstep-programs-composite-core-first/summary.json`
(172.99 seconds, 3 GiB peak, 4,262 reclaims, no OOMs or kills), including the same
acceptance checks. All five direct VOP cases also pass at
`build/sparkle/runtime_refresh/top-vops-direct-composite-core-first/summary.json`
(109.78 seconds, 1.64 GiB peak, no limit events), with matching installed source
hashes and complete simulator/provenance audits. The Qwen3 INT8 checkpoint also
passes at
`build/sparkle/runtime_refresh/checkpoint-qwen3-int8-composite-core-first/summary.json`
(682.27 seconds overall, 3 GiB peak, 11,412 reclaims, no OOMs or kills). Its
original bit-exact output/DRAM test passes, and the acceptance audit verifies
unchanged checkpoint files, dependencies, sources and tools plus the installed
core/ABI hashes. Qwen3 FP4 with an INT8 head also passes at
`build/sparkle/runtime_refresh/checkpoint-qwen3-fp4-int8-composite-core-first/summary.json`
(657.84 seconds overall, 3 GiB peak, 20,201 reclaims, no OOMs or kills), including
the same bit-exact test and checkpoint/dependency/source/simulator acceptance
checks. Qwen3 FP4 PAIR also passes at
`build/sparkle/runtime_refresh/checkpoint-qwen3-fp4-pair-composite-core-first/summary.json`
(350.48 seconds overall, 3 GiB peak, 4,689 reclaims, no OOMs or kills), with the
same complete acceptance checks. LFM2 INT8 passes at
`build/sparkle/runtime_refresh/checkpoint-lfm2-int8-composite-core-first/summary.json`
(749.65 seconds overall, 3 GiB peak, 8,133 reclaims, no OOMs or kills), including
the original bit-exact test and complete simulator/source/dependency/checkpoint
acceptance checks. LFM2 FP4 with an INT8 head also passes at
`build/sparkle/runtime_refresh/checkpoint-lfm2-fp4-int8-composite-core-first/summary.json`
(548.94 seconds overall, 3 GiB peak, 920 reclaims, no OOMs or kills), with all
checkpoint/dependency/source/simulator acceptance checks and installed core/ABI
hashes verified. The resident LFM2 FP4/INT8-head case also passes at
`build/sparkle/runtime_refresh/checkpoint-lfm2-fp4-int8-resident-composite-core-first/summary.json`
(827.71 seconds overall, 3 GiB peak, 22,398 reclaims, no OOMs or kills), including
the original bit-exact RTL/ISA and resident/per-position comparisons and the
complete checkpoint/dependency/source/simulator acceptance audit. Qwen3.5 without
DSTEP also passes at
`build/sparkle/runtime_refresh/checkpoint-qwen35-vop-composite-core-first/summary.json`
(1,445.35 seconds overall, 3 GiB peak, 24,317 reclaims, no OOMs or kills),
including the original bit-exact test, exact JUnit case, installed core/ABI hashes
and complete checkpoint/dependency/source/simulator acceptance checks. Qwen3.5
DSTEP also passes at
`build/sparkle/runtime_refresh/checkpoint-qwen35-dstep-composite-core-first/summary.json`
(555.48 seconds overall, 3 GiB peak, 32,624 reclaims, no OOMs or kills), with the
same complete acceptance checks and installed core/ABI hashes. Qwen3 C2 with
board memory also passes at
`build/sparkle/runtime_refresh/checkpoint-qwen3-board-c2-composite-core-first/summary.json`
(514.76 seconds overall, 3 GiB peak, 31,041 reclaims, no OOMs or kills), including
the original exact-logit and used-DRAM comparison and the complete input and
simulator acceptance audit. The matching Qwen3 C4 board-memory case passes at
`build/sparkle/runtime_refresh/checkpoint-qwen3-board-c4-composite-core-first/summary.json`
(535.34 seconds overall, 3 GiB peak, 22,285 reclaims, no OOMs or kills), with
the same complete acceptance checks. LFM2 C2 with board memory also passes at
`build/sparkle/runtime_refresh/checkpoint-lfm2-board-c2-composite-core-first/summary.json`
(203.46 seconds overall, 3 GiB peak, 22,777 reclaims, no OOMs or kills), with
the complete checkpoint acceptance audit. The corresponding LFM2 C4 case passes at
`build/sparkle/runtime_refresh/checkpoint-lfm2-board-c4-composite-core-first/summary.json`
(201.18 seconds overall, 3 GiB peak, 7,255 reclaims, no OOMs or kills), with
the same acceptance checks. Resident LFM2 C2 also passes at
`build/sparkle/runtime_refresh/checkpoint-lfm2-resident-board-c2-composite-core-first/summary.json`
(210.21 seconds overall, 3 GiB peak, 20,551 reclaims, no OOMs or kills), with
the complete acceptance audit. Resident LFM2 C4 also passes at
`build/sparkle/runtime_refresh/checkpoint-lfm2-resident-board-c4-composite-core-first/summary.json`
(211.50 seconds overall, 3 GiB peak, 5,591 reclaims, no OOMs or kills), with
the same acceptance checks. Qwen3.5 C2 board memory also passes at
`build/sparkle/runtime_refresh/checkpoint-qwen35-board-c2-composite-core-first/summary.json`
(495.70 seconds overall, 3 GiB peak, 21,440 reclaims, no OOMs or kills), with
the complete acceptance audit. Qwen3.5 C4 board memory also passes at
`build/sparkle/runtime_refresh/checkpoint-qwen35-board-c4-composite-core-first/summary.json`
(576.88 seconds overall, 3 GiB peak, 21,695 reclaims, no OOMs or kills), with
the complete acceptance audit. Qwen3.5 DSTEP C2 board memory also passes at
`build/sparkle/runtime_refresh/checkpoint-qwen35-dstep-board-c2-composite-core-first/summary.json`
(479.87 seconds overall, 3 GiB peak, 25,507 reclaims, no OOMs or kills), with
the complete acceptance audit. Qwen3.5 DSTEP C4 board memory also passes at
`build/sparkle/runtime_refresh/checkpoint-qwen35-dstep-board-c4-composite-core-first/summary.json`
(492.93 seconds overall, 3 GiB peak, 18,874 reclaims, no OOMs or kills), with
the complete acceptance audit. All 18 current checkpoint refreshes are complete;
the older assertion-enabled results below predate the composite installation.
The combined audit at
`build/sparkle/checkpoint-composite-inventory-first/summary.json` verifies all
18 exact test cases, their installed SE-composite source bindings, and 21,163
unique archived objects. It takes 5.07 seconds, peaks at 1.71 GiB, and records
no limit or OOM events. These remain separate runtime workloads; the combined
audit does not rerun live model weights or establish whole-design equivalence.
This Verilator evidence is
two-state behavioral coverage, not four-state event equivalence.
Other standalone composite configurations and four-state event equivalence are
not qualified by this configuration-specific bridge.

The production SE-tail passes initialized retained-state product refinement at
LANES8/inputLatency7/treeDelay1: all 89,824 retained synthesized bits, comprising
82,820 parent bits (including 76,160 arbitrary shared RAM bits) and 7,004 bits
in 46 concrete floating-point children. The complete parent transition theorem
is authenticated and its state/cut representation reconstructed exactly; all
concrete child initialization, output and transition obligations pass. The
RAM remains arbitrary and shared, rather than initialized to zero. Three actual
compiled output/RAM/enable faults yield counterexamples; 45 guards pass.
Evidence is `build/sparkle/se_tail_product/attempt1/summary.json`, with 992
authenticated inputs (110.19 seconds, 3 GiB peak, 8,570 reclaim events and zero
OOMs/kills). Production consumer binding passes for Gen1, Gen2 and CLI: the
three exact module bodies, attributes and directives match, and every reached
SE-tail/FP specialization is joined to its authenticated binding. Evidence is
`build/sparkle/se-tail-product-consumer-binding-first/qualification.json`;
61 guards pass. Binding took 101.57 seconds, reached the 3 GiB cap with 41,243
reclaim events, and recorded zero OOMs/kills. The four source `dq_n` diagnostic
bits and FIFO assertion parity are separate obligations; this is not a
whole-VPU initialization theorem. A separate diagnostic extension now proves
the four actual counter bits and two-state sampled FIFO assertion predicates,
bringing source-state bookkeeping to 89,828 bits. Actual pre-clean counter Q/D
and output cones are projected at 282 authenticated parent state bits. Identity
buffers are checked explicitly. Source X branches are preserved: an undef-enabled
SAT query proves that none can make either side's outputs or next-state bits
undefined for arbitrary two-state inputs, before strict equality is checked.
Actual D-bit inversion and D-to-X mutations produce counterexamples; changing
only the native initializer correctly admits a different existential reference
witness. Evidence is `build/sparkle/se-tail-diagnostic-sixth/summary.json`;
52 guards pass. The check took 11.91 seconds, used 1.42 GiB peak and recorded no
limit events. Earlier endpoint-buffer and X-rejection failures are preserved.
The historical standalone `SeTailABI` wrapper contains the FIFO assertion, but
the production VPU directly instantiates the core and does not inherit it.
The current Lean emitter now places the simulation-only assertion in the core
and removes the duplicate ABI assertion. Its independent emission bridge now
passes: complete native bodies/attributes/directives differ only by those exact
assertion edits, and all 47 independently extracted pre-clean synthesis modules
match, including every state, memory and initializer field. Ten focused simulator
cases check real underflow/overflow fatal messages, init-active failures,
reset/enable suppression and safe cases. The fixture explicitly forces only
diagnostic operands; it does not establish legal-traffic reachability.
Evidence is `build/sparkle/se-tail-assertion-emission-fifth/summary.json`
(1,206 inputs, 18.27 seconds, 861 MiB peak, no limit events); 41 emission guards
pass. Earlier archive/live-object, specialized-module inventory, simulator exit
and packed-string padding failures are preserved. Regenerated Gen1, Gen2 and CLI
assemblies now pass complete token/attribute/directive correspondence after only
the exact assertion relocation, including the production ternary line wrapping.
The bridge preserves historical synthesis reachability under the same parameters,
ordered support sources and SYNTHESIS/YOSYS defines: 95/99/99 module definitions,
764/779/779 reached paths and 536 terminals per assembly. This is source
correspondence, not fresh whole-design elaboration or runtime qualification.
Evidence is `build/sparkle/se-tail-assertion-assemblies-third/summary.json`
(4,603 inputs, 187.38 seconds, 3 GiB peak, 61,267 limit reclaims, no OOM);
36 guards pass. The strict line-format rejection and a malformed receipt-hash
invocation are preserved. Fresh STREAM descriptor runtime qualification passes
all three original cases (default and two board seeds), with exact JUnit case
inventory, audited simulators, and unchanged sources/tools/dependencies:
`build/sparkle/runtime_refresh/top-stream-descriptors-core-assertion-first/summary.json`.
The run took 562.96 seconds, reached the 3 GiB cap with 7,826 limit reclaims and
no OOM. The four mixed STREAM programs also pass with the same exact-case,
simulator and unchanged-input audits:
`build/sparkle/runtime_refresh/top-stream-mixed-core-assertion-first/summary.json`
(230.94 seconds, 3 GiB peak, 1,176 limit reclaims, no OOM).
The seven composite-VOP cases also pass, covering 4/8/16 lanes and the two
many-small-composite programs, with complete simulator and unchanged-input audits:
`build/sparkle/runtime_refresh/top-vops-composites-core-assertion-first/summary.json`
(634.46 seconds, 3 GiB peak, 19,573 limit reclaims, no OOM).
The three unchanged DSTEP integration cases also pass with the current core
assertion at
`build/sparkle/runtime_refresh/top-dstep-programs-core-assertion-first/summary.json`
(139.30 seconds, 2.35 GiB peak, no limit events). Exact JUnit inventory is three
tests with zero failures/errors/skips; all three simulator manifests are verified,
and source/tool inventories remain unchanged. This is native-Top simulation,
not physical board execution.
This qualifies these four suites only; the other runtime/checkpoint suites still
need current assertion-enabled evidence. Historical receipts remain
unchanged; four-state simulation and full event-ordering equivalence are outside
the sampled predicate and focused simulator checks.

The eight-lane VPU max unit passes initialized two-state observed refinement:
all 757 native state bits are related to original state, and all 177 additional
original Q bits are independently excluded from every output and retained
next-state cone. Original initialization is unconstrained; the actual native
initializers supply an existential matching reference witness. The complete
historical transition graph is reconstructed exactly, and new undef-enabled
SAT checks prove definedness and ordinary equality for all 1,866 output/next-state
bits across both sides under arbitrary two-state inputs and current mapped state.
This resolves source X branches without assuming output definedness or pipeline
fill. Actual output, hold and D-to-X faults yield counterexamples; an initializer
change is correctly detected as a changed witness rather than a semantic failure.
Evidence is `build/sparkle/vpu-max-initial-third/summary.json` (229 inputs,
12.28 seconds, 1.04 GiB peak, no limit events); 46 guards pass. Earlier live-tool
hash and structural-totality failures are preserved. Exact production max binding
now passes for Gen1, Gen2 and CLI. Fresh current `VpuDatapath.toVerilog` emission
at 8/2/true matches the proven standalone 8/1/false max module's entire body,
attributes and directive context, and each actual reached historical instance is
checked independently. Evidence is
`build/sparkle/vpu-max-initial-consumer-binding-first/qualification.json`;
53 consumer guards pass. Binding took 99.37 seconds, reached the 3 GiB cap with
79,438 reclaim events and recorded zero OOMs/kills. This qualifies the max module,
not the complete current assembly after other module changes. Whole-VPU
composition remains pending; independent initial states, four-state inputs and
physical power-up are outside this theorem's scope.

The production VTree also passes initialized product refinement at LANES8/LA4:
all 3,646 state bits (1,704 local plus nine concrete adders and one duplicated-
output adder). Initialization, immediate output agreement and one-step
preservation pass with unrestricted traffic, resets and stalls, including
colliding schedules. The collision diagnostic is checked against authenticated
original RTL predicates; this preserves synthesized behavior without claiming
that colliding schedules compute valid mathematical reductions. All four
output/hold/reset/diagnostic mutations yield counterexamples; 33 guards pass.
Evidence is `build/sparkle/vtree_product/attempt2/summary.json` (41.42 seconds,
760 MiB peak, no limit events). The first hierarchy-extraction failure and
initial mistargeted guard mutation are preserved. Production consumer binding
now passes for Gen1, Gen2 and CLI: exact module bodies, attributes, directives,
the VTree and all ten reached adders, and the original diagnostic predicates
match the authenticated theorem. Evidence is
`build/sparkle/vtree-product-consumer-binding-first/qualification.json`;
50 guards pass. Binding took 92.67 seconds, reached the 3 GiB cap with 48,687
reclaim events, and recorded zero OOMs/kills. Whole-VPU initialization
composition remains pending.

The subsequent Qwen3 INT8 checkpoint test reported one pass in 484.57 seconds,
with the exact expected JUnit case and no skips. An environment restart removed
the live session and temporary dependency environment before the qualifier's
final audits were published, so this attempt remains incomplete and is excluded
from the qualified checkpoint count. Its original files are preserved under
`build/sparkle/runtime_refresh/checkpoint-qwen3-int8-audited-first/`; the separate
`interruption.json` authenticates the retained evidence without upgrading it.

The complete native quantizer adds 300,000 cycle comparisons across
`(D,LANES)=(32,4),(32,8),(96,8),(128,16),(4,4)`. These exercise streaming and
row-mode QACT, column/row factors, duplicate rows, QST narrow/wide writes, HALF,
empty commands, reset, grant stalls, and delayed write acknowledgement. Active
memory writes, read addresses, completion and profiling are compared to the RTL.
The controller/storage proof exposes every retained control register and every
buffer RAM cell from arbitrary equal current state. It checks all outputs and
all inputs to the three pipeline boundaries, whose arbitrary outputs are shared
between implementations. Separate pipeline proofs discharge those boundaries;
the production audit verifies that every embedded module matches its proven
circuit. Completion and buffer-write mutations must produce SAT counterexamples.
Evidence is under `build/sparkle/formal_quant/`; no reachable-state assumptions
are used in the controller proof. These historical arithmetic proofs retain
their enabled-fill scope. The D128/LANES8 initialized product theorem above
separately closes initialization composition for that exact configuration.

At `D=128, LANES=8`, complete-quantizer Kintex-7 synthesis passes the
resource-count gate: 6,761 native LUTs versus 6,865 reference LUTs, 5,734 versus
5,738 flip-flops, and 111 versus 113 distributed-RAM cells. Both use 65 DSP48s
and 517 shift-register cells, with no block RAM. Buffer metadata remains native
memory to preserve RAM inference. The first Newton-operand delay's unreset sign
stages initialize to their constant one value (permitted by the reference's
unspecified initial state); its resettable endpoint still clears to zero. This
removes an otherwise unnecessary shift register. These are synthesis counts,
not placement or timing qualification. Evidence is in `build/sparkle/quant_synthesis/`.

The byte-bank lowering checks compare Sparkle's ordinary emitter with the packed
emitter, starting from equal but otherwise arbitrary RAM contents. They check every
storage cell, register and output by induction, for a 40-bank fixture (including
the 32-byte grouping boundary, differing addresses and a singleton) and ACT RAM at
`D=8, MCOLS=2, ROWS=4, BLOCKS=4, LANES=1`. A checker self-test disables one byte
write and requires proof failure. This verifies the lowering on those fixtures;
the separate ACT RAM controller proof now compares the production circuit directly
with the original RTL for `(D,MCOLS,ROWS,BLOCKS,LANES)` configurations
`(8,1,1,4,1)`, `(32,2,4,2,8)`, `(32,3,3,2,8)` and `(96,2,2,2,8)`.
It checks all 689, 3,485, 3,199 and 5,995 retained state bits respectively, plus
hardware outputs, from corresponding arbitrary states with unrestricted inputs.
An output mutation must fail. The extra native hazard diagnostic is outside this
hardware equivalence scope because the reference expresses it as a simulation assertion.

The production-size ACT proof in `tools/prove_sparkle_actram_ports.py` also passes
at `(128,4,4,128,8)`: it checks all 5,865 non-memory state bits and every pin of
20 matched RAM primitives representing 540,672 stored bits. Identical RAM
semantics, explicit byte-order correspondence and checked writes preserve equal
contents without expanding every stored bit into the solver. Inputs are
unrestricted; no alignment or traffic assumptions are added. RAM-write and
read-output mutations both fail as expected. `make prove-sparkle` includes this
proof and its negative controls; evidence is under `build/sparkle/formal_actram_ports/`.
The Board-default `(128,2,2,128,8)` configuration also passes the same complete
check: 3,679 non-memory state bits and 10 RAM primitives holding 270,336 bits.
The small native-Board `(128,2,2,4,4)` configuration now also passes its complete
saved proof: all 3,542 state bits, 90 RAM-input groups, ten RAM primitives holding
8,448 bits, and 9,988 checked output bits. The bounded replay proves all 6,966
equivalence cells with none unproven, and a fresh current ACT emission matches
the proven native artifact byte-for-byte. It completed under the 3 GiB ceiling
without OOM events. Replay and current-source binding evidence are under
`build/sparkle/formal_actram_ports/128_2_2_4_4/proof/replays/20261011T012045Z-618a26f93ff0/`;
the earlier interrupted attempt remains preserved.
The current ACT composition audit also passes all three configurations: fresh
standalone emissions are byte-identical to their proved artifacts, and the ACT
module embedded in the saved small-Board assembly has identical SystemVerilog
tokens and global directive context. The assembly's ternary-expression whitespace
wrapping is permitted; semantic token or directive changes are rejected.
This binds the ACT module only, not the entire current Board. Evidence is in
`build/sparkle/check_actram_composition/summary.json`; the audit used 215 MiB
peak under a 1.5 GiB cap with no memory-limit events.

This proof found and corrected an ACT RAM data-write indexing mismatch outside
the documented lane-aligned input contract: reference data writes beyond the word
boundary are dropped, while enables wrap at their declared index width. Verilator
5.052 incorrectly wraps the reference data writes too. Simulation uses an explicit
bounds guard in a reference copy; the original synthesis RTL remains unchanged.
`tools/check_actram_index_frontends.py` reproduces the discrepancy and proves the
guarded expression equivalent to the original under both Slang and the legacy
Yosys frontend. Seven differential configurations pass 140,000 cycles; startup
clearing and reintroduced data-wrap mutations are rejected. Evidence is under
`build/sparkle/formal_actram/`, `actram_regressions/` and `actram_index_frontends/`.

TMEM induction checks relate every RAM cell and pipeline register to the original
RTL, with requests, grants, addresses and data unrestricted. Both sides start from
equal but otherwise arbitrary memory and pipeline state; native register initializers
are removed for this proof. Three small configurations, explicitly listed in
`tools/prove_sparkle_tmem.py`, cover general/mixed/contiguous routing, shared read
copies, and one or two writes per bank. A checker self-test removes a pending-write
bypass and requires proof failure. Logs and hashes are in `build/sparkle/formal_tmem/`.

The folding-tree proof checks the concrete FP pipelines, controller, routing,
delays, root outputs, valid timing, and schedule-error flags, for the same seven
configurations. Initial arithmetic, controller and delay states are equal but
otherwise arbitrary. Self-tests corrupt root-valid timing and an FP result and
must fail. An optional `--controller-only` mode cuts corresponding FP adder outputs
to equal arbitrary values while checking every operand/enable pair; this isolates
controller/routing failures but does not verify arithmetic at the cut points.
Results and source hashes are in `build/sparkle/formal_vtree/`.

Sequencer checks compare eight combinational stages to the reference: register-relative
decode, unit routing, multiplication operands, partial products, product sums, footprint
ranges, segregated footprints, and conflicts. Inputs are unrestricted and independent
at each stage, including overflowing addresses and unknown opcodes. Configurations
`(D,S)=(32,1),(64,2),(96,3),(128,4)` cover non-power-of-two dimensions as well.
Window-selection checks cover every supported `WIN=2,4,8,16,32`, including completion
masks, dependency insertion, oldest-ready selection, and MXU release. Age matrices
and queue read results are unrestricted inputs; this does not prove queue storage
or that the age matrix remains a total order. Checker self-tests corrupt ranges,
conflicts, and MXU starts and require SAT counterexamples. Logs and input hashes
are under `build/sparkle/formal_seq_logic/` and `build/sparkle/formal_seq_schedule/`.

The four dispatch stages are checked by exposing all 1,746 current-state bits as
shared arbitrary inputs and proving every next-state bit and output equal, with
concrete arithmetic. The checker requires complete coverage of every flip-flop;
it rejects omitted state, unsupported cells, and mismatched clocks. All intermediate
equivalence points must also be proven. This establishes an inductive correspondence
from equal, otherwise arbitrary initial registers, for the same four `(D,S)`
configurations. Reset, dispatch authorization, resolved commands, PCs, unit numbers,
and window availability are unrestricted. Reset and arithmetic mutations must produce
SAT counterexamples. Evidence is in `build/sparkle/formal_seq_dispatch/`.
Separately, 120,000 randomized-startup simulation cycles across three configurations
compare the reference and an independent command FIFO, checking stalls, order, and
commands discarded by resets.

The complete sequencer differential bench covers `(D,S,WIN)=(32,1,2),(64,2,8),
(96,3,16),(128,4,32)`, including randomized startup, stalls, in-flight resets,
all four loop-stack entries, zero-trip loops, RLD, HALT/CHAIN, and invalid opcodes.
It compares control, commands, counters, and qualified trace events every cycle.
`tests/test_sparkle_seq.py` additionally compares original and native sequencers
against the ISA, including exact RTL traces, all DRAM/TMEM words, cycle counts,
and instruction counts, with normal and boot loading and one or two slices.
The native sequencer has also passed both R8–R15 argument tests; selecting all
currently native units passes eight single-slice fuzz cases, twelve scoreboard
stress cases, and ten WAITW cases.

The window-storage checker compares every register, queue entry, command-memory
cell, and output for `WIN=2,4,8,16,32` from equal arbitrary current state. This
includes allocation/completion collisions, command reads and writes, readiness
stamps, and start/release queues. Command-output and dispatch mutations must fail.
The complete-sequencer checker additionally includes instruction memory, fetch,
scalar registers, the loop stack, HALT/CHAIN, counters, and trace registers, at
`(IMEM_WORDS,D,S,WIN)=(16,32,1,2),(32,64,2,4),(64,128,1,4)`.
It assumes the ISA's depth-four loop contract: stack depth is at most four and
a nonzero LOOP cannot push onto a full stack. Separate SAT checks establish that
reset clears the depth and legal entry preserves the bound. Other state and
inputs remain arbitrary. These are exact next-state/output comparisons from
equal initial states, with concrete arithmetic and complete state coverage;
they do not establish equivalence from independently chosen initial memories.
Evidence is under `build/sparkle/formal_seq_window/` and `formal_seq/`.

The native DMA has passed 22 end-to-end checks against the ISA simulator and
expected timeout behavior: LD/ST alignment and buffer wrapping, memory
backpressure, WAITW polling, DSTEP, and STREAM. Run them with
`make test-sparkle-dma`; the captured run is in
`build/sparkle/dma-integration.log`.
`make test-sparkle-integration` selects all currently ported components together
for 18 single/two-slice fuzz, design-size, STREAM, and WAITW checks. Both targets
are included in `make test-sparkle`. All 18 combined checks pass; the captured
run after optimizing DMA initialization is in `build/sparkle/all-native-integration-fill.log`,
with a source snapshot in `build/sparkle/all_native_integration_fill_summary.json`.

`tools/prove_sparkle_dma.py` exposes all retained controller and RAM state and
compares every next-state bit and output from equal arbitrary state. It assumes
no bounds on controller state or external inputs. Yosys `-undef` treats undefined
reference behavior (such as an out-of-range part-select) as unconstrained; this
is not a claim that independently chosen `X` values match. The five configurations
below pass after the fill-table initialization optimization, and deliberate completion and buffer-write mutations produce SAT
counterexamples. Evidence is under `build/sparkle/formal_dma/`.

| D | LANES | DEPTH | HAS_DSTEP | State bits checked |
|---:|---:|---:|---:|---:|
| 32 | 8 | 32 | 1 | 52,872 |
| 128 | 8 | 128 | 1 | 279,664 |
| 32 | 4 | 32 | 0 | 52,310 |
| 32 | 16 | 64 | 0 | 61,841 |
| 4 | 1 | 32 | 0 | 15,309 |

At `D=128, LANES=8, DEPTH=128, HAS_DSTEP=1`, DMA out-of-context Kintex-7
synthesis uses 6,230 native LUTs versus 6,238 reference LUTs. Both use 29 RAMB18
blocks, two DSP48 blocks, and 774 distributed-RAM cells. The native implementation
uses 3,561 flip-flops versus 3,584 reference flip-flops, passing the strict resource
gate. The fill-sequencing table starts at a valid configuration, specializing the
reference's unspecified power-up contents; subsequent updates retain their
reference semantics. Evidence is under `build/sparkle/dma_synthesis/`; these
counts do not establish placed area or timing parity.

Both native stream-engine units pass strict out-of-context XC7 resource gates.
The external-arithmetic composite configuration (`LANES=8, MW=21, NS=3, HA=2`)
uses 6,597 LUTs versus 6,651 reference, with equal 2,010 flip-flops and 2,218
shift-register cells. Its unreset control registers start at a valid identity
operation, a legal specialization of the reference's unspecified initial state;
this removes four otherwise unnecessary flops. The tail (`LANES=8, TA=7, QD=1`)
uses 12,997 LUTs versus 13,021 and 8,680 flip-flops versus 8,684. Both tails use
eight RAMB18 equivalents, 52 DSPs, 246 distributed-RAM cells, and 590 shift-register
cells. These are resource counts, not placement/timing results. Evidence is under
`build/sparkle/se_composite_synthesis/` and `build/sparkle/se_tail_synthesis/`.

The physical-emission check inspects Yosys's parsed attributes on 343 register
declarations and 47 memories across fourteen representative cases. It also verifies that the current
TMEM/tree/sequencer/conversion/quantizer/DMA/composite functional Verilog tokens match their proven versions after
removing comments and attributes. Original proof-input hashes are verified;
historical generator sources can be retained by hash under
`build/sparkle/proof_inputs/` when only the production emitter changes. The
current generated circuit must still match the proven circuit's functional tokens.
Its evidence is under `build/sparkle/physical/`. This checks attribute preservation,
not whether placement meets the target clock.

**The full-parity goal remains open.** The simulator now selects native DRAM
interfaces and the complete native VPU and behavioral MXU with `all`; all 28
combined regression cases pass, recorded in
`build/sparkle/all-native-with-mxu-summary.json`. The physical DSP variant remains separately
qualified for behavior. Its default-size resource comparison now passes under a
shared flow preserving explicit DSP pipelines (1,151 versus 1,160 LUTs, equal
3,221 flip-flops, 288 DSPs and 2,725 shift registers); selective integration of that
flow into the full board remains open, and prior default-flow failures are retained.
The selective flow also passes a mixed physical-dot plus independent FP32
multiplier benchmark: default geometry uses 1,258 native versus 1,260 reference
LUTs, with equal 3,285 flip-flops, 290 DSPs, 2,725 shift registers and 15 carry
cells. It preserves all 288 explicit MXU DSP configurations while inferring two
DSPs for the unrelated multiplier; mapped simulation passes 2,048 cycles.
This relies on retaining the FP module hierarchy on both sides and is not a
whole-board placement/timing result. Evidence and the reusable selective flow
are in `build/sparkle/mxu_selective_synthesis/` and
`tools/sparkle_mxu_synthesis.py`. The generator command
`mxu-physical D MCOLS ROWS FIFO_DEPTH LANES IMPL CL OUTPUT.sv` emits the physical
core and diagnostic ABI (external DSP48E1 primitive/model required); its two
qualified complete-ABI configurations match exactly in
`build/sparkle/mxu_physical_cli/summary.json`.
The current physical Slice/Board assembly checker also passes both configurations
after sequencer promotion: 54 modules for the D=32/four-column Slice and 62 for
the D=128/two-column Board. Non-MXU modules are preserved, complete elaboration
passes, and restoring incompatible behavioral diagnostics is rejected in each
case. The smaller Slice binds its exact physical dot and DSP model to the
existing proof; the initial Board record covers structural/elaboration qualification.
Evidence is in `build/sparkle/check_slice_physical_abi/summary.json`.
Production physical-dot composition now passes for D=128, CL=16 with both four
and two columns. The four-column proof checks 61,323 parent state bits and 516
PE/column-end instances backed by 102,516 concrete DSP-model state bits; all
95,605 parent equivalence cells are proven. The two-column proof checks 35,866
parent bits and 258 instances backed by 45,818 DSP-model state bits; all 52,020
parent equivalence cells are proven. Every helper input, parameter, clock and
enable is checked, with shared arbitrary helper outputs justified by the exact
concrete leaf proofs. Helper module tokens, attributes and incoming macro context
must match those proofs. This is compositional equivalence, not a flat whole-chip
theorem or FPGA physical signoff.
The first production attempt hit the job-local memory ceiling while Python loaded
the reference JSON; its incomplete inputs and evidence remain preserved. The
successful replay adds only combinational `opt_expr` after memory expansion,
reducing the reference graph from about 1.2 GB to 69 MB. Streaming before/after
checks preserve every original DFF, parameter, clock and public current-state
identity. Only the original four-column reference's 2,048 structurally unobserved
weight-array bits are excluded; no native state is dropped. Final four-/two-column
runs complete in 164.7/77.5 seconds under the 3 GiB cap without OOMs. Both actual
helper-input and retained-next-state mutations are rejected in the original and
folded proof paths; 45 contract, state-inventory and assembly-binding guards pass.
Evidence is in `build/sparkle/formal_mxu_physical_composition/128_4_16-folded/`
and `128_2_16-folded/`.
The separate `tools/check_sparkle_physical_proof_binding.py` check now binds those
exact proven modules and the functional DSP model to the current Gen1/Gen2 FPGA
assemblies and the smaller two-column Board assembly, including original replay
input authentication and supplemental historical scanner-dependency evidence.
All three bindings pass in `build/sparkle/physical-proof-binding/summary.json`.
Earlier assembly records reporting missing physical coverage are retained;
the new binding record supplies that coverage without rewriting their history.
The production behavioral dot proof at D=128, four columns, IMPL=2 and CL=16
now passes through the checkpointed replay described below. Its earlier limited-out
attempts remain preserved as incomplete. Streaming compaction preserves all 93,479 retained next-state
bits on each side and the complete hardware graph, reducing the saved JSON from
823,403,461 to 579,032,256 bytes. The subsequent replay reached the 3 GiB job-local
memory limit inside Yosys's JSON frontend, before equivalence checking. This is
neither a passing proof nor a counterexample. Inputs, compaction evidence and
the limited-out replay are preserved in
`build/sparkle/formal_mxu_dot/128_4_2_16/bounded_replay/`. The subsequent streaming
RTLIL transport and checkpointed proof keep the memory ceiling and proof
obligations unchanged.
Small transport-auditor and ACT-composition guard suites pass 68 tests under a
256 MiB cap (52 MiB peak, no memory-limit events). The transport checks include
graph/declaration mutations, authenticated Yosys roundtrips and protection against
reports overwriting inputs through ordinary paths, symlinks or hard links.
These fixture results do not qualify the production conversion or prove the dot.
The production JSON-to-RTLIL conversion now completes under a 512 MiB cap with
no OOM events, retaining 93,479 next-state bits on each side. It emits a
603,900,322-byte RTLIL artifact from the 579,032,256-byte compact JSON. This
changes frontend representation rather than reducing the proof obligations.
Evidence is in `build/sparkle/formal_mxu_dot/128_4_2_16/rtlil_transport/steps.rtlil.json`
with status `converted-not-qualified`. The independent production roundtrip and
graph audit now pass: declared backing-wire arrays stream directly into SQLite,
while ordinary JSON owners retain the 16 MiB bound. The complete audit checks
1,392,620 reference cells, 32,430 native cells, all 30,516/30,513 retained aliases,
17,899 ports on each side, and all 93,479 next-state bits per side. Its authenticated
Yosys roundtrip and independent graph/declaration checks completed under the
3 GiB cap with no OOM events. The separate qualification record is
`build/sparkle/formal_mxu_dot/128_4_2_16/rtlil_transport/qualification/summary.json`
(`transport_qualified`, solver not run). This qualifies the saved graph transport,
not functional equivalence or a fresh current-source circuit.
The subsequent proof replay changes only `read_json` to `read_rtlil`; every
remaining original proof command is preserved. RTLIL loading succeeds, but
`equiv_make` reaches the 3 GiB job limit while constructing the comparison module,
before solving. The journal confirms a cgroup-local OOM kill. The proof remains
incomplete, with its script, inputs, log and termination evidence retained under
`build/sparkle/formal_mxu_dot/128_4_2_16/rtlil_transport/proof/`. Further work must
reduce comparison-construction memory without dropping proof obligations.
An experimental `equiv_make_consume` pass now reuses the reference module instead
of cloning it, with a pinned source transformation that leaves upstream matching,
undriven-net handling, rewiring and equivalence generation unchanged. Eight small
stock/plugin graph and canonical-declaration comparisons pass, including four
positive and four deliberately failing proof cases. Unsupported configurations
are rejected. Evidence is in `build/sparkle/equiv_consume/qualified-small/summary.json`.
The production attempt completes comparison construction and reaches optimization,
but subsequently hits the same 3 GiB job limit in `opt_clean`, before solving.
Its incomplete evidence is under
`build/sparkle/formal_mxu_dot/128_4_2_16/rtlil_transport/proof-consume/`.
The checkpointed replay now succeeds. Construction writes the complete comparison
module, a separate read/write roundtrip verifies byte-identical serialization,
and a fresh process runs every original optimization and solver command in order.
All 93,642 equivalence cells are proven, with zero unproven cells and all 93,479
retained state bits covered. The solver stage completes in 67.9 seconds with a
3,062,452,224-byte peak (2.85 GiB), no memory-limit events and no OOMs. Construction
and verification also complete under the 3 GiB ceiling without OOMs. Evidence is
in `build/sparkle/formal_mxu_dot/128_4_2_16/rtlil_transport/checkpoint-replay/prove.json`
and `prove.log`; the checkpoint driver is `tools/replay_sparkle_mxu_checkpoint.py`.
The expanded checkpoint/promotion suite passes 55 tests under a 256 MiB cap
(64 MiB peak, no memory-limit events). These include four positive and four
deliberately failing real checkpointed proofs, changed-input and record-chain
rejections, incomplete-proof rejection, and changed-current-emission rejection.
`tools/promote_sparkle_mxu_checkpoint.py` now binds a fresh compiled native dot
emission and regenerated reference extraction byte-for-byte to the proven inputs.
The production reuse check passes for D=128 with four columns/IMPL=2 and two
columns/IMPL=0, both with FIFO depth 1024, eight lanes and CL=16. All six component
proofs are reused with regeneration prohibited; the controller RAM write-address
mutation is rejected. The complete behavioral composition audit now covers eight
configurations with zero missing component proofs, checking current emissions,
concrete arithmetic leaves and component wiring. Evidence is in
`build/sparkle/formal_mxu_dot/128_4_2_16/promoted-checkpoint/`,
`build/sparkle/mxu_production_closure/summary.json` and
`build/sparkle/mxu_composition/summary.json`. Promotion and composition complete
in 67.3 seconds under the 3 GiB cap; memory reclaim events occur, but no OOMs.
The reference's 2,048 structurally unobservable register bits remain explicitly
excluded by the original proof setup. Physical DSP composition is discharged
separately by the proofs above; full-design FPGA implementation remains open.
Native composite and tail circuits have passed their scoped proofs,
resource checks and integration tests. The `all` simulation mode replaces core
units while retaining the original top/Slice assembly and some reference helpers.
The newer `top-test` mode uses complete native Top/Slice hardware with the original
testbench, type packages and explicit external memory models. Its `AXI=2` path
now selects the native memory-channel bridge and its native FIFOs. Source-selection
regressions pass for all three memory paths. Alongside the six earlier native-Top
runtime cases, all three `AXI=2` LiteDRAM cases now pass: hazard, random-instruction,
and DMA programs match the ISA simulator's complete DRAM/TMEM outputs at core
clocks slower than, equal to, and faster than the controller. Authenticated inputs
and results are in `build/sparkle/top-ldc-bounded/`; the run completed under the
3 GiB process-tree ceiling without OOM kills. Broader native board
runtime qualification and full-design FPGA area/timing qualification remain outstanding.
The separate `board-test` selection (native control, trace and asynchronous FIFOs
inside the original board/core assembly) passes all 15 observability tests;
authenticated inputs and the terminal log are recorded in
`build/sparkle/board-support-integration-summary.json`. The native memory channel
passes four complete formal configurations and 20 unchanged original bench
scenarios. The `mem-channel XIDW ARD XRD RUN OQ OD OUTPUT.sv` generator command
emits its native core and ABI; all emitted core modules match the qualified
versions in `build/sparkle/mem_channel_cli/summary.json`.
`OTPU_SPARKLE=mem-channel-test` selects this channel in the original board assembly;
`make test-sparkle-mem-channel` passes three integration tests covering a mixed
program, masked read-modify-write and two-run DMA/MXU turnarounds under stalls.
Evidence is in `build/sparkle/mem-channel-board-integration-summary.json`.
The complete `board-native-test` selection also passes all three channel integration
tests, including masked writes and DMA/MXU turnarounds, with source checks excluding
reference Board/Slice/channel fallbacks. Its authenticated inputs, unchanged
simulation-support sources, and terminal results are in
`build/sparkle/board-native-channel-bounded/`. This run completed under the 3 GiB
process-tree ceiling with no OOM kills. It is separate from the earlier interrupted
18-case native-board regression and does not certify that entire suite.

A production-configuration coverage audit identified four formal obligations.
The Trace and Control leaf obligations now pass. Trace at DEPTH/QD/WIN
16384/32/16 checks 4,111 controller bits and all inputs to two exactly matched RAM
primitives, covering 1,089,440 memory bits by induction without expanding them
into registers. Only 20 unmatched, structurally dead native performance-field
bits are excluded; their identities and liveness checks are recorded. Three real
RAM faults are rejected. The production proof took 4.5 seconds and 199 MiB.
Control checks all 2,421 bits at both 100000 and 133333 kHz with the FPGA's C4/R4,
DDR1066, and enabled host features; its read-ready fault is rejected. Its two
positive proofs and negative control completed in 9.4 seconds and 1.52 GiB.
Evidence is in `build/sparkle/formal_trace_ports/production/summary.json` and
`build/sparkle/formal_control_production/summary.json`. The separate binding in
`build/sparkle/board-leaf-proof-binding/summary.json` confirms both proved modules,
including attributes and incoming directive contexts, in the preserved Gen1,
Gen2, and 133333-kHz FPGA bundle artifacts. All these jobs completed without OOM
kills; 81 final proof/result/binding guard tests pass.

Production local parent composition now also passes at C4/L8/FIFO1024 and the
production memory sizes: 1,150 Slice state bits, its ABI and seven child parameter
projections, 92 Board state bits, and all NativeSys wiring. Separate chains cover
Gen1/100000 kHz with unregistered DMA and Gen2 at both 100000 and 133333 kHz with
registered DMA. Three actual faults (Slice error, Board memory flush, and channel
data) are rejected. The run took 72.8 seconds, peaked at 2.19 GiB, and had no memory
limit events. `build/sparkle/production_parent_contracts/summary.json` records each
stage and authenticates the generator sources, linked objects, and proof inputs.
Their exact parent-to-assembly bindings also pass for all three FPGA artifacts:
13 local modules per assembly, including attributes and incoming directive
contexts, plus the typed Slice ABI through the previously authenticated synthesis
wrapper identity. Evidence is in
`build/sparkle/production_parent_assembly_binding/summary.json`; 15 binding guard
tests pass. The binding took 34.5 seconds under a 512 MiB cap, with no OOM kills.
These remain local parent contracts. Gen1's exact unregistered DmaSplit
configuration (DW=128, IDW=4, REG=0) now passes an 87-bit full-state proof with
clock, next-state and initialization audits, plus rejection of an actual
write-address-valid fault. Evidence is in
`build/sparkle/formal_dma_split_gen1_production/summary.json`; the positive and
negative checks took 2.4 seconds and 255 MB, without memory limit events.
Board's Collective now also passes the
exact S=1/LANES=8 base case and unbounded temporal induction (step 4), rejects an
actual acknowledgement fault, and matches all three qualified FPGA assemblies.
Evidence is in `build/sparkle/formal_collective_production-v3/summary.json`.
That run took 53.6 seconds under the 3 GiB cap with no OOM kills; an earlier
512 MiB attempt was killed within its cgroup and remains recorded as incomplete.
NativeDram now also passes at the exact production
D/QD/WQD/CHASH/WGATHER/RD/AD/APF = 128/16/32/1/4/128/64/32. Concrete RAM induction
covers all 36 memories (314,304 bits), including checked read-port ordering.
The parent proof covers all 3,625 remaining state bits, every RAM input and every
primary output: 10,114 equivalence cells pass, with zero state bits pruned.
Reference-defined initialization is preserved; unspecified reference state
permits native initialization. An actual RAM write-address fault is rejected by
the same complete proof. Evidence is authenticated by
`build/sparkle/native_dram_production_proof_8/qualification.json`.
RAM proofs took 4.1 seconds and 84 MB; the parent and fault checks took 29.3 and
31.1 seconds at 428 and 509 MB respectively. Preparation peaked at 1.54 GB,
without OOM. Earlier graph-size and backend guard failures remain incomplete;
the successful continuation reuses byte-identical prepared state and interfaces
with explicit old/new proof-driver provenance. Its exact proof-to-assembly
binding now passes as part of the child audit below.
Fresh immutable-input replays also establish authenticated terminal logs for
production MemChannel, SE-tail (8/7/1), and VTree (8/4), where the older records
omitted log digests. Evidence is in
`build/sparkle/mem_channel_production_local_replay/summary.json` and
`build/sparkle/vpu_production_leaf_log_replay-default/summary.json`.
SE-tail proves all 86,922 equivalence cells; VTree retains its original induction
miter and assumptions. The two VPU replays completed in 135 seconds at 2.818 GiB
with no memory limit events. A preliminary 512 MiB attempt was killed before
qualification and remains incomplete; the workspace ceiling was not increased.
All 33 implementation-child bindings now pass: each of Gen1, Gen2, and the CLI
bundle matches the qualified Seq, TMem, ACT, DMA, MXU, Quant, VPU, DmaSplit,
MemChannel, Collective, and NativeDram implementations. Evidence is in
`build/sparkle/all_child_binding-complete/summary.json`, with no missing child
cases and 48 guard tests passing. The audit authenticates exact module tokens,
parameters and incoming directive contexts. Physical attributes use explicit
insertion-only policies for the named storage/synchronizer/fanout targets; it
does not erase arbitrary attributes. The final run took 62 seconds under a
768 MiB cap, with page-cache reclaim but no OOM events.
This is implementation-child applicability, not exhaustive qualification of
every assembly module. The later joins below add parent/ABI, Control/Trace and
primitive applicability; CDC, actual timing and hardware validation remain
outstanding. The intermediate inventory in
`build/sparkle/hierarchy_coverage_inventory-final/summary.json` accounts for
91 of 95 Gen1 definitions and 95 of 99 Gen2/bundle definitions. At that stage the
same four still required binding in each: `otpu_dma_split`, `otpu_mem_ch`,
`otpu_fpga_top_ld`, and `otpu_fpga_top_ld_sparkle`. Syntactic instance inventories
are recorded separately; they are not an elaborated parameter/reachability proof.
The subsequent shell applicability check supplies both FPGA wrapper/shell
definitions for all three assemblies, including a fresh proof at the exact CLI
133333-kHz configuration. It retains both reset-state bits, independent clocks,
every directed boundary pin and package-pad topology. Four actual reset-clock,
CSR-clock, DMA-address and pad mutations are rejected. The 29-second run reached
the 3 GiB cap with page reclamation and no OOM events; evidence is in
`build/sparkle/fpga-shell-applicability-first/summary.json`.
The remaining DMA-split and memory-channel wrapper checks pass all six assembly
cases. They compare every directed pin and bit position against the original
interface, using Slang AST metadata for signedness, range order and evaluated
parameters that its blackboxed netlist output omits. Actual valid-input inversions
are rejected. All 54 wrapper/shell guards pass; the production ABI run took
111 seconds under the 3 GiB cap with page reclamation and zero OOM events.
Evidence is in `build/sparkle/remaining-abi-v3/summary.json`; earlier unsupported
frontend/dependency/literal attempts remain explicitly incomplete.
The final definition join authenticates these records together with the existing
child, parent, Control/Trace and physical-DSP bindings. All 95 Gen1 definitions
and all 99 Gen2/CLI definitions have applicability records; none remain uncovered.
`build/sparkle/module-coverage-joined-first/summary.json` records this result as
`module_definitions_bound_scope_incomplete`: inherited proof assumptions, external
vendor behavior, elaborated parameter/reachability, CDC and FPGA signoff remain
explicitly outside that conclusion. The join took 118 seconds under a 768 MiB
cap with page reclamation and no OOM events.
The elaborated hierarchy auditor now has 39 passing guards, including evaluated
parameter defaults, inferred parameter types, typedef resolution and packed-struct
ports. The production CLI bundle's full reachable-instance traversal now passes;
the independent Gen1 and Gen2 API traversals also pass.
`build/sparkle/dsp-occurrence-projection-first/summary.json` supplies the missing
pre-flatten DSP contracts: eight qualified PE helpers and the production 23-bit
column-end helper yield twelve occurrence profiles. Each projection retains exact
parameters and pins and is linked to its existing concrete physical proof. All
16 projection guards pass. The 44-second extraction reached the 3 GiB cap with
page reclamation and no OOM events; it adds no vendor behavioral claim.
The second production traversal stopped after fourteen local nodes and remains
preserved as incomplete (`build/sparkle/specialized-hierarchy-bundle-second/summary.json`).
The first attempt rejected ten unused vendor output pins; the corrected checker
requires their connected-pin set to match the qualified original exactly and
records every output omission. Inputs/inouts and internal child pins remain strict.
The second attempt stopped on an exported generate-loop variable in a module
with no overridable parameters. That case now has an explicit AST scope/value
check and 39 passing hierarchy guards. The fresh traversal passes all 97 local
specializations and 779 internal instance paths, with 528 DSP and eight shell
vendor occurrences, in
`build/sparkle/specialized-hierarchy-bundle-third/{summary,qualification}.json`.
It took 457 seconds, reached the 3 GiB cap with 19,743 reclamation events, and
recorded zero OOMs or kills. This completes the elaborated inventory for that
bundle. The subsequent machine-checked join from each specialization to its
applicable proof records also passes, including all six typed wrapper
configurations and every DSP/shell terminal, in
`build/sparkle/specialization-binding-bundle-final/{summary,qualification}.json`.
It authenticates ordered package/model context, exact component receipts and
actual parent/instance terminal contracts; all 45 focused guards pass. The final
join took 77 seconds under the 3 GiB cap with 51,877 reclamation events and no
OOMs or kills. Its status is `specialized_instances_bound_scope_incomplete`:
component assumptions remain inherited, and this is not a new behavioral
equivalence theorem or physical signoff.
Gen1's independent 100000-kHz API inventory and specialization binding now also
pass, covering 93 local specializations and 764 internal instance paths. Evidence is in
`build/sparkle/specialized-hierarchy-gen1-first/qualification.json` and
`build/sparkle/specialization-binding-gen1-first/qualification.json`.
The traversal took 441 seconds and binding took 79 seconds; both reached the
3 GiB cap with page reclamation and zero OOMs or kills. The same inherited
component/vendor/CDC/physical-signoff scope applies.
Gen2's independent 100000-kHz API inventory and binding also pass, covering 97
specializations and 779 internal paths, in
`build/sparkle/specialized-hierarchy-gen2-first/qualification.json` and
`build/sparkle/specialization-binding-gen2-first/qualification.json`.
Both API cases bind all 528 DSP and eight shell terminals independently. Gen2's
traversal took 447 seconds and binding took 80 seconds; both reached the 3 GiB
cap with reclamation and zero OOMs or kills. All three assemblies now have
complete elaborated inventories and specialization applicability records under
the recorded component assumptions; physical/vendor signoff remains separate.
VPU CL2 is covered
by the identical proved module bodies and wrapper wiring recorded in
`build/sparkle/vpu_qualification.json`. The interrupted 18-case Board run retained
15 progress dots but no authenticated selectors or JUnit report, so its exact
test list cannot be reconstructed. Fresh runtime qualifications record exact
case identities and preserve incomplete runs.

After sequencer promotion, fresh native runtime checks pass all eight selected
cases: three Top LiteDRAM programs, three Board channel cases, and Board WAITW
timeout/recovery plus exact MLP trace comparison. Records are in
`build/sparkle/runtime_refresh/{top-ldc-current,board-channel-current,board-sequencer-current-optional-deps}/`.
Each run verifies exact JUnit identities and unchanged source/tool inputs. The
three runs took 544, 433, and 343 seconds, with peak memory 3.00, 2.32, and
2.75 GiB respectively and no OOM kills. The first sequencer-suite attempt failed
collection because module-level optional PyTorch imports skipped all Board tests;
those imports now belong only to the two model tests that require them. That
failed attempt is preserved separately. These eight cases do not certify the
unrecovered 18-case suite or the complete native Board regression.

New runtime qualifications use an opt-in authenticated simulator cache. Cache
reuse requires matching ordered sources, parameters, compiler tools/options and
compilation environment, plus unchanged executable and compilation-log hashes.
Legacy cache entries do not qualify. Each run records its effective hardware
configuration and archives the exact simulator manifests and executable bytes.
The added cache and runtime evidence guards pass 37 tests; a real compilation,
authenticated cache hit and simulator execution also pass. Earlier runtime
records predate this executable-origin audit and retain their narrower scope.

Repeated host operations also reuse native RTL emission within the Python process.
Every call still runs Lake's dependency check, and reuse requires unchanged source,
generator, tool, adapter and environment identities plus the full emitted-file
hash. Missing, corrupted or symlinked artifacts trigger regeneration. All 21
targeted generation/source-selection tests pass. The initial control-suite attempt
in `runtime_refresh/board-op-control-audited/` was deliberately stopped and remains
incomplete after exposing repeated emission overhead; it is not a passing suite.
The replacement run in
`build/sparkle/runtime_refresh/board-op-control-audited-memo/summary.json` passes
all 38 exact control/instruction cases with no skips: loops and register offsets,
aligned/unaligned transfers, matrix modes, quantization, single-slice gather,
register loads, ARGMAX, HALT CHAIN and preloaded-host WAITW checks. Source/tool
and simulator audits pass. It took 874 seconds, peaked at 224 MiB, and recorded
zero memory-limit or OOM events. These are runtime comparisons, not additional
unbounded formal proofs or live-host WAITW coverage.

Small-model runtime qualification now selects 40 exact cases across Qwen3, LFM2,
Qwen3.5 and Gemma4, including their selected MoE variants. `SimTransport` cases
use `board-native-test`; `RtlBackend` cases use `top-test`. Two new full six-layer
Qwen3.5-MoE/Gemma4-MoE tests compare logits and every model-image byte with experts
preloaded; asynchronous host streaming remains separate. Qualification is recorded
per suite. All 58 harness/dependency guards, exact 40-case collection,
both new fixture/layout preflights and the actual dependency-byte preflight pass
(`build/sparkle/model-{collection,fixtures,dependencies}-bounded.log`). The isolated
CPU environment binds wheel hashes, installed package bytes and two copied loader
libraries; runtime suites require pre/post dependency checks, offline model use,
and one Torch intra/inter-op thread. This is not a hermetic OS/stdlib proof.
The first four Qwen3 Board cases now pass in
`build/sparkle/runtime_refresh/model-qwen3-board-audited-serial/summary.json`:
three token-step comparisons (default and mixed weight formats), plus twelve-token
generation across the attention-bucket boundary with complete model DRAM comparison.
Exact JUnit, unchanged dependencies/source/tools and simulator audits pass. The
run took 330 seconds, peaked at 2.42 GiB and recorded zero memory-limit/OOM events.
The initial model attempt was stopped and preserved as incomplete after finding
the application's three-worker compile-ahead default. `OTPU_COMPILE_AHEAD` now
allows a positive worker count while preserving the default of three; bounded
runs force it and `OTPU_BUILD_JOBS` to one. All 49 targeted scheduling/resource
guards pass.
The full six-layer Qwen3.5-MoE Board test also passes, comparing logits and every
model-image byte after four token steps, including recurrent/convolution state,
attention caches and expert-routing mailboxes. Experts are preloaded; asynchronous
host streaming remains outside this test. Exact JUnit, unchanged source/tools and
dependencies, and the simulator audit pass in
`build/sparkle/runtime_refresh/model-qwen35-moe-board-audited-first/summary.json`.
The qualification took 400 seconds, reached the 3 GiB cap with 2,711 reclamation
events, and recorded zero OOMs or kills.
The full six-layer Gemma4-MoE Board test also passes all four token steps with
bit-exact logits and complete model-image comparison, covering sliding/global
attention, shared global K/V, expert routing, parallel dense MLPs and padded
expert widths. Experts are preloaded here as well. Its exact JUnit, unchanged
source/tools/dependencies and simulator audit pass in
`build/sparkle/runtime_refresh/model-gemma4-moe-board-audited-first/summary.json`.
The qualification took 165 seconds, peaked at 816 MiB, and recorded no memory-limit
or OOM events.
All four LFM2 Board cases also pass five token-step logit comparisons each,
covering per-position/resident decoding and mixed per-kind/per-layer weight
formats through the convolution state-ring turnover. Exact JUnit, unchanged
source/tools/dependencies and all 64 simulator cache-use events are verified in
`build/sparkle/runtime_refresh/model-lfm2-board-audited-first/summary.json`.
The qualification took 276 seconds, peaked at 1.78 GiB and recorded no
memory-limit or OOM events.
The LFM2-MoE Board case also passes four token-step logit comparisons, four
generated tokens and the expected per-layer expert-request mailbox sequence.
Its preloaded experts and pre-satisfied fences do not qualify live expert
streaming. Exact JUnit, unchanged source/tools/dependencies and simulator
provenance pass in
`build/sparkle/runtime_refresh/model-lfm2-moe-board-audited-first/summary.json`.
The run took 249 seconds, peaked at 2.47 GiB and recorded no memory-limit or
OOM events.
All twelve Qwen3.5 Board cases pass six token-step logit comparisons each across
both model configurations: standard execution, DSTEP, resident decode, STREAM,
and per-kind/per-layer mixed weight formats. Exact JUnit, unchanged source/tools
and dependencies, and 216 simulator audit events (215 cache hits) are verified in
`build/sparkle/runtime_refresh/model-qwen35-board-audited-first/summary.json`.
The qualification took 1,572 seconds, peaked at 2.54 GiB and recorded no
memory-limit or OOM events.
All four Qwen3.5 group-major Board cases also pass, comparing six token-step
logits each against the array-major ISA programs at 16 and 18 heads, with and
without DSTEP and resident pair loops. Exact JUnit, unchanged source/tools and
dependencies, and simulator provenance pass in
`build/sparkle/runtime_refresh/model-qwen35-groups-board-audited-first/summary.json`.
The run took 830 seconds, peaked at 974 MiB and recorded no memory-limit or OOM
events.
Both Qwen3.5 no-DSTEP Board cases also pass capability discovery and three
token-step VOP fallback comparisons each. The first attempt stopped before model
execution because the suite forced PAIR=0 while hardware reported column reuse.
The suite now matches the actual PAIR=1/DSTEP=0/STREAM=0 capabilities; 36 harness
guards pass, including preservation of genuine host mismatch rejection. The
failed attempt is retained in `model-qwen35-no-dstep-board-audited-first/`.
Exact JUnit, unchanged source/tools/dependencies and simulator audit pass in
`build/sparkle/runtime_refresh/model-qwen35-no-dstep-board-audited-caps/summary.json`.
The corrected run took 307 seconds, peaked at 704 MiB and recorded no memory-limit
or OOM events. All 29 selected Board model cases are now qualified.
The LFM2 MLP-loop Top case also passes decode and prefill logits and full model
DRAM comparisons, with exact JUnit, unchanged source/tools/dependencies and
verified simulator provenance in
`build/sparkle/runtime_refresh/model-lfm2-mlp-top-audited-first/summary.json`.
That run took 208 seconds, peaked at 2.51 GiB and recorded no memory-limit or OOM
events.
The first resident-decode Top attempt reached the 3 GiB cgroup limit during C++
compilation and is preserved as incomplete in
`build/sparkle/runtime_refresh/model-lfm2-resident-design-top-audited-first/`.
Verilator combined 64 generated implementation files into one translation unit.
The audited builder now explicitly disables output grouping while keeping one
compiler job; the flags are authenticated cache inputs. All 54 cache and runtime
harness guards pass (`build/sparkle/serial-split-cache-guards.xml`).
The unchanged resident-decode test then passed logits and model DRAM comparisons
at positions 255 and 256, with exact JUnit, unchanged source/tools/dependencies and
verified simulator provenance in
`build/sparkle/runtime_refresh/model-lfm2-resident-design-top-audited-split/summary.json`.
It took 486 seconds, peaked at 2.25 GiB and recorded no memory-limit or OOM events.
All three Qwen3 Top prefill cases also pass: eight-row matrix replay at two and
four int8 columns, plus fp4 layers with an int8 head. The original tests compare
the complete model DRAM image against the ISA simulator and the final logits
against token-by-token decode. Exact JUnit, unchanged source/tools/dependencies
and simulator provenance pass in
`build/sparkle/runtime_refresh/model-qwen3-prefill-top-audited-first/summary.json`.
The run took 306 seconds, peaked at 1.90 GiB and recorded no memory-limit or OOM
events.
All three Qwen3.5 Top prefill cases also pass six-row continuation with DSTEP,
including both K/V-head configurations and the pipelined loop over 16 DeltaNet
heads. Complete model DRAM and final logits match the ISA references. Exact
JUnit, unchanged source/tools/dependencies and simulator provenance pass in
`build/sparkle/runtime_refresh/model-qwen35-prefill-top-audited-first/summary.json`.
The run took 505 seconds, peaked at 2.57 GiB and recorded no memory-limit or OOM
events.
All three Gemma4 Top cases also pass at position 600 after the original 600-token
prefill: per-position programs, resident programs and resident programs with
host-provided PLE data and its mailbox fence. Logits and the complete model DRAM
image match the ISA simulator. Exact JUnit, unchanged source/tools/dependencies
and simulator provenance pass in
`build/sparkle/runtime_refresh/model-gemma4-top-audited-first/summary.json`.
The run took 475 seconds, peaked at 712 MiB and recorded no memory-limit or OOM
events. All 40 selected random-model runtime cases are now qualified (29 Board,
11 Top). This finite suite does not establish real-checkpoint or physical-card
parity, nor discharge the remaining formal assumptions.
The software ISA/compiler baseline also passes all 24 cases
(`build/sparkle/isa-compiler-baseline.xml`); this is separate from RTL qualification.

An additional audited inventory preserves all 25 original Top native-memory
stress cases in five serial suites: latency/hazards, scoreboard stress, random
traffic, partial-beat ordering and read-modify-write fuzzing. Actual pytest
collection matches every literal selector; all 25 harness/collection guards pass
(`build/sparkle/memory-stress-harness.xml`). These retain the original C8/R8/ACT16
test geometry and explicit AXI/boot/native-memory selection, rather than claiming
production C4/R4 coverage. The first five latency/hazard cases pass complete
TMEM/DRAM comparison, including stalls and latency up to 400 cycles, with exact
JUnit, unchanged source/tools and verified simulator audit in
`build/sparkle/runtime_refresh/top-native-memory-latency-audited-first/summary.json`.
The run took 285 seconds, peaked at 2.99 GiB and recorded no memory-limit or OOM
events. The remaining 20 stress cases also pass in the corresponding
`runtime_refresh/top-native-memory-{scoreboard,fuzz,partial-order,rmw-fuzz}-audited-first/`
records: six scoreboard cases, two random-traffic cases, four partial-write
ordering cases and eight randomized read-modify-write cases. Each has exact
JUnit, complete TMEM/DRAM comparison, unchanged source/tools and verified
simulator evidence. These four suites took 126, 43, 242 and 176 seconds,
respectively; peak memory was 228 MiB, 183 MiB, 2.54 GiB and 223 MiB, with no
memory-limit or OOM events. All 25 native-memory stress cases are now qualified
at their original test configurations; this is not physical DDR/CDC signoff.

The broader original Top regression inventory now contains 119 new/refreshed
cases, with exact pytest collection and 26 harness/inventory checks passing
(`build/sparkle/top-regression-inventory.xml`). It partitions every original
`test_rtl.py` case and adds the existing VOP/STREAM/WAITW integration cases.
Three reference-only TMEM/DDR-BIST cases are explicitly outside native parity
claims; the existing native-memory 25 and LiteDRAM three-case suites are not
duplicated. No original programs or parameter combinations are downsized.
The six native-memory WAITW cases pass in
`build/sparkle/runtime_refresh/top-waitw-native-board-memory-audited-first/summary.json`:
store ordering, diagnostic programs and four host flag conditions with simulated
host writes during execution. Complete TMEM/DRAM comparisons, exact JUnit,
unchanged source/tools and simulator audit pass. The run took 380 seconds,
reached 3 GiB with 2,482 reclamation events, and had zero OOMs or kills.
These use native Top with the original test microarchitecture and Board-sized
geometry, not the physical Board shell or a real asynchronous expert server.
All nine compiler-kernel cases also pass: MLPs and attention at one, two and four
slices, attention-layer updates, and the original 128-element design case.
Complete DRAM/TMEM comparisons, exact JUnit, unchanged source/tools and simulator
audit pass in
`build/sparkle/runtime_refresh/top-compiler-kernels-audited-first/summary.json`.
The run took 1,125 seconds, peaked at 2.70 GiB and recorded no memory-limit or OOM
events (four builds and five authenticated cache hits).
The ten remaining randomized one-/two-slice cases and all sixteen scoreboard
stress cases also pass complete DRAM/TMEM comparisons, exact JUnit, unchanged
source/tools and simulator audit in
`build/sparkle/runtime_refresh/top-fuzz-remaining-audited-first/summary.json` and
`build/sparkle/runtime_refresh/top-scoreboard-audited-first/summary.json`.
These took 31 and 48 seconds, respectively, each peaking at 189 MiB with no
memory-limit or OOM events; all 26 simulator invocations were authenticated cache
hits.
All ten native-memory burst cases, six scale-coherence cases and six host-write
coherence cases also pass complete DRAM/TMEM comparisons, exact JUnit, unchanged
source/tools and simulator audit in
`build/sparkle/runtime_refresh/top-native-bursts-audited-first/summary.json`,
`build/sparkle/runtime_refresh/top-native-scale-coherence-audited-first/summary.json`
and `build/sparkle/runtime_refresh/top-native-host-coherence-audited-first/summary.json`.
These cover page-crossing reads, gathered byte writes, masked DMA write bursts,
scale-cache invalidation during DMA writes, and host scale rewrites between runs
and before WAITW release. Original transaction-count checks also pass: gathered
writes cause no controller read-modify-writes, scale caching reduces read traffic,
and DMA writes issue one command per beat. Runs took 387, 128 and 127 seconds,
peaking at 1.34 GiB, 224 MiB and 175 MiB, respectively, with no memory-limit or OOM
events (one build and 21 authenticated cache hits). These simulated host writes
do not establish physical XDMA/DDR coherence.
All six DMA alignment cases also pass: native memory at 0/50/85 percent stalls,
and behavioral memory at the original 4-/8-/16-lane geometries. Complete DRAM/TMEM
comparisons and all runtime provenance checks pass in
`build/sparkle/runtime_refresh/top-dma-native-audited-first/summary.json` and
`build/sparkle/runtime_refresh/top-dma-behavioral-audited-first/summary.json`.
These took 63 and 447 seconds, peaking at 171 MiB and 2.16 GiB, respectively.
Both 20,000-element logit-fill cases pass complete DRAM/TMEM comparisons, including
the dependent readback and surrounding memory, in
`build/sparkle/runtime_refresh/top-native-logit-fill-audited-first/summary.json`
(236 seconds, 1.89 GiB peak).
The transposed-value append-throughput case also passes DRAM equality, zero
controller read-modify-writes and the original under-5,300-cycle incremental
append bound under modeled DRAM timing in
`build/sparkle/runtime_refresh/top-native-vt-throughput-audited-first/summary.json`
(25 seconds, 280 MiB peak). Exact JUnit, unchanged source/tools and authenticated
simulator checks pass for all four suites, with no memory-limit or OOM events.
All five matrix-replay cases also pass at their original two-/four-column and
six-/eight-/sixteen-row geometries, with complete DRAM/TMEM comparison in
`build/sparkle/runtime_refresh/top-mxu-replay-audited-first/summary.json`
(339 seconds, 2.04 GiB peak). All six four-bit MLP cases pass in
`build/sparkle/runtime_refresh/top-fourbit-kernels-audited-first/summary.json`
(377 seconds, 1.48 GiB peak): int4/fp4 quantizer output, one/two slices, D32/D128,
and PAIR column reuse with odd block counts and unaligned scale rows. Complete
memory equality and the original numerical-error bounds pass. Both suites have
exact JUnit, unchanged source/tools and verified simulator provenance, with no
memory-limit or OOM events.
Both additive-attention-mask cases pass complete DRAM/TMEM equality through
behavioral and native memory, including fully masked rows, negative infinity,
accumulation and row maxima, in
`build/sparkle/runtime_refresh/top-mask-{behavioral,native}-audited-first/summary.json`
(139/125 seconds, 1.19/1.23 GiB peaks).
All three basic WAITW cases pass immediate conditions, host-written data ordering
and the expected timeout error in
`build/sparkle/runtime_refresh/top-waitw-basic-audited-first/summary.json`
(10 seconds, 183 MiB peak).
The three STREAM descriptor cases and four mixed STREAM/DSTEP/vector programs
also pass complete DRAM/TMEM comparisons in
`build/sparkle/runtime_refresh/top-stream-descriptors-audited-first/summary.json`
and `build/sparkle/runtime_refresh/top-stream-mixed-programs-audited-first/summary.json`
(464/85 seconds, 1.64 GiB/193 MiB peaks). These retain descriptor modes/gates,
register-relative addressing, scoreboard dependencies and selected special FP
inputs. All five suites pass exact JUnit, unchanged source/tools and simulator
provenance checks, with no memory-limit or OOM events.
All seven composite-vector cases, five direct-vector cases and three DSTEP
program cases also pass complete DRAM/TMEM comparisons in
`build/sparkle/runtime_refresh/top-vops-composites-audited-first/summary.json`,
`build/sparkle/runtime_refresh/top-vops-direct-audited-first/summary.json` and
`build/sparkle/runtime_refresh/top-dstep-programs-audited-first/summary.json`.
These retain 4-/8-/16-lane variants, original scheduling parameters, selected
special FP inputs and many tiny composite operations simultaneously in flight.
The runs took 441, 17 and 65 seconds, peaking at 1.80 GiB, 200 MiB and 184 MiB,
respectively. Exact JUnit, unchanged source/tools and simulator provenance pass;
no memory-limit or OOM events occurred.
The six historical Top cases now pass the stronger audit refresh in
`build/sparkle/runtime_refresh/top-baseline-refresh-audited-first/summary.json`:
one-/two-slice random programs, attention/MLP lane-count invariance at four and
sixteen lanes, and R8–R15 run arguments with/without boot loading. The run took
600 seconds, peaked at 2.10 GiB and had no memory-limit or OOM events; exact JUnit,
unchanged source/tools and eight authenticated simulator invocations pass.
The separate reference TMEM bypass bench and external DDR-controller sequential
read/write BIST checks also pass with the same audit requirements in
`build/sparkle/runtime_refresh/reference-tmem-bypass-audited-first/summary.json`
and `build/sparkle/runtime_refresh/external-ldc-bist-audited-first/summary.json`
(10/12 seconds, 477/480 MiB peaks, no memory-limit or OOM events).
All 119 cases are now qualified: 116 native Top cases and three external-reference
cases. Exact suite/case identities, nonoverlap, expected counts, scopes and recorded
audit results are reconciled in
`build/sparkle/runtime_refresh/top119-inventory-reconciliation.json`.
The external benches are not native implementation proofs or new physical-card
measurements; the finite runtime inventory does not discharge formal assumptions.

Real-checkpoint qualification has a separate inventory of 18 unchanged RTL cases
in `tools/sparkle_checkpoint_runtime_suites.py`. All use native Top through
`RtlBackend`, including the ten tests with board memory geometry; they do not
exercise a physical card or the Board transport wrapper. The qualifier now binds
the complete live checkpoint file inventory before and after each run, in
addition to source, dependency and simulator evidence. The checkpoint/inventory
and existing qualification guards pass 49 tests, including actual collection of
all 18 selectors.

LFM2.5-230M is available at the pinned revision
`40cb2ad3b3044d5a41eee083a6103c8b523afa45`. Its acquisition receipt is
`build/sparkle/checkpoint_acquisition/lfm2-pinned-first/summary.json`; downloaded
files match the revision's Git/LFS identities and sizes. To reduce runtime
memory, DRAM input serialization now streams endian conversion, boot padding
and program bytes in chunks. All 41 byte-parity, allocation and boot/short-dump
tests pass in `build/sparkle/rtlsim-image-serialization-first.xml`. Workload sizes,
returned memory and comparisons are unchanged.

The first real-checkpoint case now passes:
`test_lfm2_5_230m_token_on_rtl_is_bit_exact[fp4-int8-True-False]`.
It retains the original two-slice configuration, 128 MiB DRAM per slice,
256-token capacity, nine ISA-prefill tokens and one native-RTL token. Logits and
the entire used DRAM image match bit for bit. Evidence is in
`build/sparkle/runtime_refresh/checkpoint-lfm2-fp4-int8-audited-first/summary.json`:
exact JUnit, unchanged checkpoint/dependency/source/tool bytes and an authenticated
simulator cache hit all pass. Qualification took 203 seconds and reached the
3 GiB ceiling with 2,822 reclaim events, zero OOMs and zero killed processes.
The simulator was prebuilt separately (325 seconds, 2.01 GiB peak, no limit
events), avoiding concurrent weight loading and compilation. This completes
the first of the 18 real-checkpoint cases; physical-card runs remain separate.

The resident checkpoint's larger memory layout required further representation
changes. The behavioral DRAM simulation ABI now loads through a 4096-word scratch
buffer instead of retaining a second full-size DRAM image. All 51 differential
cases pass against original RTL, including partial words, chunk boundaries,
missing/empty/oversized inputs, absent directory arguments, complete initial
memory, port activity and final dumps. Authenticated evidence is in
`build/sparkle/dram-chunk-init-first/summary.json`; the native storage/read/write
core is unchanged.

Model qualification also sets `OTPU_WEIGHT_CACHE_BYTES=33554432` to bound the
aggregate small-tensor cache and `OTPU_SIM_MMAP=1` for independent disk-backed
RTL snapshots and copy-on-write dump mappings. Both are opt-in outside the
qualifier. The original memory sizes, tensor values, writable-array behavior,
dump-length checks and full state comparisons are preserved. The combined
cache/mapping/serialization/qualification suite passes 128 tests in
`build/sparkle/mmap-cache-guards-first.xml`.

The resident LFM2.5-230M case now also passes unchanged:
`test_lfm2_5_230m_token_on_rtl_is_bit_exact[fp4-int8-True-True]`.
It uses two slices with 512 MiB DRAM each, including the on-device embedding
lookup table. After nine ISA-prefill tokens, the next native-RTL token matches
both the ISA logits and full used DRAM image; the additional comparison with
the per-position program passes too. The receipt is
`build/sparkle/runtime_refresh/checkpoint-lfm2-fp4-int8-resident-audited-first/summary.json`.
Exact JUnit, checkpoint/dependency/source/tool stability and the authenticated
simulator cache hit all pass. Qualification took 232 seconds, reaching the
3 GiB cap with 15,799 reclaim events and zero OOMs/kills. Its separate prebuild
took 332 seconds, peaking at 2.12 GiB with no limit events.

The original LFM2 board-memory C2 case also passes unchanged, using one slice,
1 GiB DRAM, AXI transfers and boot loading. Exact logits and the full used DRAM
image agree with the ISA simulator. Its receipt is
`build/sparkle/runtime_refresh/checkpoint-lfm2-board-c2-audited-first/summary.json`.
Source, tool, dependency and checkpoint stability checks pass, with one
authenticated simulator cache hit. Qualification took 197 seconds, reaching
the 3 GiB cap with 3,903 reclaim events and zero OOMs/kills. Its separate
prebuild took 89 seconds, peaking at 1.22 GiB with no limit events. This test
exercises native Top with the board memory configuration, not a physical FPGA
card.

The resident-embedding variant of the same original C2 board-memory test also
passes, reusing that authenticated simulator. Exact logits and full used DRAM
agree, with unchanged source, tool, dependency and checkpoint inputs:
`build/sparkle/runtime_refresh/checkpoint-lfm2-resident-board-c2-audited-first/summary.json`.
Qualification took 178 seconds, reaching the 3 GiB cap with 6,252 reclaim
events and zero OOMs/kills.

Both original C4 board-memory variants now pass as well, preserving the
one-slice, 1 GiB layout, AXI transfers, boot loading, and exact logits/full used
DRAM comparisons. Their authenticated receipts are
`build/sparkle/runtime_refresh/checkpoint-lfm2-board-c4-audited-first/summary.json`
and
`build/sparkle/runtime_refresh/checkpoint-lfm2-resident-board-c4-audited-first/summary.json`.
Source, tool, checkpoint and dependency inputs remained unchanged. The shared
simulator prebuild took 126 seconds and peaked at 1.43 GiB with no limit events.
The nonresident/resident qualifications took 225/208 seconds, respectively;
both reached the 3 GiB cap, with 2,870/6,334 reclaim events and zero OOMs/kills.
All four LFM2 board-memory cases are qualified.

The unchanged LFM2 INT8 checkpoint case also passes, with two slices, eight MXU
columns, 16 lanes and 128 MiB DRAM per slice. Exact logits and full used DRAM
agree with the ISA reference after nine prefill tokens. The receipt is
`build/sparkle/runtime_refresh/checkpoint-lfm2-int8-audited-first/summary.json`;
source, tool, checkpoint and dependency stability checks pass. Qualification
took 254 seconds and peaked at 1.57 GiB with no limit events. Its separate
simulator prebuild took 486 seconds and peaked at 2.66 GiB, also with no limit
events. All seven original LFM2 checkpoint cases are now qualified: seven of
18 overall, with eleven Qwen cases remaining.

`tools/fetch_sparkle_qwen_checkpoint.py` prepares the Qwen inputs using pinned
revisions, API/tree inventory agreement, streaming downloads and Git/LFS hash
verification before installation. Its eleven small integrity tests pass
(`build/sparkle/qwen-fetch-guards-first.xml`). Both checkpoint acquisitions now
pass: Qwen3-0.6B revision `c1899de289a04d12100db370d81485cdf75e47ca`
(nine files, 1,519,207,673 bytes) and Qwen3.5-0.8B revision
`2fc06364715b967f1860aea9cf38778875588b17` (ten files, 1,769,978,120 bytes).
The receipts are
`build/sparkle/checkpoint_acquisition/qwen3-pinned-first/summary.json` and
`build/sparkle/checkpoint_acquisition/qwen35-pinned-first/summary.json`.
Acquisition took 120/140 seconds and peaked at 2.57/2.58 GiB, respectively,
with no limit events. These authenticate the complete downloaded weight files.

The original Qwen3 C2 board-memory checkpoint case now passes unchanged, with
AXI transfers and boot loading. Exact logits and the full used DRAM image
agree with the ISA reference. Its receipt is
`build/sparkle/runtime_refresh/checkpoint-qwen3-board-c2-audited-first/summary.json`;
source, tool, dependency and checkpoint stability checks pass, with the
authenticated cached simulator. Qualification took 420 seconds and reached the
3 GiB cap with 13,260 reclaim events and zero OOMs/kills.

The corresponding unchanged Qwen3 C4 case also passes exact logits and full
used DRAM comparison, with stable source, tool, checkpoint and dependency inputs
and the authenticated cached simulator:
`build/sparkle/runtime_refresh/checkpoint-qwen3-board-c4-audited-first/summary.json`.
It took 412 seconds, reaching the 3 GiB cap with 12,620 reclaim events and zero
OOMs/kills. Both original Qwen3 board-memory cases are qualified. Nine of the
18 real-checkpoint cases are qualified; nine Qwen cases remain.

The first Qwen3.5 C2 board-memory attempt is incomplete: the enforced 3 GiB
cgroup terminated it with exit 137 before a numerical result. The kernel
record confirms a local memory-cgroup OOM, with about 2.27 GiB anonymous RSS
in the Python test process and 0.68 GiB in the simulator. The preserved input
receipt, log and kernel evidence are recorded in
`build/sparkle/runtime_refresh/checkpoint-qwen35-board-c2-audited-first/failure.json`.
This is not a qualified pass.

With `OTPU_SIM_MMAP=1`, ISA DRAM now also uses independent writable disk
snapshots at the full configured capacity, including the complete zero tail.
Adoption transfers the caller's image-list entries to the mappings, and completed
ISA runs flush updates so pages can be reclaimed during RTL simulation. Default
anonymous-memory behavior remains unchanged. The memory/serialization/cache
suite passes 95 tests, including complete ISA LD/ST/register-state comparison,
ownership, zero padding and mapping lifetime:
`build/sparkle/isa-mmap-guards-disk.xml`. The initial test invocation used
RAM-backed `/tmp` and was correctly rejected; its failed JUnit is retained in
`build/sparkle/isa-mmap-guards-first.xml`.

The unchanged Qwen3.5 C2 checkpoint retry now passes with mapped ISA memory:
`build/sparkle/runtime_refresh/checkpoint-qwen35-board-c2-audited-isa-mmap/summary.json`.
Exact logits and the full used DRAM image match, including the recurrent state;
source, tool, checkpoint and dependency stability checks pass with the
authenticated simulator. Qualification took 497 seconds, reaching the 3 GiB cap
with 24,660 reclaim events and zero OOMs/kills. The earlier failed attempt is
retained. Ten of the 18 real-checkpoint cases are now qualified; eight remain.

The unchanged Qwen3.5 C4 board-memory case also passes with mapped ISA memory:
`build/sparkle/runtime_refresh/checkpoint-qwen35-board-c4-audited-isa-mmap/summary.json`.
Exact logits, full used DRAM and provenance checks pass. Qualification took
532 seconds, reaching the 3 GiB cap with 19,958 reclaim events and zero OOMs/kills.
Both original Qwen3.5 board-memory cases without DSTEP are qualified. Eleven
of the 18 real-checkpoint cases are now qualified; seven remain.

The unchanged Qwen3.5 DSTEP C2 board-memory case now passes too:
`build/sparkle/runtime_refresh/checkpoint-qwen35-dstep-board-c2-audited-first/summary.json`.
Exact logits and full used DRAM, including recurrent state, agree with the ISA
reference; source, tool, checkpoint and dependency stability checks pass with
the authenticated simulator. Qualification took 525 seconds, reaching the 3 GiB
cap with 41,365 reclaim events and zero OOMs/kills. Twelve of the 18
real-checkpoint cases are now qualified; six remain.

The unchanged Qwen3.5 DSTEP C4 case also passes exact logits, full used DRAM
and all provenance checks:
`build/sparkle/runtime_refresh/checkpoint-qwen35-dstep-board-c4-audited-first/summary.json`.
Qualification took 469 seconds, reaching the 3 GiB cap with 22,550 reclaim
events and zero OOMs/kills. All four Qwen3.5 board-memory cases are now
qualified. Thirteen of the 18 real-checkpoint cases are qualified; the three
Qwen3 behavioral-memory variants and two Qwen3.5 behavioral-memory variants
remain.

The recovered Qwen3 INT8 behavioral-memory qualification now passes:
`build/sparkle/runtime_refresh/checkpoint-qwen3-int8-audited-recovered/summary.json`.
The original prompt, exact logits and full used DRAM comparison are unchanged;
the exact JUnit case, simulator audit and final source/tool/checkpoint/dependency
stability checks all pass. Qualification took 560.79 seconds, reached the 3 GiB
cap with 8,033 reclaim events, and recorded zero OOMs/kills. The earlier
interrupted attempt remains incomplete. Fourteen of the 18 checkpoint cases
are qualified; the two Qwen3 FP4 variants and two Qwen3.5 behavioral-memory
variants remain. The recovered dependency files now live persistently under
`build/sparkle/recovery/`, with the original paths retained through compatibility
links and all 20,827 installed files verified against the original manifest.

The Qwen3 FP4 behavioral-memory case with an INT8 head also passes:
`build/sparkle/runtime_refresh/checkpoint-qwen3-fp4-int8-audited-first/summary.json`.
The exact original test passes without skips; simulator authentication and final
source, tool, checkpoint and dependency stability checks pass. Qualification
took 622.43 seconds, reached the 3 GiB cap with 6,626 reclaim events, and recorded
zero OOMs/kills. Fifteen of the 18 checkpoint cases are now qualified; Qwen3
FP4 PAIR and the two Qwen3.5 behavioral-memory variants remain.

The Qwen3 FP4 PAIR behavioral-memory case now passes too:
`build/sparkle/runtime_refresh/checkpoint-qwen3-fp4-pair-audited-first/summary.json`.
Its exact original test case passes without skips, with a verified simulator
and unchanged source, tools, checkpoint and dependencies. Qualification took
360.20 seconds, reached the 3 GiB cap with 9,629 reclaim events, and recorded
zero OOMs/kills. Sixteen of the 18 checkpoint cases are qualified; only the
two Qwen3.5 behavioral-memory variants remain. The separate exact-config
simulator prebuild took 327.25 seconds at 1.95 GiB with no limit events.

The Qwen3.5 behavioral-memory case without DSTEP now passes:
`build/sparkle/runtime_refresh/checkpoint-qwen35-vop-audited-first/summary.json`.
The exact original test passes without skips; simulator authentication and final
source/tool/checkpoint/dependency stability checks pass. Qualification took
293.97 seconds, reached the 3 GiB cap with 14,705 reclaim events, and recorded
zero OOMs/kills. Seventeen of the 18 checkpoint cases are qualified; only the
Qwen3.5 DSTEP behavioral-memory variant remains. Its preceding exact-config
simulator prebuild took 135.96 seconds at 1.27 GiB with no limit events.

The final Qwen3.5 DSTEP behavioral-memory case now passes:
`build/sparkle/runtime_refresh/checkpoint-qwen35-dstep-audited-first/summary.json`.
Its exact original test and all simulator/source/tool/checkpoint/dependency
audits pass. Qualification took 275.28 seconds, reached the 3 GiB cap with
15,490 reclaim events, and recorded zero OOMs/kills. All 18 original
real-checkpoint cases are now qualified. This completes that runtime inventory;
whole-system formal initialization and physical FPGA signoff remain separate.
An independent inventory reconciliation also passes:
`build/sparkle/checkpoint-inventory-reconciliation-first/summary.json`.
It verifies all 18 exact JUnit cases, rechecks 21,146 unique archived objects,
reconstructs simulator identities and final provenance checks, and excludes
the two incomplete/failed checkpoint attempts. Its 29 guards pass; reconciliation
took 8.86 seconds at the 3 GiB cap with 304 reclaim events and zero OOMs/kills.
These are separately qualified historical native-Top runs, including the
board-memory-named cases; the reconciliation does not claim one common
current-tree run, BoardBackend transport coverage or physical FPGA execution.

The first audited Board functional suite passes both selected tests: vector
RDOT/OUTER/LOG2 operations and all STREAM modes plus DSTEP. Its exact JUnit
identities, unchanged source/tool inputs, and consumed simulator executable are
authenticated in
`build/sparkle/runtime_refresh/board-functional-audited/summary.json`.
The run took 378 seconds, peaked at 2.58 GiB, and recorded no memory-limit or
OOM events. It compiled one simulator and authenticated 15 subsequent cache hits.

The audited Board VPU suite passes all 63 arithmetic, broadcast, reduction,
dot/outer-product and edge-value cases in
`build/sparkle/runtime_refresh/board-op-vpu-audited-first/summary.json`.
Together with the 38 qualified control cases, this covers all 101 original
`op_checks` cases selected for Board qualification. Exact JUnit, unchanged
source/tools and simulator provenance checks pass (504 events, 503 cache hits).
The VPU run took 1,570 seconds, peaked at 2.18 GiB and recorded no memory-limit
or OOM events. The ISA-oracle edge cases deliberately exclude NaN operands
because original RTL and ISA NaN behavior differs; native/original floating-point
proofs and datapath comparisons carry that separate obligation.

The two Board address-suite cases and two direct native-memory Board cases also
pass, with exact JUnit, unchanged source/tools and verified simulator usage, in
`build/sparkle/runtime_refresh/{board-address,board-native-memory}-audited-first/summary.json`.
The address suite checks the host SimTransport address map plus actual RTL
partial writes; it does not qualify physical DDR address lines. The direct
native-memory cases exercise demo/masked-write programs with two stall seeds,
separately from the memory-channel path. Runs took 41 and 193 seconds, peaking
at 213 MiB and 2.21 GiB, with no memory-limit or OOM events.

The audited Board observability suite also passes all 13 selected cases:
register maps, host calibration, I2C, counters and snapshots, MXU starvation,
three exact hardware-trace comparisons, long waits, ring/full-stop behavior and
dropped-record accounting. The run authenticated eight simulator binaries and
54 cache hits, with exact JUnit identities and unchanged source/tool inputs.
It took 1,748 seconds under the 3 GiB cap; page reclamation reached the cap,
with zero OOM events or kills. Evidence is in
`build/sparkle/runtime_refresh/board-observability-audited/summary.json`.

The Lean source proves command packing and abstract byte-bank/wide-memory
correspondence. `ProductComposition.lean` additionally proves a generic
synchronous composition rule: equal parent responses, related Moore child
outputs, and relation-preserving child steps yield output agreement at every
cycle from a related initial-state witness. Lean accepted its four theorems
(`build/sparkle/product-composition-kernel-first.log`, 34.64 seconds, 512 MiB
cap, zero OOMs). This checks the logical rule; instantiating its premises for
generated Quant RTL and authenticating external SAT results remain separate.
Circuit equivalence evidence is primarily
external Yosys/SAT/SMT proofs, composition audits, and differential tests; it is
not a Lean-kernel proof of each generated circuit or of the Verilog emitter.
The original synchronous FIFO definition remains available only for unchanged
external split consumers; all channel FIFOs are native. Physical validation of
native CDC constraint mappings and complete FPGA build integration remain outstanding.
An initial native CDC constraint file is generated separately by
`tools/generate_sparkle_mem_channel_constraints.py`. Register/FIFO ownership is
checked against four qualified native hierarchies; mock Tcl evaluation preserves
25 maximum delays, 14 bus-skew constraints and five waivers. This does not verify
post-synthesis Vivado cell names or crossing coverage. The top-level adaptation
in `build/sparkle/top_native_constraints/` also passes native AST/ABI ownership
checks and mock Tcl evaluation for both CSR clock choices, preserving all 12
timing/waiver commands. Its helper tests reject incorrect ownership, unadapted
reference paths, and timing-policy changes. The board-XDC adaptation also passes
native ownership and mock checks for temperature and I2C synchronizers, preserving
all 43 board commands and the pin, GTX and LiteDRAM placement policy. Evidence is
in `build/sparkle/board_native_constraints/`. Actual Vivado endpoint and
crossing validation remains outstanding for all three constraint files.
The default project still selects the original hardware. An opt-in
`OTPU_SPARKLE_BUNDLE` project path is under validation: it requires a matching
configuration/file manifest, selects the native physical RTL and adapted
constraints, and restricts local builds to the bounded runner with one job.
All 78 board-constraint and project-selection helper tests pass, including
parameter mismatch/reuse guards, source selection and native setup/hold timing
rejection before bitstream generation. Results are in
`build/sparkle/native-build-helper-tests.xml`. The bundle verifier passes 45
additional tests. A fresh Gen2 bundle at 133,333 kHz, BUILD_ID=0 passes independent
CLI/API equality, complete Verilator lint and actual preflight acceptance/rejection
checks for project markers and changed clock parameters. Its manifest is
`build/sparkle/fpga-bundle-gen2/manifest.json`; qualification evidence is in
`build/sparkle/fpga-bundle-gen2-qualification/summary.json`. Actual Vivado
qualification remains pending before this is a qualified FPGA build.

Prepare a new bundle for the exact intended configuration with
`tools/prepare_sparkle_fpga_bundle.py prepare --bundle DIR --parameters`
followed by the eleven decimal FPGA arguments listed below. Preparation and
verification require the bounded runner. Source or constraint changes invalidate
the bundle; prepare into a new directory. `OTPU_SPARKLE_BUNDLE=DIR` selects it in
`boards/ypcb-00338/run_vivado.sh`. Native `STEP=impl` reuses the saved configuration
and rejects explicit configuration overrides; use a full build to change them.
The complete native FPGA API now passes assembly and Verilator lint in both
behavioral and physical modes for Gen1, Gen2, and a nondefault configuration.
Gen1 contains 86 behavioral modules and 95 physical modules; Gen2 contains 90
and 99 respectively, including its registered DMA path.
Their shell bytes and parameters match the independently qualified FPGA glue,
and only the intended MXU implementation and simulation diagnostics differ.
Authenticated matrix evidence is in
`build/sparkle/check_fpga_top_complete/matrix-summary.json`.
This matrix establishes assembly/elaboration; the supplemental physical-proof
binding above now covers the exact D=128, four-column DSP implementation.
Actual Vivado timing/CDC qualification remains outstanding.
The generator exposes these complete APIs as `fpga-top` and `fpga-top-physical`,
with arguments in this order:

```text
MCOLS ACT_ROWS VPU_CL MXU_IMPL LANES ULANES CORE_KHZ BUILD_ID DDR_MTS DSTEP PCIE_GEN OUTPUT.sv
```

All numeric arguments use decimal notation; `DSTEP` must be zero or one.
The emitted hardware is specialized to these values: changing Verilog parameter
overrides requires regenerating the bundle. `board-physical` takes the same
25 configuration arguments as `board-native` and selects the physical MXU API.
CLI-to-API output qualification now passes: all six FPGA CLI emissions match the
qualified Gen1, Gen2 and variant API outputs byte-for-byte. A separately configured
physical Board emission also matches its independent named-field API invocation,
and all 15 invalid-argument checks reject without creating outputs. Evidence is
in `build/sparkle/check_fpga_cli/summary.json`; the bounded run completed with no
OOM events. The `check-sparkle-fpga-cli` Make target repeats this qualification
inside the bounded runner. These commands do not supply the external
PCIe block design, LiteDRAM core, vendor primitives, or qualified physical constraints.
Run generator builds and emissions through `tools/sparkle_bounded.py`, as required
by `AGENTS.md`.

For the sequencer at `IMEM_WORDS=65536, D=128, S=1, WIN=32`, out-of-context
Kintex-7 synthesis reports 31,302 native LUTs versus 31,313 reference LUTs and
18,860 native flip-flops versus 19,580 reference flip-flops. Both use 57 RAMB36
blocks and eight DSP48 blocks; distributed RAM counts are 212 native RAM32M
cells versus 218 reference cells. The strict resource gate passes with no tracked
regression. Native queues and loop-start addresses use RAM; register reads and
release-dependency selection use balanced mux trees. Resource evidence is in
`build/sparkle/seq_candidate/balanced_release_decode_exact/summary.json`.
Its complete-state candidate matrix also passes (8,534, 12,508 and 14,044 state
bits), with the HALT mutation rejected. This retains the existing ISA depth-four
loop-stack contract; evidence is in `build/sparkle/formal_seq_candidate/summary.json`.
The production-size IMEM positive proof also passes for the saved candidate
(32,768 instruction words, D=128, one slice, WIN=16): all 31,772 retained state
bits and the identical 1,048,576-bit IMEM primitive boundary are covered under
the same ISA contract. The authenticated replay proves all 36,329 equivalence
cells; evidence is in
`build/sparkle/formal_seq_ports/candidate/default/replays/20261011T001938Z-5911c7bde5b6/status.json`.
Both production-size IMEM fault controls are rejected with SAT counterexamples:
one flips a native write-data bit, the other flips a native read-address bit.
Each retains the complete 31,772-bit state pairing and exact memory boundary;
authenticated results are under
`build/sparkle/formal_seq_ports/candidate/bounded_mutations/`.
The optimization is now promoted. Fresh production emissions match the three
small proof configurations, the production-size IMEM proof, and the exact
physical/ABI resource configuration byte-for-byte. This binds the existing
proofs and resource results to current production code; it is not a new synthesis
run. Evidence is in
`build/sparkle/seq_promotion/20261011T004515Z-43920839f641/summary.json`.

At `D=128, MCOLS=ROWS=4, BLOCKS=128, LANES=8`, out-of-context
Yosys Kintex-7 synthesis maps both activation RAM implementations to 64 RAMB36
blocks, four RAMB18 blocks, 1,334 flip-flops, and 46 SRL16 cells. The native circuit's
shared barrel shifter uses 1,500 LUTs versus 6,082 for the reference. These counts
cover this configuration only and do not establish placed area or timing parity.
For the board's 64K-word, eight-lane, six-copy TMEM configuration, both versions
map to 384 RAMB36 blocks, 2,829 flip-flops, and 294 carry cells. Native TMEM uses
13,210 LUTs versus 13,267 for the reference; its strict resource-count gate passes.
Counting inverters as well gives 13,230 native cells versus 13,281 reference cells.
The optimized data rotation passes all three full-memory proof configurations.
The default-size proof checks all 4,512 pipeline register bits and all interfaces
of 48 matched RAM primitives, covering 12,582,912 stored bits through identical
memory semantics. Deliberate RAM-write and bypass-selection errors are rejected.
Authenticated results are in `build/sparkle/tmem_optimized_qualification.json`.
Full-design area and timing qualification is still required.

Wrapper/shell applicability joins, elaborated hierarchy inventories and
specialization bindings are complete for the three qualified assemblies.
Completion still requires broader ISA, compiler, model and board regressions; and actual
FPGA synthesis, CDC, timing/DRC and hardware evidence. The existing component
proofs retain their stated assumptions and reference-undefined behavior scopes.
Native implementation coverage alone does not establish complete parity.

## Results

The design runs ten modern models with their real weights on an Inspur YPCB-00338 card
(Xilinx Kintex-7 xc7k480t, two DDR3 channels), and the card produces the same tokens as the
simulator, bit for bit.

| Model | Weights | Decode, device | Decode, wall | Prefill, device | DRAM while decoding |
|:--|:--|--:|--:|--:|--:|
| LFM2.5-230M | int8 | 59.0 tok/s | 52.3 tok/s | 295.6 tok/s | 14.5 GB/s (85% of peak) |
| LFM2.5-230M | 4-bit, int8 head | 85.8 tok/s | 82.1 tok/s | 335.4 tok/s | 14.1 GB/s (82%) |
| Qwen3-0.6B | int8 | 21.6 tok/s | 21.3 tok/s | 92.1 tok/s | 14.4 GB/s (84%) |
| Qwen3-0.6B | 4-bit, int8 head | 31.3 tok/s | 30.7 tok/s | 103.4 tok/s | 13.9 GB/s (82%) |
| Qwen3.5-0.8B | int8 | 17.6 tok/s | 16.3 tok/s | 61.4 tok/s | 14.5 GB/s (85%) |
| Qwen3.5-0.8B | 4-bit, int8 head | 24.5 tok/s | 23.3 tok/s | 66.7 tok/s | 14.1 GB/s (83%) |
| Gemma 4 E2B | 4-bit, int8 head | 10.57 tok/s | 10.53 tok/s | 32.1 tok/s | 15.6 GB/s (92%) |
| Gemma 4 E2B | 4-bit, 4-bit head | 12.14 tok/s | 12.09 tok/s | 29.9 tok/s | 15.5 GB/s (91%) |
| LFM2-2.6B | int8 | 6.05 tok/s | 6.03 tok/s | 21.4 tok/s | 16.1 GB/s (94%) |
| LFM2-2.6B | 4-bit, int8 head | 10.96 tok/s | 10.93 tok/s | 20.6 tok/s | 15.8 GB/s (93%) |
| SmolLM3-3B | int8 | 5.00 tok/s | 4.99 tok/s | 21.1 tok/s | 16.0 GB/s (94%) |
| SmolLM3-3B | 4-bit, int8 head | 8.74 tok/s | 8.72 tok/s | 22.8 tok/s | 15.7 GB/s (92%) |
| Phi-4-mini (3.8B) | int8 | 3.99 tok/s | 3.98 tok/s | 13.8 tok/s | 16.0 GB/s (94%) |
| Phi-4-mini (3.8B) | 4-bit, int8 head | 6.56 tok/s | 6.55 tok/s | 15.0 tok/s | 15.8 GB/s (92%) |
| Qwen3.5-2B | int8 | 8.02 tok/s | 8.00 tok/s | 38.2 tok/s | 16.0 GB/s (94%) |
| Qwen3.5-2B | 4-bit, int8 head | 12.09 tok/s | 12.03 tok/s | 41.7 tok/s | 15.8 GB/s (92%) |
| Qwen3.5-4B | 4-bit, int8 head | 5.88 tok/s | 5.87 tok/s | 12.9 tok/s | 15.7 GB/s (92%) |
| Gemma 4 E4B | int8, 4-bit head and down 0-23 | 3.78 tok/s | 3.75 tok/s | 14.8 tok/s | 16.0 GB/s (94%) |

*Measured on the card: the first three models on 2026-09-29 with the production image
`deploy_champ_e698dcd7`. LFM2-2.6B, SmolLM3-3B and Phi-4-mini on 2026-09-30, and Qwen3.5-2B and
4B and Gemma 4 on 2026-10-01, with build B, `deploy_fused133c_79c5707a`, production since then.
Build B decodes LFM2-2.6B, SmolLM3 and Phi-4-mini 8-9% faster than e698dcd7 (Gemma 4 E2B 10%),
at 91-94% of the DRAM peak instead of 82-87%. Qwen3.5-4B's int8 image is over 4 GiB.*
- *The image: main e698dcd at 133.33 MHz, one bitstream for all models. It has LiteDRAM
  controllers calibrated by a small CPU inside the memory core, a four-column systolic matrix
  unit and the stream engine ([docs/stream.md](docs/stream.md)). DDR3-1066, with a 17.1 GB/s
  peak.*
- *The host: the card sits in opentpu (Intel Core i7-4790).*
- *Method, `tools/qual/perf.py`: decode is 64 greedy tokens after a 512-token prompt, with the
  host's argmax in the loop (not streamed). "Device" counts only the cycles the accelerator runs;
  "wall" adds the host. Prefill is the 512-token prompt, on the device.*
- *DRAM traffic comes from the card's own counters while it runs.*
- *Gemma 4 E2B keeps its per-layer embedding tables on the card (3.5-3.6 GiB images;
  [docs/gemma4.md](docs/gemma4.md)); in int8 it does not fit. The base checkpoint (gemma-4-E2B)
  matches Hugging Face's greedy tokens on three prompts with either head. The chat runs the
  instruct checkpoints (gemma-4-E2B-it, ...: the same images and speeds). E4B's table (2.95 GB)
  stays on the host, which copies one 11 KB row into the card per token; its image is 3.96 GiB,
  int8 with the head and the first 24 layers' down projections in 4-bit, as measured here
  ([docs/gemma4_e4b.md](docs/gemma4_e4b.md)). Since 2026-10-09 E4B-it's default is the head and
  the first 12 layers' gate / up projections in 4-bit: the same bytes a token, perplexity
  within 0.01% of int8's instead of +3.2%, and prompt runs of 2 rows instead of 3-4
  ([docs/formats.md](docs/formats.md)).
  In the card's own decode loop (the card picking every token) Gemma 4 decodes faster: E2B
  11.01 / 12.73 tok/s (int8 / 4-bit head), E4B 3.83 tok/s, on the device.*
- *Every configuration matches the simulator token for token, per-position and with the
  resident decode program. More detail in [docs/board.md](docs/board.md).*

With the logits streamed back while the card runs (`tools/decode_profile.py`, 96 tokens), 4-bit
decode is faster, in device / wall tok/s:
- LFM2: 89.5 / 84.5;
- Qwen3: 33.7 / 33.3;
- Qwen3.5: 24.6 / 24.2;
- LFM2-2.6B: 11.07 / 11.02 (build B);
- SmolLM3-3B: 8.92 / 8.89 (build B);
- Phi-4-mini: 6.69 / 6.67 (build B).

The previous production image, se-cand3, was built with the Xilinx MIG, a two-column matrix
unit and a 120.755 MHz clock. Measured the same way, the new image:
- **decode:** within 2.3% of se-cand3's in every configuration. Decode is bound by DRAM, and
  LiteDRAM reads at 82-85% of the DDR3 peak, as the MIG did.
- **prefill:** 1.3x (Qwen3.5) to 2.0x (LFM2 4-bit) faster.
- **calibration:** when the image starts, the core's CPU calibrates both DDR3 channels in 12 s,
  with no host involvement.

The earlier images and their numbers are in [docs/board.md](docs/board.md), section 5.

Mixture-of-experts models bigger than the card's 4 GiB run with their experts streamed from host
storage ([docs/offload.md](docs/offload.md), section 10). The card routes each token and computes
every expert, and it keeps the experts in per-layer slots in its DRAM. The host only copies
missing experts from a pool file into those slots, at the link's rate (section 10.1). Measured
on 2026-10-01 with build B (79c5707a), the card's own decode loop picking every token, 4-bit
experts, int8 head:
- **LFM2.5-8B-A1B** (8.5B parameters, 1.7B active): 10.6 tok/s over 160 tokens. 98.5% of expert
  uses hit the slots, and 5.2 MB streamed per token.
- **Qwen3.5-35B-A3B** (34.7B parameters, 3.0B active): 3.95 tok/s, with Hugging Face's 16
  greedy tokens. 62% of expert uses hit, and 153 MB streamed per token at 1.41 GB/s over PCIe
  (section 10.3).
- Both match the simulator bit for bit.

otpu-chat chats with both, and with gemma-4-26B-A4B-it (`--model lfm2-8b`, `qwen35-35b`,
`gemma4-26b`), with the same engine and settings. Each model's experts are packed once into a
pool file beside its checkpoint, and the chat checks the pool before it loads
([docs/offload.md](docs/offload.md), section 14).

4-bit weights ([docs/quant.md](docs/quant.md)) use FP4 values with two-level block scales, 4.25
bits per weight, and keep the LM head in int8 for accuracy. They cut the bytes per token by about
a third and raise decode speed by 40% (Qwen3.5) to 45% (Qwen3, LFM2), at a measurable cost in
perplexity that docs/quant.md reports per model.

The host is nearly out of the way. For LFM2 and Qwen3 the card runs one decode program compiled
once, which reads the position from a register and looks up its own embedding and RoPE rows, and
the logits stream back while the card is still running: the host adds 0.17 to 0.30 ms per
token on omarchy (0.45 to 1.3 ms on opentpu).
Qwen3.5 runs the same way for decode; its prefill still compiles each chunk's program on the host,
ahead of the card.

## How it works

```
  Kernels in ol              mlp, attention, full model layers
        |  @ol.jit
  Language + compiler        layouts, affine loop addressing, fusion
        |
  ISA                        8 x 32-bit words per instruction
        |
  ISA simulator  <======>  RTL          same bits, checked by the tests
  (Python)                 (SystemVerilog)
                            |  Vivado bitstream
                           FPGA card    Kintex-7 xc7k480t
                            |  PCIe
                           Host         otpu-chat, otpu-smi, otpu-lens
```

The machine is deliberately simple. A sequencer issues one instruction per cycle to a few
units: DMA moves data, the matrix unit multiplies int8 weights streamed from DRAM, the vector
unit does fp32 math, and a quantizer turns results back into int8. There is no cache and no
hidden scheduling: every data movement is an instruction, so a trace shows exactly where the
cycles go. [docs/isa.md](docs/isa.md) describes the whole instruction set.

A kernel looks like this:

```python
from opentpu import language as ol

@ol.jit
def mlp(h, gamma, w_gate, w_up, w_down, out, eps):   # simplified; see kernels/mlp.py
    x = ol.load(h)
    xs = ol.quantize(rmsnorm(x, ol.load(gamma), eps))
    g = ol.dot(xs, w_gate)
    u = ol.dot(xs, w_up)
    a = ol.all_gather(silu(g) * u)
    y = ol.all_gather(ol.dot(a, w_down))
    if ol.program_id() == 0:
        ol.store(out, x + y)
```

Because every data movement is an instruction, a trace of a run explains its speed. Lens, the
profiler, records a run from the RTL, the simulator or the card and opens it in the browser,
with a roofline, a timeline and per-instruction tables ([docs/lens.md](docs/lens.md)).

![Lens replaying a Qwen3 decode step on the floorplan](docs/img/lens-floorplan.gif)

*Lens replaying part of a Qwen3 decode step. Colours show what each unit is doing in each
cycle: busy, waiting on DRAM, or waiting on another instruction.*

## Try it

Everything except the card runs on a laptop.

```sh
pip install -e .
pip install pytest torch transformers
python3 -m pytest -q          # RTL tests also need Verilator 5

hf download LiquidAI/LFM2.5-230M --local-dir models/LFM2.5-230M
otpu-chat --model lfm2 --backend isa    # chat on the simulator
```

With a card, build the bitstream (`make bit` in [`boards/ypcb-00338`](boards/ypcb-00338)), load
it over JTAG, then run `sudo otpu-setup` and `otpu-chat --backend board`.
[docs/board.md](docs/board.md) walks through the bring-up.

| Command | What it does |
|:--|:--|
| `otpu-chat` | chat with Qwen3-0.6B, LFM2.5-230M (`--model lfm2`), Qwen3.5-0.8B (`--model qwen35`), LFM2-2.6B (`lfm2-2.6b`), SmolLM3-3B (`smollm3`), Phi-4-mini (`phi4-mini`) or Qwen3.5-2B / 4B (`qwen35-2b`, `qwen35-4b`), Gemma 4 E2B / E4B (`gemma4`, `gemma4-e4b`: the instruct checkpoints, gemma-4-E2B-it / E4B-it); MoE models bigger than the card with their experts streamed: LFM2.5-8B-A1B (`lfm2-8b`), Qwen3.5-35B-A3B (`qwen35-35b`), gemma-4-26B-A4B-it (`gemma4-26b`); a checkpoint without a chat template (a base model) only with `--raw` |
| `otpu-serve` | an OpenAI-style API server (`/v1/chat/completions`, `/v1/completions`, streamed or not; SGLang's `/generate`) for many clients at once: their contexts kept on the card and in host RAM / on disk (a prompt continuing a saved one feeds only the rest), their decode steps batched on the card for Qwen3 and the Llama-likes, every token picked on the card (Qwen3-0.6B: 78 tok/s with 4 clients, 25 alone); [docs/serve.md](docs/serve.md) |
| `otpu-smi` | temperature, power, DRAM bandwidth and per-unit utilization; `-l --csv` logs a time series |
| `otpu-lens` | record a run and open it in the profiler (`summary` prints the overview in the terminal) |
| `otpu-selftest`, `otpu-diag` | check that the card works |

## Validating against Hugging Face

`tools/validate.py` checks a device's greedy tokens and logits against a CPU golden: the same
checkpoint in Hugging Face transformers, fp32 on the CPU, with openTPU's quantization. The
golden's weights are the values the matrix unit multiplies (the model image's own quantizer,
in the formats you pick), and its activations are rounded to int8 per 128 values wherever the
device's quantizer rounds them: every matmul input, and in attention the query, K, V and the
softmax weights. The device is the ISA simulator, the RTL (Verilator) or the card, and
`--against` adds a second device that must give the same tokens and bit-identical logits. It
is measured on Qwen3-0.6B, LFM2.5-230M, Qwen3.5-0.8B and Gemma 4 E2B (base and instruct); the
MoE models are not supported.

```sh
python3 tools/validate.py --model qwen3                                    # ISA simulator, int8
python3 tools/validate.py --model lfm2 --wformat fp4 --head-format int8   # 4-bit layers
python3 tools/validate.py --model gemma4                                   # E2B-it: 16 GB (below)

# the RTL against the ISA simulator, bit for bit: slow, so one prompt and a few tokens
# (this one takes 4 minutes on a 16-core host, the Verilator build included)
python3 tools/validate.py --model lfm2 --backend rtl --against isa --tokens 3 "The capital of France is"

# the card against the ISA simulator, bit for bit, on the card host
otpu-lock -- python3 tools/validate.py --model qwen3 --backend board --against isa

# or only the card's run under the lock, and the rest on another host: the ISA simulator then
# runs in the configuration the card ran in
otpu-lock -- python3 tools/validate.py --model qwen3 --backend board --no-golden --save card.npz
python3 tools/validate.py --model qwen3 --against card.npz
```

Each prompt (eight by default, 16 tokens each) prints the device's continuation and the
goldens'. Then the device's own tokens are fed to the golden, so that every step compares the
same context, and the tool prints the top-1 agreement, the mean and largest KL divergence, the
largest logit difference and the lowest cosine. The summary has four rows:

| Row | What it is |
|:--|:--|
| device vs W+A | the device against the quantized golden: the check |
| device vs fp32 | the device against the plain checkpoint |
| W+A vs fp32 | what the quantization alone costs |
| W+A~ vs W+A | the golden against itself with its inputs nudged by one fp32 ulp: the floor |

The golden cannot round exactly as the device does: its sums, norms and exponentials differ in
the last bits. Once one int8 value rounds the other way, the difference spreads through the
layers after it. So on a real model the device sits about as far from the quantized golden as
the golden sits from itself after a one-ulp nudge, and a healthy device is near that floor.
With 4-bit weights the floor is far below the fp32 rows. Measured on the ISA simulator, with
the eight default prompts and 16 tokens each:

| Model | Weights | device vs W+A: top-1, KL | floor KL | device vs fp32: top-1, KL | W+A vs fp32 KL |
|:--|:--|--:|--:|--:|--:|
| LFM2.5-230M | int8 | 96.2%, 0.0038 | 0.0039 | 96.2%, 0.0055 | 0.0050 |
| LFM2.5-230M | 4-bit, int8 head | 94.6%, 0.0045 | 0.0041 | 80.6%, 0.152 | 0.157 |
| Qwen3-0.6B | int8 | 96.1%, 0.0088 | 0.0109 | 96.1%, 0.011 | 0.012 |
| Qwen3-0.6B | 4-bit, int8 head | 96.9%, 0.0123 | 0.0163 | 85.9%, 0.193 | 0.195 |
| Qwen3.5-0.8B | int8 | 96.1%, 0.0020 | 0.0017 | 97.7%, 0.0033 | 0.0029 |
| Qwen3.5-0.8B | 4-bit, int8 head | 96.9%, 0.0020 | 0.0021 | 88.3%, 0.076 | 0.077 |
| Gemma 4 E2B (base) | int8, 4-bit PLE table | 100.0%, 0.0036 | 0.0035 | 99.2%, 0.015 | 0.017 |
| Gemma 4 E2B (base) | 4-bit, int8 head and PLE table | 99.2%, 0.0029 | 0.0036 | 96.9%, 0.045 | 0.043 |
| Gemma 4 E2B-it | int8, 4-bit PLE table | 100.0%, 0.0071 | 0.0078 | 97.5%, 0.014 | 0.0085 |
| Gemma 4 E2B-it | 4-bit, int8 head and PLE table | 98.6%, 0.0095 | 0.0136 | 93.1%, 0.102 | 0.093 |
| Gemma 4 E2B-it | the base's mix, int8 head and PLE table | 100.0%, 0.0135 | 0.0075 | 98.6%, 0.028 | 0.036 |

KL is the mean KL(golden || device) in nats per token. The device's KL from the quantized
golden is 0.70 to 1.16 times the floor's, and its distance from fp32 is what the quantization
alone predicts. A run takes 2 to 14 minutes on a 16-core host (Gemma 4 E2B: 16 and 26, the
host shared with other jobs; E2B-it 8 to 14 on omarchy alone) and peaks at 2.5 GB (LFM2) to
16 GB (Gemma 4 E2B). Gemma 4 E2B-it, the instruct checkpoint otpu-chat runs (2026-10-09, tree
aa2166b1), answers most prompts in a few tokens and stops at its end of turn (`<turn|>`): its
rows have 71 to 81 positions against the base's 128, so one position weighs more. The mix's
1.80x is one position of 71, a near tie in `def fibonacci(n):`'s (KL 0.69, the floor's 0.17
there); without it, 0.75x. The prompts
are plain text after `<bos>`, as the base's, which the instruct tokenizer does not add
(`gemma4.text_ids`).

Qwen3's activation rounding costs more than the other models': its k_norm gains have outlier
channels (Qwen3-0.6B: up to 42 times their median), and K is rounded to int8 with one scale per
token, head and 128 values, so the other channels, the ones the attention scores depend on, were
left with a few levels. Its int8 W+A golden was 0.042 from fp32, against 0.0050 for LFM2.5-230M
and 0.0029 for Qwen3.5-0.8B. The image now moves the outliers' magnitude from K into q (a power
of two per channel in the q_norm and k_norm gains, which leaves q . K unchanged; docs/quant.md,
"K smoothing"): 0.012 in the table. On two fixed texts (2,046 positions, paired) it takes the
int8 W+A golden's KL from 0.059 to 0.015 and the 4-bit one's from 0.221 to 0.179, and the ISA
simulator's on 512 of them from 0.064 to 0.019 (int8) and from 0.228 to 0.195 (4-bit, int8
head). The 4-bit row's 128 greedy positions are too few to show that drop (each run is on its
own tokens, and a few positions dominate).

Gemma 4 runs in its image's formats, which follow the card's fit (E2B's int8 image keeps its
per-layer-embedding table in 4-bit). The golden takes its embedding rows from the LM head, as
the device gathers them, its per-layer embeddings from the device's PLE records, and it
compares the logits after the soft cap. E2B in fp32 is about 20 GB, so Hugging Face loads the
language model alone, without its 9.4 GB PLE table (the golden reads the rows it needs from the
checkpoint), and the golden keeps the bf16 checkpoint's weights in bf16, which is exact, and
widens them a matrix at a time for its fp32 passes. An E2B run peaks at 16 GB: give it a host
with 22 GB free.

A run passes when the device agrees with the quantized golden on at least 80% of the top-1
tokens and its mean KL is at most three times the floor's (`--min-top1`, `--kl-ratio`), and,
with `--against`, when both devices give the same tokens and bit-identical logits. The exit
status is 0 for PASS and 1 for FAIL, and `--json` writes every step for scripts.
`--weights-only` drops the activation rounding from the golden (then only the top-1 bound
holds), and `--no-fp32` skips the fp32 rows.

On the card (build 1025907f, 2026-10-07: `--no-golden --save` under the lock, `--against` on a
build host), all six runs of Qwen3-0.6B, LFM2.5-230M and Qwen3.5-0.8B, in int8 and in 4-bit
with an int8 head, gave the ISA simulator's tokens and bit-identical logits on every prompt
(0 ulp over 103 to 128 steps a run). The card's mean KL from the quantized golden was 0.94 to
1.39 times the floor, with 94.5% to 97.7% top-1 agreement. Qwen3-0.6B int8's KL from fp32 on
the card went from 0.052 (build 84989047, before K smoothing) to 0.012.

## Where to start reading

1. [docs/isa.md](docs/isa.md): the instruction set. Everything else is built on it.
2. [`opentpu/kernels`](opentpu/kernels) and [docs/compiler.md](docs/compiler.md): how a kernel
   becomes instructions.
3. [`opentpu/isasim.py`](opentpu/isasim.py): the simulator, which is the spec.
4. [`rtl/`](rtl): the hardware, starting from [`rtl/top/otpu_top.sv`](rtl/top/otpu_top.sv).
5. [docs/lfm2.md](docs/lfm2.md), [docs/qwen35.md](docs/qwen35.md), [docs/llama.md](docs/llama.md),
   [docs/benchmarks.md](docs/benchmarks.md): whole models and where their cycles go.
6. [docs/board.md](docs/board.md): the physical card, from clocks to PCIe.
7. [docs/targets.md](docs/targets.md): how one design builds for several boards and chips (a
   target file per build: `targets/*.toml`).

## What's next

- **The last few percent of DRAM.** Decode is bound by DRAM efficiency: it reads 82 to 85% of the
  DDR3-1066 peak. Work on the LiteDRAM path's efficiency is under way.
- **Timing margin and area.** The design closes 133.33 MHz, the clock at which the 128-byte port
  matches the two DDR3 channels, but only just (WNS +0.032 ns). A tournament of Vivado runs keeps
  working on its margin and area. Decode is bound by DRAM, so a faster clock mostly helps prefill.
- **Faster prefill.** The four-column systolic matrix unit is in the production image; prefill is
  still limited by the matrix unit's multiply rate.

- **More targets.** The design builds from target files (`targets/*.toml`,
  [docs/targets.md](docs/targets.md)): the YPCB-00338 in production, the BCU1525 (Virtex
  UltraScale+ VU9P, four DDR4 DIMMs) being brought up, and ASICs, starting with NanGate45 and
  OpenROAD for area, clock and power numbers.

## Contributing

Issues and pull requests are welcome, and most of the work needs only Python and Verilator, not
an FPGA. Changes to the ISA, the simulator or the RTL must keep `python3 -m pytest -q` passing,
and performance claims should say how they were measured.

## License

Apache License 2.0. See [LICENSE](LICENSE).
