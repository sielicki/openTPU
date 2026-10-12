"""Compare reference/native ACT RAM resource mapping for the board configuration.

This is an out-of-context Kintex-7 synthesis comparison, not a placement/timing
qualification. Requires Yosys with read_slang and the Xilinx synthesis backend.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build/sparkle/actram_synthesis"


def run(command, log):
    with log.open("w") as output:
        subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
                       timeout=600, check=True)


def synthesize():
    WORK.mkdir(parents=True, exist_ok=True)
    run(["lake", "build", "opentpu-gen"], WORK / "build.log")
    native = WORK / "native.sv"
    run([str(ROOT / ".lake/build/bin/opentpu-gen"), "actram", "128", "4", "4", "128", "8",
         str(native)], WORK / "generate.log")
    results = {}
    for kind, source in [
        ("reference", "-G D=128 -G MCOLS=4 -G ROWS=4 -G BLOCKS=128 -G LANES=8 rtl/mem/otpu_actram.sv"),
        ("native", str(native.relative_to(ROOT))),
    ]:
        stats = WORK / f"{kind}.json"
        script = WORK / f"{kind}.ys"
        script.write_text(f"""read_slang --top otpu_actram {source}
synth_xilinx -family xc7 -top otpu_actram -noclkbuf -noiopad
tee -o {stats.relative_to(ROOT)} stat -json
""")
        run(["yosys", "-Q", "-T", "-s", str(script)], WORK / f"{kind}.log")
        results[kind] = json.loads(stats.read_text())["modules"]["\\otpu_actram"]["num_cells_by_type"]
    print("Cell                 reference     native")
    for cell in sorted(results["reference"].keys() | results["native"].keys()):
        print(f"{cell:20} {results['reference'].get(cell, 0):9} {results['native'].get(cell, 0):10}")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="fail if native BRAM, LUT, distributed RAM, FF or SRL counts regress")
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    summary = WORK / "summary.json"
    summary.write_text(json.dumps({"status": "running"}) + "\n")
    try:
        results = synthesize()
        totals = {}
        for kind, cells in results.items():
            totals[kind] = {
                "bram18_equivalents": cells.get("RAMB18E1", 0) + 2 * cells.get("RAMB36E1", 0),
                "luts": sum(n for name, n in cells.items() if name.startswith("LUT")),
                "distributed_ram": sum(n for name, n in cells.items()
                                       if name.startswith("RAM") and not name.startswith("RAMB")),
                "flip_flops": sum(n for name, n in cells.items() if name.startswith("FD")),
                "shift_registers": sum(n for name, n in cells.items() if name.startswith("SRL")),
            }
        regressions = [name for name, count in totals["native"].items()
                       if count > totals["reference"][name]]
        sources = [ROOT / "rtl/mem/otpu_actram.sv", WORK / "native.sv",
                   WORK / "reference.ys", WORK / "native.ys", Path(__file__).resolve()]
        report = {"status": "failed" if args.check and regressions else "passed",
                  "scope": "out-of-context xc7 synthesis; no placement or timing checks",
                  "configuration": {"D": 128, "MCOLS": 4, "ROWS": 4, "BLOCKS": 128, "LANES": 8},
                  "yosys": subprocess.check_output(["yosys", "-V"], text=True).strip(),
                  "cells": results, "totals": totals, "regressions": regressions,
                  "checked": args.check,
                  "input_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in sources}}
        summary.write_text(json.dumps(report, indent=2) + "\n")
    except BaseException as error:
        summary.write_text(json.dumps({"status": "failed", "error": str(error)}) + "\n")
        raise
    if args.check and regressions:
        raise SystemExit("Native resource regression: " + ", ".join(regressions))
    if args.check:
        print("PASS ACT RAM resource counts (placement/timing not checked)")


if __name__ == "__main__":
    main()
