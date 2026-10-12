Conditional two-state lifting argument (independently reviewed; actual bounded
certificate execution still pending; no new theorem result has run).

1. The old authenticated script constructs gold/gate equivalences on the entire
   transition interface and finishes with `equiv_status -assert`. The new bridge
   derives that exact whole steps artifact from independently mapped physical
   Q/D and compares the entire graph. Thus no output or mapped D obligation is
   omitted or replaced by a sampled/reset/fill predicate.
2. For arbitrary two-state external inputs and the757 mapped current-state
   bits, the totality certificate requires every external output and every
   mapped D bit on BOTH sides to have a total two-state combinational cone.
   It checks exact pin/direction/width/signedness contracts, rejects live X/Z,
   partial/unsupported operators and cycles, and enforces unique input and cell
   drivers. The177 omitted reference Q bits cannot reach any of these cones.
3. On this domain, the undefined-value relaxation in `equiv_simple -undef`
   cannot turn a differing defined gold/gate bit into an allowed match: both
   compared expressions are always defined. Consequently the authenticated
   all-output/next-state result implies ordinary two-state output and mapped
   next-state equality for all equal mapped states and equal inputs.
4. Every actual native Q initializer is audited before alias insertion/pruning.
   The mapped reference witness equals it and satisfies every actual reference
   initializer. Unmatched reference Q receives a separate constraint-respecting
   witness. Equality therefore holds at cycle0, without an asserted reset.
5. Induction on common clock edges uses step3 to preserve mapped equality and
   output equality. Unmatched reference state may evolve independently because
   the total cone closure excludes it from all observed and retained-D roots.
   Mealy max outputs are included with shared current inputs; a Moore premise
   is neither needed nor claimed.

If all five checks succeed, the remaining limitation is NOT an unresolved
arbitrary-state lemma. It is the explicit domain/trust boundary: synchronous
two-state RTLIL execution, actual native initializers, existential compatible
reference initialization, original extracted max interface, trusted extraction/
Yosys SAT/RTLIL operator semantics and source-to-RTL compilation. It does not
cover independent arbitrary starts, X/Z-valued inputs, four-state simulation,
physical power-up, whole-VPU composition, or a Lean-kernel proof of Yosys.

If totality fails, do not issue initialized two-state refinement. Preserve the
exact failed operator/literal as a missing obligation; a future range/onehot/
definedness proof may discharge it without narrowing input traffic. The current
strict whitelist intentionally rejects even safe special cases of partial ops.

Independent reviewer /root/scale_binding approved the quotient/totality logic
read-only, including uniqueness guards, with no blocking issue. Driver success
promotion now remains gated on the complete real certificate, source equality,
historical authentication and required actual mutation guards. No claim changes
merely because this reasoning document exists.
