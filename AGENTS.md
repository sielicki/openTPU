# Resource limits for this workspace

The user has experienced repeated host OOMs during this port. Treat memory safety
as a requirement, not a best-effort scheduling preference.

- Run builds, simulations, proof solvers, netlist extraction/transformation, and
  large-artifact processing through `python3 tools/sparkle_bounded.py -- COMMAND`.
  It enforces one heavy job across all agents, a 3 GiB process-tree RAM ceiling,
  zero swap, and a two-CPU quota. Descendants run as the ordinary workspace user.
- A busy gate returns 75. Wait for the owning job; do not start an unbounded copy.
  If the gate or its verified cgroup limits are unavailable, keep heavy work
  stopped and do lightweight code work. Do not fall back to free-memory polling.
- Do not raise the ceiling or bypass the gate to make a proof pass. Reduce the
  proof representation's memory use while preserving its complete obligations.
- Keep compiler parallelism at one. Do not invoke external build daemons to
  move expensive work outside the bounded process tree.
- Hash and archive large artifacts with streaming reads. Avoid whole-file
  copies and release parsed netlists before launching a solver.
- Preserve interrupted/limited-out results as incomplete, with their inputs and
  logs. Resume immutable proof inputs when valid instead of repeating extraction.
- `OTPU_TEST_RESOURCE_LIMITS=1 python3 -m pytest -q
  tests/test_sparkle_bounded.py` is the sole exception to the outer gate: these
  small integration tests exercise competing 64 MiB scopes and an intentional
  scope-local allocation failure. Run them only when no heavy job is active.
