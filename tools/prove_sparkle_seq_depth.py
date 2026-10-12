"""Check reset and preservation of the ISA's four-entry loop stack bound.

Consumes the complete transition netlists emitted by prove_sparkle_seq.py.
This is a safety check, independent of the equivalence solver's internal points.
A program may push only when fewer than four loops are active (docs/isa.md).
"""
import argparse
import json
import re
import subprocess

from prove_sparkle_seq import CONFIGS, DEPTH_ASSUMPTIONS, ROOT, WORK
from prove_sparkle_seq_logic import hashes
from sparkle_transition import step_miter


def prove(cfg):
    work = WORK / "_".join(map(str, cfg))
    steps = work / "proof_steps.json"
    raw = json.loads(steps.read_text())
    results = []
    for reset in [False, True]:
        name = "depth_reset" if reset else "depth_preserved"
        source = work / f"{name}.sv"
        condition = ("gold_next_sp == 0 && gate_next_sp == 0" if reset else
                     "gold_next_sp <= 3'd4 && gate_next_sp <= 3'd4")
        code, count = re.subn(r"assign ok = .*?;", f"assign ok = {condition};",
                              step_miter(raw), count=1, flags=re.S)
        if count != 1:
            raise RuntimeError("depth check output missing")
        if not reset:
            code = code.replace("endmodule", DEPTH_ASSUMPTIONS + "endmodule")
        source.write_text(code)
        script = work / f"{name}.ys"
        script.write_text(f"read_json {steps.relative_to(ROOT)}\n"
                          f"read_verilog -formal -sv {source.relative_to(ROOT)}\n"
                          "prep -top step_miter -flatten\nchformal -lower\nopt -full\n"
                          f"sat -set-assumes {'-set rst 1' if reset else ''} -prove ok 1 -verify\n")
        files = [steps, source, script, ROOT / "docs/isa.md",
                 ROOT / "tools/prove_sparkle_seq.py", ROOT / "tools/prove_sparkle_seq_depth.py",
                 ROOT / "tools/sparkle_transition.py"]
        before = hashes(files)
        log = script.with_suffix(".log")
        with log.open("w") as stream:
            result = subprocess.run(["yosys", "-Q", "-T", "-s", str(script)], cwd=ROOT,
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=600)
        if hashes(files) != before:
            raise RuntimeError("depth proof inputs changed during proof")
        if result.returncode or "SUCCESS!" not in log.read_text():
            raise RuntimeError(f"depth proof failed: {log}")
        results.append({"check": name, "input_sha256": before, "log": str(log)})
        print(f"PASS {name} {cfg}", flush=True)
    return {"configuration": cfg, "checks": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", action="store_true")
    args = parser.parse_args()
    summary = WORK / ("depth_summary_first.json" if args.first else "depth_summary.json")
    summary.write_text(json.dumps({"status": "running"}) + "\n")
    try:
        results = [prove(cfg) for cfg in (CONFIGS[:1] if args.first else CONFIGS)]
        summary.write_text(json.dumps({"status": "passed", "proofs": results}, indent=2) + "\n")
    except BaseException as error:
        summary.write_text(json.dumps({"status": "failed", "error": str(error)}) + "\n")
        raise


if __name__ == "__main__":
    main()
