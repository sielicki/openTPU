"""Prove native TMEM against RTL from equal, otherwise arbitrary initial state.

All memory cells and pipeline registers form the induction invariant. Inputs are
unrestricted, including requests, grants, addresses and data. This is a hardware
equivalence proof for the listed configurations, not an arbiter correctness proof.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build/sparkle/formal_tmem"
CONFIGS = [
    (8, 2, 3, 2, 1, 1, 1, 0, 4),
    (8, 2, 3, 2, 2, 7, 3, 0, 4),
    (16, 4, 4, 3, 1, 0, 0, 1, 8),
]


def miter(cfg):
    words, lanes, nrp, nwp, wpb, gr, gw, host, guests = cfg
    iw = (words // lanes).bit_length() - 1
    equal = []
    for b in range(lanes):
        for w in range(wpb):
            for ref, native in [("pw_v", "pwv"), ("pw_a", "pwa"), ("pw_d", "pwd"), ("pd", "pd")]:
                equal.append(f"golden.{ref}[{b}][{w}]==native.{native}{b*wpb+w}")
    for p in range(nrp):
        if not (guests >> p) & 1:
            for b in range(lanes):
                cp = f"golden.g_port[{p}].g_copy"
                equal.append(f"{cp}.q[{b}]==native.q{p}_{b}")
                for w in range(wpb):
                    equal.append(f"{cp}.bh[{b}][{w}]==native.bh{p}_{b}_{w}")
                for a in range(words // lanes):
                    equal.append(f"{cp}.g_bank[{b}].mem[{a}]==native.mem{p}_{b}[{a}]")
        for lane in range(lanes):
            for reg in ["fresh", "held"]:
                equal.append(f"golden.g_port[{p}].{reg}[{lane}]==native.{reg}{p*lanes+lane}")
            if (gr >> p) & 1:
                equal.append(f"golden.g_port[{p}].sel[{lane}]==native.sel{p*lanes+lane}")
            else:
                equal.append(f"golden.g_port[{p}].g_rot.rot_q[{lane}]==native.rot{p*lanes+lane}")
    invariant = " &&\n    ".join(f"({expr})" for expr in equal)
    return f"""module tmem_miter(
  input wire clk,
  input wire [{nrp-1}:0][{lanes-1}:0] r_en,r_req,
  input wire [{nrp-1}:0][{lanes-1}:0][31:0] r_addr,
  input wire [{nwp-1}:0][{lanes-1}:0] w_en,w_req,
  input wire [{nwp-1}:0] w_gnt,
  input wire [{nwp-1}:0][{lanes-1}:0][31:0] w_addr,w_data,
  output wire ok
);
  wire [{nrp*lanes*32-1}:0] golden_data,native_data;
  wire [{lanes*wpb-1}:0] selected_valid;
  wire [{lanes*wpb*iw-1}:0] selected_address;
  wire [{lanes*wpb*32-1}:0] selected_data;
  otpu_tmem #(.WORDS({words}),.LANES({lanes}),.NRP({nrp}),.NWP({nwp}),.WPB({wpb}),
    .GEN_R({gr}),.GEN_W({gw}),.SH_HOST({host}),.SH_MASK({guests})) golden(
    .clk,.r_en,.r_req,.r_addr,.r_data(golden_data),.w_en,.w_req,.w_gnt,.w_addr,.w_data,.dump(1'b0));
  otpu_tmem_sparkle native(.clk,.r_en,.r_req,.r_addr,.r_data(native_data),
    .w_en,.w_req,.w_gnt,.w_addr,.w_data,.selected_valid,.selected_address,.selected_data);
  wire state_equal = {invariant};
  logic first = 1'b1;
  always @(posedge clk) first <= 1'b0;
  always_comb if(first) assume(state_equal);
  assign ok = state_equal && golden_data==native_data &&
    selected_valid==golden.bw_v && selected_address==golden.bw_a && selected_data==golden.bw_d;
endmodule
"""


def hashes(paths):
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def prove(cfg, mutation=False):
    work = WORK / "_".join(map(str, cfg))
    work.mkdir(parents=True, exist_ok=True)
    source = work / ("mutated.sv" if mutation else "native.sv")
    if mutation:
        original = (work / "native.sv").read_text()
        # Remove the first pending-write bypass, while keeping its RAM and writes.
        changed, count = re.subn(r"assign _gen_qb0_0 = .*;", "assign _gen_qb0_0 = q0_0;", original, count=1)
        if count != 1 or changed == original:
            raise RuntimeError("TMEM mutation target missing")
        source.write_text(changed)
    else:
        subprocess.run([str(ROOT / ".lake/build/bin/opentpu-gen"), "tmem-core",
                        *map(str, cfg), str(source)], cwd=ROOT, check=True)
        (work / "miter.sv").write_text(miter(cfg))
    script = work / ("mutation.ys" if mutation else "proof.ys")
    script.write_text(f"""read_slang --top tmem_miter rtl/mem/otpu_tmem.sv {source.relative_to(ROOT)} {work.relative_to(ROOT)}/miter.sv
prep -top tmem_miter -flatten
memory_map
chformal -lower
# Match arbitrary initial states, rather than relying on native register initializers.
setattr -unset init w:golden.* w:native.*
opt -full
sat -seq 1 -tempinduct -maxsteps 4 -set-assumes -prove ok 1 -verify -dump_vcd {work.relative_to(ROOT)}/failure.vcd
""")
    inputs = [source, script, work / "miter.sv", ROOT / "rtl/mem/otpu_tmem.sv"]
    before = hashes(inputs)
    log = script.with_suffix(".log")
    result = subprocess.run(["yosys", "-Q", "-T", "-s", str(script)], cwd=ROOT,
                            capture_output=True, text=True, timeout=600)
    log.write_text(result.stdout + result.stderr)
    if hashes(inputs) != before:
        raise RuntimeError("TMEM proof inputs changed during proof")
    if mutation:
        if result.returncode == 0 or "proof did fail" not in result.stdout + result.stderr:
            raise RuntimeError(f"missing bypass was not rejected by a failed proof; see {log}")
        print("PASS TMEM checker self-test: missing pending-write bypass rejected", flush=True)
    else:
        if result.returncode or "Induction step proven: SUCCESS!" not in result.stdout:
            raise RuntimeError(f"TMEM induction did not finish successfully; see {log}")
        print(f"PASS TMEM {cfg}: state/output correspondence by induction", flush=True)
    return {"configuration": dict(zip(
        ["WORDS", "LANES", "NRP", "NWP", "WPB", "GEN_R", "GEN_W", "SH_HOST", "SH_MASK"], cfg)),
        "input_sha256": before, "log": str(log), "induction_steps":
        int(re.findall(r"\[induction step (\d+)\]", result.stdout)[-1]) if not mutation else None}


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
        mutation = prove(CONFIGS[0], mutation=True) if args.self_test else None
        summary.write_text(json.dumps({"status": "passed", "proofs": proofs,
            "initial_state": "equal, otherwise arbitrary memories and pipeline registers",
            "yosys": subprocess.check_output(["yosys", "-V"], text=True).strip(),
            "self_test": mutation}, indent=2) + "\n")
    except BaseException as error:
        summary.write_text(json.dumps({"status": "failed", "error": str(error)}) + "\n")
        raise


if __name__ == "__main__":
    main()
