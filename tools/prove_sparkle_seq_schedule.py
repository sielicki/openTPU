"""Prove native window selection against the original sequencer's combinational RTL.

Window state, age/dependency matrices, unit handshakes, completion head slots and
the release slot/pending bit are unrestricted. Queue storage and its pointers are
outside this local proof; their selected values are explicit inputs on both sides.
"""
from pathlib import Path
import argparse
import json
import re
import subprocess

from prove_sparkle_seq_logic import ROOT, hashes

WORK = ROOT / "build/sparkle/formal_seq_schedule"
CONFIGS = [2, 4, 8, 16, 32]


def harness(slots):
    source = (ROOT / "rtl/seq/otpu_seq.sv").read_text()

    def section(start, end):
        if source.count(start) != 1 or source.count(end) != 1:
            raise RuntimeError("reference window proof extraction needs updating")
        return source.split(start, 1)[1].split(end, 1)[0]

    functions = section("  localparam int TAW = 16;", "  // window")
    completions = section("  // ---- completions this cycle\n", "  // ---- free slot")
    free = section("  always_comb q_fp = fp_ranges(q_cmd, q_pr, D, S);\n", "  // ---- loop-end handling")
    starts = section("  logic [WIN-1:0] same_started [NUNITS];\n", "  // MXU release:")
    release = section("  wire          can_rel  = ", "\n\n  // Each unit's command")
    # Expose queue read results/pending as proof cutpoints, identically on both sides.
    needle = "(uq_r != uq_t[U_MXU])"
    if release.count(needle) != 1:
        raise RuntimeError("reference release queue interface changed")
    release = release.replace(needle, "rel_pending")
    sw = slots.bit_length()-1
    return f"""module seq_schedule_miter import otpu_pkg::*; (
  input wire [{slots-1}:0] sv, sstarted,
  input wire [{slots*5-1}:0] soh_in,
  input wire [{slots*slots-1}:0] sdep_in, sdepd_in, older_in,
  input wire [4:0] urdy, ustart, udone,
  input wire [{5*sw-1}:0] head_slots,
  input wire [{sw-1}:0] rel_slot,
  input wire rel_pending,
  input wire [321:0] c_fp,
  input wire [{322*slots-1}:0] sfp_in,
  output wire [12:0] ok
);
  localparam int WIN={slots}, SW={sw}, TAW=16;
{functions}
  wire [4:0] soh[WIN];
  wire [WIN-1:0] sdep[WIN], sdepd[WIN], older[WIN];
  fps_t sfp[WIN];
  for(genvar i=0;i<WIN;i++) begin
    assign soh[i]=soh_in[5*i+:5];
    assign sdep[i]=sdep_in[WIN*i+:WIN];
    assign sdepd[i]=sdepd_in[WIN*i+:WIN];
    assign older[i]=older_in[WIN*i+:WIN];
    assign sfp[i]=sfp_in[322*i+:322];
  end
  wire [SW:0] uq_h[NUNITS];
  wire [SW-1:0] uq[NUNITS][WIN];
  for(genvar u=0;u<NUNITS;u++) begin
    assign uq_h[u]='0;
    for(genvar i=0;i<WIN;i++) assign uq[u][i]=head_slots[SW*u+:SW];
  end
{completions}
  logic have_free;
  logic [SW-1:0] free_slot;
  logic [WIN-1:0] ndep, ndepd;
{free}
  logic [WIN-1:0] same_started[NUNITS];
{starts}
  wire can_rel = {release}
  wire [WIN-1:0] n_fin, n_deps, n_dram, n_mrdy, n_crdy;
  wire n_free, n_rel;
  wire [SW-1:0] n_free_slot;
  wire [5*WIN-1:0] n_same, n_sel;
  wire [5*SW-1:0] n_starts;
  wire [4:0] n_can, n_cand;
  otpu_seq_schedule_sparkle native(.sv,.sstarted,.soh(soh_in),.sdep(sdep_in),
    .sdepd(sdepd_in),.older(older_in),.urdy,.ustart,.udone,.head_slots,.rel_slot,
    .rel_pending,.c_fp,.sfp(sfp_in),.fin(n_fin),.free(n_free),.free_idx(n_free_slot),
    .deps(n_deps),.dram_deps(n_dram),.same(n_same),.sel(n_sel),.starts(n_starts),
    .can(n_can),.candidates(n_cand),.mxu_ready(n_mrdy),.coll_ready(n_crdy),.can_rel(n_rel));
  wire [4:0] same_eq, sel_eq, starts_eq;
  for(genvar u=0;u<5;u++) begin
    assign same_eq[u]=n_same[WIN*u+:WIN]==same_started[u];
    assign sel_eq[u]=n_sel[WIN*u+:WIN]==sel[u];
    assign starts_eq[u]=n_starts[SW*u+:SW]==start_slot[u];
  end
  assign ok={{n_rel==can_rel, n_crdy==crdy, n_mrdy==mrdy, n_cand==cand_any,
    n_can==can_start, &starts_eq, &sel_eq, &same_eq, n_dram==ndepd, n_deps==ndep,
    n_free_slot==free_slot, n_free==have_free, n_fin==fin}};
endmodule
"""


