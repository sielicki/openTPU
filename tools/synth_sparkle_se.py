"""Compare native/reference stream-engine units in out-of-context XC7 synthesis.

Resource counts do not establish placement or timing parity.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]



def run(command, log):
    with log.open("w") as output:
        subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
                       check=True, timeout=1200)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", choices=["composite", "tail"], required=True)
    parser.add_argument("--check", action="store_true", help="fail on resource count regressions")
    parser.add_argument("--reuse-reference", action="store_true", help="reuse an identical reference synthesis after validating its inputs and tool version")
    args = parser.parse_args()
    WORK = ROOT / f"build/sparkle/se_{args.unit}_synthesis"
    CONFIG = dict(LANES=8, MW=21, NS=3, HA=2, EXT=1) if args.unit == "composite" else dict(LANES=8, TA=7, QD=1)
    top = "otpu_se_comp" if args.unit == "composite" else "otpu_se_tail"
    generator = "se-comp" if args.unit == "composite" else "se-tail"
    references = ["rtl/top/otpu_pkg.sv", "rtl/vpu/otpu_fp.sv", "rtl/vpu/otpu_fpipe.sv", f"rtl/vpu/{top}.sv"]
    WORK.mkdir(parents=True, exist_ok=True)
    summary = WORK / "summary.json"
    previous = json.loads(summary.read_text()) if args.reuse_reference and summary.exists() else {}
    summary.write_text(json.dumps({"status": "running"}) + "\n")
    checkpoint = {"status": "running"}
    try:
        run(["lake", "build", "opentpu-gen"], WORK / "build.log")
        native = WORK / "native.sv"
        run([str(ROOT / ".lake/build/bin/opentpu-gen"), generator, *map(str, CONFIG.values()),
             str(native)], WORK / "generate.log")
        params = " ".join(f"-G {k}={v}" for k, v in CONFIG.items())
        results = {}
        reused_reference = False
        version = subprocess.check_output(["yosys", "-V"], text=True).strip()
        reference_files = [ROOT / p for p in references]
        inputs = [*reference_files, native, Path(__file__).resolve()]
        before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
        for kind, source in [("reference", f"{params} " + " ".join(references)),
                             ("native", f"rtl/top/otpu_pkg.sv {native.relative_to(ROOT)}")]:
            stats = WORK / f"{kind}.json"
            netlist = WORK / f"{kind}_netlist.json"
            script = WORK / f"{kind}.ys"
            script.write_text(f"""read_slang --top {top} {source}
synth_xilinx -family xc7 -top {top} -noclkbuf -noiopad
tee -o {stats.relative_to(ROOT)} stat -json
write_json {netlist.relative_to(ROOT)}
""")
            before[str(script.relative_to(ROOT))] = hashlib.sha256(script.read_bytes()).hexdigest()
            reference_inputs = [*reference_files, script]
            reusable = (kind == "reference" and args.reuse_reference and stats.exists() and netlist.exists() and
                previous.get("configuration") == CONFIG and
                previous.get("input_sha256", {}).get(str(netlist.relative_to(ROOT))) == hashlib.sha256(netlist.read_bytes()).hexdigest() and
                previous.get("yosys") == version and
                all(previous.get("input_sha256", {}).get(str(p.relative_to(ROOT))) ==
                    hashlib.sha256(p.read_bytes()).hexdigest() for p in reference_inputs) and
                json.loads(stats.read_text())["modules"]["\\" + top]["num_cells_by_type"] ==
                    previous.get("cells", {}).get("reference"))
            if reusable:
                reused_reference = True
                print("Reusing reference synthesis: identical inputs, configuration, tool version and saved counts", flush=True)
            else:
                run(["yosys", "-Q", "-T", "-s", str(script)], WORK / f"{kind}.log")
            results[kind] = json.loads(stats.read_text())["modules"]["\\" + top]["num_cells_by_type"]
            before[str(stats.relative_to(ROOT))] = hashlib.sha256(stats.read_bytes()).hexdigest()
            before[str(netlist.relative_to(ROOT))] = hashlib.sha256(netlist.read_bytes()).hexdigest()
            for path, digest in before.items():
                if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest:
                    raise RuntimeError("synthesis inputs changed during run")
            # Preserve a fully checked reference result if native synthesis is
            # interrupted. Reuse still validates every reference input/output.
            checkpoint = {"status": "running", "configuration": CONFIG,
                          "cells": dict(results), "input_sha256": dict(before),
                          "yosys": version, "reused_reference": reused_reference}
            summary.write_text(json.dumps(checkpoint, indent=2) + "\n")
        for path, digest in before.items():
            if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest:
                raise RuntimeError("synthesis inputs changed during run")
        totals = {}
        for kind, cells in results.items():
            totals[kind] = {
                "bram18_equivalents": cells.get("RAMB18E1", 0) + 2*cells.get("RAMB36E1", 0),
                "dsps": sum(n for k, n in cells.items() if k.startswith("DSP")),
                "luts": sum(n for k, n in cells.items() if k.startswith("LUT")),
                "distributed_ram": sum(n for k, n in cells.items() if k.startswith("RAM") and not k.startswith("RAMB")),
                "flip_flops": sum(n for k, n in cells.items() if k.startswith("FD")),
                "shift_registers": sum(n for k, n in cells.items() if k.startswith("SRL")),
            }
        regressions = [k for k, v in totals["native"].items() if v > totals["reference"][k]]
        summary.write_text(json.dumps({"status": "failed" if args.check and regressions else "passed",
            "configuration": CONFIG, "scope": "out-of-context xc7 synthesis; no placement or timing checks",
            "cells": results, "totals": totals, "regressions": regressions, "checked": args.check, "reused_reference": reused_reference,
            "input_sha256": before, "yosys": version}, indent=2) + "\n")
        print("Cell                 reference     native")
        for cell in sorted(results["reference"].keys() | results["native"].keys()):
            print(f"{cell:20} {results['reference'].get(cell, 0):9} {results['native'].get(cell, 0):10}")
    except BaseException as error:
        summary.write_text(json.dumps({**checkpoint, "status": "failed", "error": str(error)}, indent=2) + "\n")
        raise
    if args.check and regressions:
        raise SystemExit("Native resource regression: " + ", ".join(regressions))
    if args.check:
        print(f"PASS SE {args.unit} resource counts (placement/timing not checked)")


if __name__ == "__main__":
    main()
