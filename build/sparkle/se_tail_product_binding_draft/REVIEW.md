Draft only; no imports, tests, builds, or proofs executed.

Install checker in tools/ and guards in tests/ after independent review.
Use the normal bounded gate for pytest and binder execution. The binder hashes
and archives the 992-input theorem closure, so its execution is heavy work even
though it launches no solver. Require a fresh --output directory.

Pins SE-tail attempt1 summary e2c3abb46217bfb10e0d74ee5083d715baa06c01b07844d5a0a48e1b056760ec.
Checks complete 82,820 parent witness (76,160 arbitrary shared RAM bits), all
46 concrete FP children/7,004 bits with complete zero init fields, exact Moore
outputs, directions/widths/parameters, all 138 positive logs and three actual
compiled mutation logs/CEX. Reauthenticates full historical parent replay with
its exact script/steps/log provenance rather than rerunning the large theorem.

All three concrete module bodies including attributes and incoming directives
must match each Gen1/Gen2/CLI assembly and its historical coverage/specialization
receipt. Checks every one of 47 reached node IDs independently, all46 child
edges, and the enclosing stream-tail datapath edge. Parent production top is
LANES8/VPU_CL2; presence of the concrete stream-tail under the authenticated
datapath binds the streams=true production configuration. Compiled unparameterized
tail equality binds inputLatency7/treeDelay1 rather than inferring them from
names or top-level parameters.

Claim: exact production applicability of initialized retained synthesized
SE-tail product refinement. Does not include dq_n's four diagnostic source
bits/FIFO diagnostics, independent arbitrary initial-state equivalence, whole
VPU/board composition, reference-undefined behavior, or physical signoff.
