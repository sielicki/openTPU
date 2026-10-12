Executable driver and guard draft; NOT imported, compiled, tested, extracted,
hashed against large artifacts, or run during the live checkpoint source freeze.
Install check_sparkle_se_tail_product.py, se_tail_product_inventory.py and
test_sparkle_se_tail_product.py together in tools only after review/freeze ends.

The initial PLAN warning about historical log identity has been corrected.
The driver pins the authenticated exact immutable parent replay at SHA236c3c00…;
its original82,820bit theorem need not be re-solved for provenance. Independent
source-derived state mapping and initialization inspection precede legacy alias
grouping. The grouping is reconstructed through explicit bit correspondence,
then the entire serialized transition artifact must match the original
authenticated steps hash. All RAM, next-state and FP inputs remain covered.
Exact extraction/flatten/proof scripts and hierarchy-to-blackboxes transform
are audited, including original u_pad identity. A mismatch fails closed.
All original initializer aliases are captured before cut insertion or lane
normalization; preexisting cut netnames/ports are rejected and the resulting
bit constraints must remain identical. Guards exercise an initializer only on
a colliding cut alias and an alias erased by a corrupted lane bridge.

The driver newly compiles current SeTail code and three actual circuit faults:
o_v inversion, ub write-data bit flip, and um0 cen inversion. Current none.sv
must match all three authenticated module bodies, attributes and directives.
Mutation validation deliberately selects one real affected output cone per
mutation from the complete parent-state miter. This keeps SAT small and is
reported as narrow fault sensitivity; the reused positive parent theorem stays
exhaustive. All three require actual failing models, not tool errors.

For FP applicability, every actual reached original leaf is saved as a tiny
concrete subgraph with its actual native counterpart. Forty-six independent
init/output/step checks (27mul2,19add4) avoid guessing elaborated latency from
module names or erased override parameters. Complete Q/D/init/clock/direction
audits and Moore-output cone checks make the composition noncircular. The
selected existing full-state FP theorem and native source/context are also
authenticated; no after-fill FP claim is consumed.

Native local register initialization is read from all aliases before removal.
76,160 RAM bits remain shared arbitrary values; they are never silently zeroed.
The initialized product count is89,824 retained synthesized bits. Four dq_n
diagnostic-only source bits are explicitly excluded and remain unproved. No
simulation diagnostic equivalence, wholeVPU or production-binding claim is
made. An actual dq_n cone extraction/proof would be a separate additive task.

First-run concerns requiring actual bounded evidence:

- Slang may retain explicit LAT overrides on a leaf cell. The current draft
  intentionally accepts only empty elaborated overrides; inspect and add an
  exact independently justified representation if needed, not a wildcard.
- The exact parent byte replay may expose benign grouping/serialization drift.
  Preserve the failed result and explain any bridge; do not replace full
  byte/bit correspondence with a bitcount or a selected-output comparison.
- The251MB flat JSON can dominate parsing memory. The driver exposes the
  exclusively owned parent graph in-place with complete Q/D/clock/cell/coverage
  checks, avoiding the generic helper's deepcopy. Its entire resulting byte
  stream must equal the authenticated transition artifact. All big graphs are
  released before compiling/solving. If parsing alone exceeds3GiB, a streamed
  partition audit remains necessary. Never increase or bypass the cap.
- Actual hierarchy paths/identity-pad shapes and compiled mutation constructor
  shapes have not been checked by execution. They must fail closed if changed.
- Generic ProductComposition.lean is supporting logical reasoning, not a
  concrete kernel-checked instantiation or a checked SAT/compiler certificate.

Run guards with the256MiB bounded gate first. Run the driver in a fresh output
directory with the default3GiB gate, one job, zero swap, compiler1. The driver
preserves an incomplete receipt after any failed obligation; only a completed
run can claim initialized synthesized product refinement.
Newly consumed/generated artifacts are streamed into the content-addressed
archive immediately, including solver scripts and logs from finally blocks,
so a later interrupted stage does not defer their preservation until success.
