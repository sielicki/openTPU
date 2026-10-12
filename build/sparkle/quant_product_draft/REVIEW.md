# Whole Quant128/8 composition draft — UNEXECUTED

Files are persistent staging only. No import, syntax check, guard test, extraction,
Lean build or solver has been run. Install/review before executing under the
single `sparkle_bounded.py` gate. Fresh output directory required.

The driver closes a 28,676-bit synchronous product: 17,967 parent bits (16,960
arbitrary memory bits and 1,007 defined register bits), 4,290 reader bits, 2,308
writer bits and 4,111 scaler bits. It authenticates the original parent receipt
and its historical success-log hash from `quant_board_qualification`; leaf proofs
are authenticated with all input closures and exact positive SAT commands.

The parent is independently remapped without omitted Q/D bits. All original init
aliases are read before legacy netname filtering. Defined reference bits must
match defined native bits; unspecified RAM remains shared arbitrary `?` witness
bits. Cut ports must match the proven leaf interfaces using actual directions,
clocks and resolved parameterizations, and cannot alias another driver. Leaf
raw graphs are transformed anew, compared with authenticated step graphs and
initial witnesses, and checked for state-only output cones. Full module bodies,
attributes and incoming directives match into the parent and fresh compiled Lean.
Reference inline readers/writers are reconstructed from exact RTL anchors;
reference scaler and parent helper constants are checked independently.

Historical extraction/flatten scripts ARE included in the actual parent input
hashes and are authenticated and checked exactly. An earlier inference from the
current generator source incorrectly suggested they were missing; inspection of
the authoritative receipt corrected that. The authenticated full parent theorem
is reused after independent hierarchy/boxes/flat/steps and initialization audits.
Real production completion, buffer-write and reader-enable mutations must produce
SAT counterexamples with exit status 1. No miter-only mutations.

Induction: leaf current outputs agree independently of current inputs (Moore
check). Feed those equal outputs to the arbitrary-output parent theorem: all
external outputs, next parent state and every child input agree. Apply the three
leaf step theorems to preserve their relations. The separate initialized witnesses
establish the base, including seven scaler negative-zero k0 registers. This is
existential refinement of reference unspecified initialization, not equality from
independent arbitrary initial states.

First-run risks requiring audit, not weakened checks:

- Slang parameter-default dictionaries and legacy `$` specialization naming may
  differ from draft assumptions. Inspect actual metadata; do not erase overrides.
- The conservative Moore check may encounter undef constants or aliases that
  require an exact cone argument. Do not replace it with output names or claims.
- Source-only init RAM count and strict child-driver alias check need confirmation
  against actual graphs; do not force undefined values to zero.
- Production parent mutation runtime/peak is unmeasured. They partition all FP
  leaves, but retain all parent storage and every boundary obligation.
- Historical file/archive closure may refer to pre-restart tool locations. Fail
  closed on missing evidence; resolve authentic archives, never repin to new files.
- Draft tests cover failure modes but have not run. No success claim is warranted.

Example (after root releases gate and restores env):

```
source /tmp/opentpu-test-env.sh
python3 tools/sparkle_bounded.py -- python3 -m pytest -q build/sparkle/quant_product_draft/test_sparkle_quant_product.py
python3 tools/sparkle_bounded.py -- python3 build/sparkle/quant_product_draft/check_sparkle_quant_product.py --output build/sparkle/quant_product_first
```

Remaining beyond this proof: production whole-Quant consumer binding, other Quant
configurations, whole-board initialization, reference-undefined behavior and
vendor/CDC/physical signoff. No global startup or 1:1 completion claim.
