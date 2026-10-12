"""Exhaustively compare each native sequencer combinational stage with the RTL.

No legal-instruction or reachable-footprint assumptions are used. Local reference
functions are copied verbatim into the proof-only harness; generation never reads
reference HDL. Separate stage ports avoid assuming the result of a prior stage.
This is not yet a proof of the sequencer's stateful fetch/dispatch controller.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build/sparkle/formal_seq_logic"
CONFIGS = [(32, 1), (64, 2), (96, 3), (128, 4)]
STAGES = ["unit", "cmd", "ops", "part", "prod", "fp", "seg", "conf"]


def hashes(paths):
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def harness(depth, slices):
    source = (ROOT / "rtl/seq/otpu_seq.sv").read_text()
    # These exact delimiters intentionally fail closed if the reference is reorganized.
    def section(start, end):
        if source.count(start) != 1 or source.count(end) != 1:
            raise RuntimeError("reference sequencer proof extraction needs updating")
        return source.split(start, 1)[1].split(end, 1)[0]

    ranges = section("  localparam int TAW = 16;", "  // window")
    decode = section("  logic [31:0] iw [8];", "  int dunit;")
    return f"""module seq_logic_miter import otpu_pkg::*; (
  input cmd_t cmd,
  input fpo_t ops_in,
  input fpp_t part_in,
  input fpm_t prod_in,
  input fp_t fp_in,
  input logic [321:0] seg_n, seg_e,
  input logic [255:0] ir,
  input logic [511:0] regs,
  output wire [7:0] ok
);
  localparam int TAW = 16;
{ranges}
  logic [31:0] R [16];
  for(genvar i=0;i<16;i++) assign R[i]=regs[32*i+:32];
  logic [31:0] iw [8];
{decode}
  wire [31:0] unit_out;
  cmd_t cmd_out;
  fpo_t ops_out;
  fpp_t part_out;
  fpm_t prod_out;
  fp_t fp_out;
  fps_t seg_out;
  wire [1:0] conf_out;
  otpu_seq_logic_sparkle native(.*);
  assign ok[0] = unit_out == unit_of(cmd.op);
  assign ok[1] = cmd_out == dcmd;
  assign ok[2] = ops_out == fp_ops(cmd, {depth}, {slices});
  assign ok[3] = part_out == fp_part(ops_in);
  assign ok[4] = prod_out == fp_sum(part_in);
  assign ok[5] = fp_out == fp_ranges(cmd, prod_in, {depth}, {slices});
  assign ok[6] = seg_out == fp_seg(cmd.op, fp_in);
  assign ok[7] = conf_out == conf_s(fps_t'(seg_n), fps_t'(seg_e));
endmodule
"""


def prove(cfg, mutation=None):
    depth, slices = cfg
    work = WORK / f"{depth}_{slices}"
    work.mkdir(parents=True, exist_ok=True)
    name = "proof" if mutation is None else f"mutation_{mutation}"
    source = work / ("native.sv" if mutation is None else f"{name}.sv")
    if mutation is None:
        subprocess.run([str(ROOT / ".lake/build/bin/opentpu-gen"), "seq-logic",
                        str(depth), str(slices), str(source)], cwd=ROOT, check=True)
        (work / "miter.sv").write_text(harness(depth, slices))
    else:
        original = (work / "native.sv").read_text()
        target = "fp_out" if mutation == "range" else "conf_out"
        # Corrupt a real output, rather than the checker. Both payload and conflict
        # mutations must elaborate and fail SAT; a compilation error is not a pass.
        width = 403 if mutation == "range" else 2
        changed, count = re.subn(rf"(assign {target} = )(.+);",
                                rf"\g<1>(\g<2>) ^ {width}'d1;", original, count=1)
        if count != 1 or changed == original:
            raise RuntimeError("sequencer mutation target missing")
        source.write_text(changed)
    script = work / f"{name}.ys"
    script.write_text(f"""read_slang --top seq_logic_miter rtl/top/otpu_pkg.sv {source.relative_to(ROOT)} {work.relative_to(ROOT)}/miter.sv
prep -top seq_logic_miter -flatten
opt -full
sat -prove ok 255 -verify -show-inputs -show-outputs -dump_vcd {work.relative_to(ROOT)}/{name}_failure.vcd
""")
    inputs = [source, script, work / "miter.sv", ROOT / "rtl/top/otpu_pkg.sv",
              ROOT / "rtl/seq/otpu_seq.sv", ROOT / "OpenTPU/SeqLogic.lean",
              ROOT / "OpenTPU/Circuit.lean", ROOT / "OpenTPU/Generate.lean"]
    before = hashes(inputs)
    log = script.with_suffix(".log")
    result = subprocess.run(["yosys", "-Q", "-T", "-s", str(script)], cwd=ROOT,
                            capture_output=True, text=True, timeout=600)
    log.write_text(result.stdout + result.stderr)
    if hashes(inputs) != before:
        raise RuntimeError("sequencer proof inputs changed during proof")
    if mutation:
        if result.returncode == 0 or "proof did fail" not in result.stdout + result.stderr:
            raise RuntimeError(f"sequencer {mutation} mutation not rejected by SAT; see {log}")
        print(f"PASS sequencer checker self-test: incorrect {mutation} rejected", flush=True)
    else:
        if result.returncode or "SAT proof finished - no model found: SUCCESS!" not in result.stdout:
            raise RuntimeError(f"sequencer stage equivalence failed; see {log}")
        print(f"PASS sequencer D={depth} S={slices}: all eight combinational stages", flush=True)
    return {"configuration": {"D": depth, "S": slices}, "input_sha256": before,
            "stages": STAGES, "log": str(log), "mutation": mutation}


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
        proofs = [prove(cfg) for cfg in CONFIGS]
        mutations = [prove(CONFIGS[0], m) for m in ["range", "conflict"]] if args.self_test else []
        summary.write_text(json.dumps({"status": "passed", "proofs": proofs,
            "scope": "combinational stage equivalence with unrestricted independent inputs",
            "yosys": subprocess.check_output(["yosys", "-V"], text=True).strip(),
            "self_tests": mutations}, indent=2) + "\n")
    except BaseException as error:
        summary.write_text(json.dumps({"status": "failed", "error": str(error)}) + "\n")
        raise


if __name__ == "__main__":
    main()
