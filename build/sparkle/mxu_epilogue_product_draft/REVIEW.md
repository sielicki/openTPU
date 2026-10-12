# Production MXU epilogue product — validated first attempt

Exact D128/C4/IMPL2/CL16, LM2/LA4. Installed in tools/ and validated under the
bounded gate. All 25 guard tests passed; attempt1 passed initialization, output,
and complete next-state checks plus all three real hardware mutation checks.
Receipt: build/sparkle/mxu_epilogue_product/attempt1/summary.json.
Runtime was 198.857 seconds, peak 3 GiB, 8,496 memory-limit reclaim events and
zero OOM events. Native initialization defines all 8,197 bits; the reference
defines none, so this remains an existential reference initialization witness.
The authenticated driver retains its original staging docstring; the receipt's
passed status and six concrete solver results record the completed validation.

The driver independently names all 4,523 local state bits, eight mul2 instances
(1,000bits) and fourteen add4 instances (2,674bits): total8,197. It flattens the
actual concrete original and native FP implementations with no arithmetic cuts
or state pruning, then exposes every retained Q/D bit. The relation is equal
parent and adder state; multiplier m_sv fields are conditionally equal when their
shared m_sp is1. All other multiplier fields are equal.

Actual native initialization is read before modifying aliases; every native bit
must have a defined initializer, and all defined original bits must agree. A
concrete reference witness establishes the base. No all-zero or reset/fill premise
is hardcoded. init_ok/output_ok/step_ok cover every output and next-state field.

Reference extraction reuses the existing exact parent wrapper recipe but restores
its proof_mul/proof_add calls to actual otpu_fmul/otpu_fadd latency2/4 instances.
It asserts exactly two mul declarations and four add declarations in the source
loops, exact production constants, and no remaining blackbox/proof calls. The
original MXU/FP/package files and recipe are hashed. Fresh emitted native modules
are compared to authenticated corresponding-state FP leaf definitions including
attributes/directives and the exact module-name normalization. The old epilogue
receipt is used only for configuration/state-inventory/source cross-checking;
fresh full product proofs do not assume its historical after-fill FP theorem.

Compiled Lean emits actual circuit mutations with exactly one AST hit each:

- rowr output XOR bit0;
- im0 register enable/hold bypass;
- mt synchronous reset removed.

Positive obligations have arbitrary inputs/en_c/reset. Negative hold/reset controls
use en_c0 with rst0/rst1 respectively. Every negative requires exit1, explicit SAT
proof failure and a concrete model whose checked property is0. Source files,
compiled runner, linked native inputs, tools/plugins, extracted graphs, SAT
scripts/logs and counterexamples are archived; incomplete attempts stay incomplete.

First-run risks to investigate without weakening scope:

- Exact original flattened names for conversion and packed-array state must match
  the independently listed pairs; e.g. g_d2f.im[j], rowr_arr[j], and g_comb[j].u_c.
- Slang may preserve/eliminate constant or unused aliases differently under full
  concrete FP flattening; all physical Q bits must remain accounted for. No
  pruning fallback is included.
- Original/native init aliases may conflict or be absent. Inspect actual graphs;
  do not replace missing/unknown native init with zero or ignore defined bits.
- Generated AST mutation patterns must match real clocked/reg statements once.
  A changed shape fails before emission instead of silently skipping a mutation.
- Initial reference wrapper restores known reference calls by exact anchored
  names/counts; any future RTL helper reorganization needs a new source audit.
- Full product SAT memory is unmeasured. If a3GiB-limited attempt fails, preserve
  its immutable extraction and split the complete next-state/output conjunction
  into exhaustive sub-obligations under the SAME full relation and shared inputs.
  Check exact union coverage of all fields, then reuse the extracted inputs. Do
  not drop FP implementations, state bits or configs; do not raise the limit.

Run guards under256MiB after root releases the gate, then the exact full product
under the default3GiB cap. The production assembly binder is a separate next step.
A passing epilogue does not close outer MXU RAM/control, DSP initialization, whole
MXU/system startup, vendor behavior or physical signoff.
