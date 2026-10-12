"""Compare reference/native TMEM in out-of-context Kintex-7 synthesis.

Uses the board's 64K-word, eight-lane, six-copy configuration. Counts are not
placement or timing qualification. Requires Yosys with read_slang.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
from sparkle_provenance import archive

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build/sparkle/tmem_synthesis"
CONFIG = dict(WORDS=65536, LANES=8, NRP=8, NWP=4, WPB=1, GEN_R=1, GEN_W=2, SH_HOST=1, SH_MASK=160)


def run(command, log):
    with log.open("w") as output:
        subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
                       check=True, timeout=1200)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail on resource count regressions")
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    summary = WORK / "summary.json"
    if summary.exists():
        old=json.loads(summary.read_text());archive(summary)
        for relative in old.get("input_sha256", {}):
            path=ROOT/relative
            if path.exists():archive(path)
    summary.write_text(json.dumps({"status": "running"}) + "\n")
    try:
        run(["lake", "build", "opentpu-gen"], WORK / "build.log")
        generating=[ROOT/"OpenTPU"/(n+".lean") for n in ["TMem","TMemABI","Physical","Backend","Circuit","Generate"]]
        generating.append(ROOT/".lake/build/bin/opentpu-gen")
        emission={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in generating}
        native = WORK / "native.sv"
        run([str(ROOT / ".lake/build/bin/opentpu-gen"), "tmem", *map(str, CONFIG.values()),
             str(native)], WORK / "generate.log")
        if emission != {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in generating}:
            raise RuntimeError("TMEM generating sources changed during emission")
        for p in generating:archive(p)
        (WORK/"emission-inputs.json").write_text(json.dumps(emission,indent=2)+"\n")
        params = " ".join(f"-G {k}={v}" for k, v in CONFIG.items())
        results = {}
        inputs = [ROOT / "rtl/mem/otpu_tmem.sv", native, Path(__file__).resolve()]
        before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
        for kind, source in [("reference", f"{params} rtl/mem/otpu_tmem.sv"),
                             ("native", str(native.relative_to(ROOT)))]:
            stats = WORK / f"{kind}.json"
            script = WORK / f"{kind}.ys"
            script.write_text(f"""read_slang --top otpu_tmem {source}
synth_xilinx -family xc7 -top otpu_tmem -noclkbuf -noiopad
tee -o {stats.relative_to(ROOT)} stat -json
""")
            before[str(script.relative_to(ROOT))] = hashlib.sha256(script.read_bytes()).hexdigest()
            (WORK/"inputs.json").write_text(json.dumps(before,indent=2)+"\n")
            run(["yosys", "-Q", "-T", "-s", str(script)], WORK / f"{kind}.log")
            results[kind] = json.loads(stats.read_text())["modules"]["\\otpu_tmem"]["num_cells_by_type"]
        for path, digest in before.items():
            if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest:
                raise RuntimeError("synthesis inputs changed during run")
        totals = {}
        for kind, cells in results.items():
            totals[kind] = {
                "bram18_equivalents": cells.get("RAMB18E1", 0) + 2*cells.get("RAMB36E1", 0),
                "luts": sum(n for k, n in cells.items() if k.startswith("LUT")),
                "logic_cells_including_inverters": sum(n for k,n in cells.items() if k.startswith("LUT") or k=="INV"),
                "carry_cells": cells.get("CARRY4",0),
                "dsps": cells.get("DSP48E1",0),
                "distributed_ram": sum(n for k, n in cells.items() if k.startswith("RAM") and not k.startswith("RAMB")),
                "flip_flops": sum(n for k, n in cells.items() if k.startswith("FD")),
                "shift_registers": sum(n for k, n in cells.items() if k.startswith("SRL")),
            }
        regressions = [k for k, v in totals["native"].items() if v > totals["reference"][k]]
        summary.write_text(json.dumps({"status": "failed" if args.check and regressions else "passed",
            "configuration": CONFIG, "scope": "out-of-context xc7 synthesis; no placement or timing checks",
            "cells": results, "totals": totals, "regressions": regressions, "checked": args.check,
            "input_sha256": before, "emission_sha256": emission, "yosys": subprocess.check_output(["yosys", "-V"], text=True).strip()}, indent=2) + "\n")
        for relative in before:archive(ROOT/relative)
        archive(summary)
        print("Cell                 reference     native")
        for cell in sorted(results["reference"].keys() | results["native"].keys()):
            print(f"{cell:20} {results['reference'].get(cell, 0):9} {results['native'].get(cell, 0):10}")
    except BaseException as error:
        summary.write_text(json.dumps({"status": "failed", "error": str(error)}) + "\n")
        raise
    if args.check and regressions:
        raise SystemExit("Native resource regression: " + ", ".join(regressions))
    if args.check:
        print("PASS TMEM resource counts (placement/timing not checked)")


if __name__ == "__main__":
    main()
