"""Prove native circuits against original RTL with Yosys SAT temporal induction.

Requires Yosys with read_slang. The FP miter has unconstrained operands/enable,
checks the base case, and uses stage correspondence to strengthen induction.
Unreset reference datapaths are unrestricted until their enabled pipeline fills.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build/sparkle/formal"


def checked(command, log):
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=600)
    log.write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"command failed; see {log}\n{(result.stdout + result.stderr)[-3000:]}")
    return result.stdout


def hashes(paths):
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def fp_proof(mutation=False):
    source = WORK / ("float_mutated.sv" if mutation else "float.sv")
    if mutation:
        original = (WORK / "float.sv").read_text()
        needle = "assign y = result;"
        if needle not in original:
            raise RuntimeError("mutation target missing; update the checker self-test")
        source.write_text(original.replace(needle, "assign y = result ^ 32'd1;", 1))
    else:
        subprocess.run([str(ROOT / ".lake/build/bin/opentpu-gen"), "float", "2", "4", str(source)],
                       cwd=ROOT, check=True)
    script = WORK / ("fp_mutation.ys" if mutation else "fp.ys")
    script.write_text(f"""read_slang --top fp_miter rtl/vpu/otpu_fp.sv rtl/vpu/otpu_fpipe.sv {source.relative_to(ROOT)} tests/sparkle/formal/fp_miter.sv
prep -top fp_miter -flatten
opt -full
sat -seq 1 -tempinduct -maxsteps 12 -prove ok 1 -verify -show-inputs -show-outputs -dump_vcd {WORK.relative_to(ROOT)}/fp_failure.vcd
""")
    log = script.with_suffix(".log")
    inputs = [source, script, ROOT / "rtl/vpu/otpu_fp.sv", ROOT / "rtl/vpu/otpu_fpipe.sv",
              ROOT / "tests/sparkle/formal/fp_miter.sv"]
    before = hashes(inputs)
    result = subprocess.run(["yosys", "-Q", "-T", "-s", str(script)], cwd=ROOT,
                            capture_output=True, text=True, timeout=600)
    log.write_text(result.stdout + result.stderr)
    if hashes(inputs) != before:
        raise RuntimeError("proof inputs changed while Yosys was running")
    if mutation:
        if result.returncode == 0 or "proof did fail" not in result.stdout + result.stderr:
            raise RuntimeError(f"mutation was not rejected by a failed proof; see {log}")
        print("PASS FP checker self-test: incorrect output rejected")
    else:
        if result.returncode or "Induction step proven: SUCCESS!" not in result.stdout:
            raise RuntimeError(f"FP induction proof did not finish successfully; see {log}")
        print("PASS FP32 add/multiply: base case and unbounded temporal induction")
    return {"input_sha256": before, "log": str(log), "induction_steps":
            int(re.findall(r"\[induction step (\d+)\]", result.stdout)[-1]) if not mutation else None}


def collective_proof(slices, lanes, mutation=False):
    work = WORK / f"collective_{slices}_{lanes}"
    work.mkdir(exist_ok=True)
    source = work / ("mutated.sv" if mutation else "native.sv")
    if mutation:
        original = (work / "native.sv").read_text()
        needle = "assign ack = (st == 2'd2);"
        if needle not in original:
            raise RuntimeError("collective mutation target missing")
        source.write_text(original.replace(needle, "assign ack = (st != 2'd2);", 1))
    else:
        subprocess.run([str(ROOT / ".lake/build/bin/opentpu-gen"), "collective-core",
                        str(slices), str(lanes), str(source)], cwd=ROOT, check=True)
    checks = []
    for lane in range(lanes):
        checks.extend([
            f"(golden.st!=1 || golden.rm[{lane}]==native.rm{lane})",
            f"(!golden.pv || golden.pm[{lane}]==native.pm{lane})",
            f"(!golden.qv || {{golden.qwl[{lane}],golden.qm[{lane}],golden.qd[{lane}]}}=="
            f"{{native.qwl{lane},native.qm{lane},native.qd{lane}}})"])
    include = work / "collective_lanes.svh"
    include.write_text("assign lanes_equal =\n" + " &&\n".join(checks) + ";\n")
    script = work / ("mutation.ys" if mutation else "proof.ys")
    script.write_text(f"""read_slang --top collective_miter -G S={slices} -G LANES={lanes} -I {work.relative_to(ROOT)} rtl/top/otpu_pkg.sv rtl/top/otpu_coll.sv {source.relative_to(ROOT)} tests/sparkle/formal/collective_miter.sv
