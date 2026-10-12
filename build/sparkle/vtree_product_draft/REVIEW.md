Draft only: no imports, guard runs, Lean compilation, graph extraction, hashes,
or solver calls were executed while preparing these files. Repository source
files and runtime receipts are unchanged.

Candidate exact production scope: LANES8/LA4, all 3,646 bits per design:
1,704 parent + nine concrete add4 × 191 + one add2 × 223. All fields equal;
there are no conditional multiplier fields. The map covers both packed32-bit
halves of reference td[2:1], every enabled delay, reset register and add2 copy.
Raw init is read before exposing steps. Every native state bit must have a
defined init; reference-defined bits must agree with the explicit witness.
expose_steps rejects missing/excess/aliased Q bits, malformed D, unsupported
clocking, opaque arithmetic and formal assumption cells. No pruning is done.

The old VTree proof does NOT assume collision-free traffic. Its assumptions are
only first-sample equal state and, in controller-only mode, equal abstract FP
returns. Four assumptions reported in some enclosing historical runs therefore
must not be relabeled four VTree scheduling assumptions without exact evidence.
This new proof uses neither temporal assumptions nor abstract returns.

Reference scheduling restrictions occur in `ifndef SYNTHESIS simulation $fatal
checks. The new wrapper exposes their exact two predicates: row-level conflict
and any pair among the four lane strobes. Equality of the diagnostic is proved
for arbitrary rst/en/cap/row_last/sub/pacc, INCLUDING collisions. The full
datapath/control equality does not mean colliding schedules compute valid
mathematical reductions. It preserves original synthesized behavior. This is
two-state synthesized equivalence, not four-state simulator equivalence.

Diagnostic hardening: audit_collision_source pins the exact terminal RTL block,
including both collision assertion predicates, SYNTHESIS guard, complete
LN2/SH2 conditional, and both fatal calls. It additionally checks the complete
preprocessor directive inventory and NP/RL/LN2 specialization anchors. The
wrapper invokes this audit directly, and the receipt records its interpretation.
Changing an excluded-from-synthesis diagnostic therefore fails before proof
instead of silently comparing against a stale manually regenerated predicate.
New negative guards alter row threshold, row conflict, enable, onehot polarity,
lane strobe, SH2 branch, guard polarity, extra branch, and NP/RL/LN2 constants;
an additional guard checks that wrapper generation cannot bypass the audit.
Strict formatting changes intentionally also demand review. These guards remain
unexecuted pending the resource gate.

Native generation uses actual Physical.vtreeHints and Physical.addHints,
including the precise keep=true on add2 result_copy. Existing authenticated
add4/add2 proof bodies are bound with that one existing attribute bridge.
Fresh compiled-Lean mutations flip root_o, bypass td0_1 enable, remove rsr
reset, and flip schedule_collision. Each must produce an actual SAT model
falsifying the checked output/step property; mutation errors do not count.

The draft is independent of the old VTree behavior proof. It authenticates FP
source/theorem provenance but solves the full concrete product afresh; no
pipeline-fill restriction or previous parent theorem is assumed. All current
source closure, generator binaries, extraction/SAT inputs, logs and witness
are archived. Failed attempts remain incomplete.

First-run checks / unresolved execution details:

- Verify read_slang's exact flattened packed td and hierarchy names against the
  complete Q/D inventory. Expected names follow RTL declarations; do not prune
  bits to make a name mismatch pass.
- Verify actual emitted reference/native initialization: expected native3646,
  reference0, but no claim is made until actual graph audit succeeds.
- Confirm Physical register-hint API and mutation target shapes by compiled
  execution. Missing/changing targets intentionally fail closed.
- read_slang synthesis behavior must continue suppressing original simulation
  $fatal instrumentation. If instrumentation remains, unsupported graph cells
  must fail closed; do not convert them into schedule assumptions.
- This proof does not require Moore classification because all components are
  concretely flattened. A later compositional consumer must mechanically audit
  root/root_o/root_v cones and handle the Mealy diagnostic separately.
- A production binding to Gen1/Gen2/CLI remains separate after proof succeeds.

Execution after source freeze ends: install the driver and guards in tools,
run guards inside a 256MiB bounded job, then run a fresh output directory with
the default 3GiB bounded gate. No need to rerun old VTree configurations.