def prove(slots, mutation=False):
    work = WORK / str(slots)
    work.mkdir(parents=True, exist_ok=True)
    name = "mutation" if mutation else "proof"
    source = work / ("mutated.sv" if mutation else "native.sv")
    if mutation:
        original = (work / "native.sv").read_text()
        changed, count = re.subn(r"(assign _gen_can_start1 = )(.+);",
                                r"\g<1>~(\g<2>);", original, count=1)
        if count != 1 or changed == original:
            raise RuntimeError("window mutation target missing")
        source.write_text(changed)
    else:
        subprocess.run([str(ROOT / ".lake/build/bin/opentpu-gen"), "seq-schedule",
                        str(slots), str(source)], cwd=ROOT, check=True)
        (work / "miter.sv").write_text(harness(slots))
    script = work / f"{name}.ys"
    script.write_text(f"""read_slang --top seq_schedule_miter rtl/top/otpu_pkg.sv {source.relative_to(ROOT)} {work.relative_to(ROOT)}/miter.sv
prep -top seq_schedule_miter -flatten
opt -full
sat -prove ok 8191 -verify -show-inputs -show-outputs -dump_vcd {work.relative_to(ROOT)}/{name}_failure.vcd
""")
    inputs = [source, script, work / "miter.sv", ROOT / "rtl/top/otpu_pkg.sv",
              ROOT / "rtl/seq/otpu_seq.sv", ROOT / "OpenTPU/SeqSchedule.lean",
              ROOT / "OpenTPU/SeqLogic.lean", ROOT / "OpenTPU/Circuit.lean",
              ROOT / "OpenTPU/Generate.lean"]
    before = hashes(inputs)
    log = script.with_suffix(".log")
    result = subprocess.run(["yosys", "-Q", "-T", "-s", str(script)], cwd=ROOT,
                            capture_output=True, text=True, timeout=600)
    log.write_text(result.stdout + result.stderr)
    if hashes(inputs) != before:
        raise RuntimeError("window proof inputs changed during proof")
    if mutation:
        if result.returncode == 0 or "proof did fail" not in result.stdout + result.stderr:
            raise RuntimeError(f"window mutation not rejected by SAT; see {log}")
        print("PASS window checker self-test: incorrect MXU start rejected", flush=True)
    else:
        if result.returncode or "SAT proof finished - no model found: SUCCESS!" not in result.stdout:
            raise RuntimeError(f"window equivalence failed; see {log}")
        print(f"PASS sequencer WIN={slots}: completion/dependency/start/release selection", flush=True)
    return {"slots": slots, "input_sha256": before, "log": str(log), "mutation": mutation}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    summary = WORK / "summary.json"
    summary.write_text(json.dumps({"status": "running"}) + "\n")
    try:
        with (WORK / "build.log").open("w") as log:
            subprocess.run(["lake", "build", "OpenTPU", "opentpu-gen"], cwd=ROOT,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
        proofs = [prove(w) for w in CONFIGS]
        mutation = prove(CONFIGS[0], True) if args.self_test else None
        summary.write_text(json.dumps({"status": "passed", "proofs": proofs,
            "scope": "combinational window selection; unrestricted inputs and queue read cutpoints",
            "yosys": subprocess.check_output(["yosys", "-V"], text=True).strip(),
            "self_test": mutation}, indent=2) + "\n")
    except BaseException as error:
        summary.write_text(json.dumps({"status": "failed", "error": str(error)}) + "\n")
        raise


if __name__ == "__main__":
    main()