prep -top collective_miter -flatten
opt -full
sat -seq 1 -tempinduct -maxsteps 12 -prove ok 1 -verify -show-inputs -show-outputs -dump_vcd {work.relative_to(ROOT)}/failure.vcd
""")
    log = script.with_suffix(".log")
    inputs = [source, script, include, ROOT / "rtl/top/otpu_pkg.sv", ROOT / "rtl/top/otpu_coll.sv",
              ROOT / "tests/sparkle/formal/collective_miter.sv"]
    before = hashes(inputs)
    result = subprocess.run(["yosys", "-Q", "-T", "-s", str(script)], cwd=ROOT,
                            capture_output=True, text=True, timeout=600)
    log.write_text(result.stdout + result.stderr)
    if hashes(inputs) != before:
        raise RuntimeError("proof inputs changed while Yosys was running")
    if mutation:
        if result.returncode == 0 or "proof did fail" not in result.stdout + result.stderr:
            raise RuntimeError(f"collective mutation was not rejected by the proof; see {log}")
        print("PASS collective checker self-test: incorrect acknowledgement rejected", flush=True)
    else:
        if result.returncode or "Induction step proven: SUCCESS!" not in result.stdout:
            raise RuntimeError(f"collective induction did not finish successfully; see {log}")
        print(f"PASS collective S={slices} LANES={lanes}: base case and unbounded induction", flush=True)
    return {"slices": slices, "lanes": lanes,
            "input_sha256": before, "log": str(log),
            "induction_steps": int(re.findall(r"\[induction step (\d+)\]", result.stdout)[-1]) if not mutation else None}


def backend_proof(kind, mutation=False):
    """Check physical lowering, starting from equal but otherwise arbitrary RAMs."""
    work = WORK / f"backend_{kind}"
    work.mkdir(exist_ok=True)
    source = work / ("mutated.sv" if mutation else "packed.sv")
    if mutation:
        original = (work / "packed.sv").read_text()
        changed, count = re.subn(r"if \(en\[38:38\]\)", "if (1'b0)", original, count=1)
        if count != 1:
            raise RuntimeError("backend mutation target missing")
        source.write_text(changed)
    else:
        subprocess.run([str(ROOT / ".lake/build/bin/opentpu-backend-check"), kind, str(work)],
                       cwd=ROOT, check=True)
    script = work / ("mutation.ys" if mutation else "proof.ys")
    script.write_text(f"""read_slang --top backend_miter {work.relative_to(ROOT)}/raw.sv {source.relative_to(ROOT)} {work.relative_to(ROOT)}/miter.sv
prep -top backend_miter -flatten
memory_map
chformal -lower
opt -full
sat -seq 1 -tempinduct -maxsteps 4 -set-assumes -prove ok 1 -verify -dump_vcd {work.relative_to(ROOT)}/failure.vcd
""")
    inputs = [work / "raw.sv", source, work / "miter.sv", script]
    before = hashes(inputs)
    result = subprocess.run(["yosys", "-Q", "-T", "-s", str(script)], cwd=ROOT,
                            capture_output=True, text=True, timeout=600)
    log = script.with_suffix(".log")
    log.write_text(result.stdout + result.stderr)
    if hashes(inputs) != before:
        raise RuntimeError("backend proof inputs changed during proof")
    if mutation:
        if result.returncode == 0 or "proof did fail" not in result.stdout + result.stderr:
            raise RuntimeError(f"backend mutation was not rejected by a failed proof; see {log}")
        print("PASS byte-bank checker self-test: missing byte write rejected", flush=True)
    else:
        if result.returncode or "Induction step proven: SUCCESS!" not in result.stdout:
            raise RuntimeError(f"backend induction did not finish successfully; see {log}")
        print(f"PASS byte-bank lowering ({kind}): state and output correspondence", flush=True)
    return {"fixture": kind, "initial_memory": "equal, otherwise arbitrary",
            "input_sha256": before, "log": str(log),
            "induction_steps": int(re.findall(r"\[induction step (\d+)\]", result.stdout)[-1]) if not mutation else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="also prove the checker rejects an output mutation")
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    summary = WORK / "summary.json"
    summary.write_text(json.dumps({"status": "running"}) + "\n")
    try:
        checked(["lake", "build", "OpenTPU", "opentpu-gen", "opentpu-backend-check"], WORK / "build.log")
        result = fp_proof()
        collectives = [collective_proof(s, l) for s, l in [(1, 1), (2, 4), (4, 8)]]
        backends = [backend_proof(kind) for kind in ["banks", "actram"]]
        if args.self_test:
            fp_proof(mutation=True)
            collective_proof(2, 4, mutation=True)
            backend_proof("banks", mutation=True)
        version = checked(["yosys", "-V"], WORK / "version.log").strip()
        summary.write_text(json.dumps({"status": "passed", "yosys": version,
            "fp": result, "collective": collectives, "backend": backends,
            "self_test": args.self_test}, indent=2) + "\n")
    except BaseException as error:
        summary.write_text(json.dumps({"status": "failed", "error": str(error)}) + "\n")
        raise


if __name__ == "__main__":
    main()
