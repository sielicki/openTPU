"""Equivalence check for the folding tree, including its native FP pipelines.

The default checks the complete datapath and control from equal, otherwise arbitrary
initial states. --controller-only abstracts corresponding adder outputs to equal,
arbitrary results while checking every operand/enable pair independently of arithmetic.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build/sparkle/formal_vtree"
CONFIGS = [(1, 4), (2, 4), (4, 4), (8, 4), (16, 4), (8, 5), (4, 7)]


def miter(lanes, la, controller_only=False):
    rl = 64 // lanes
    lr, lw = rl.bit_length()-1, lanes.bit_length()-1
    ln2 = lanes == 8 and la == 4
    sh2 = not ln2 and lw >= 2 and la % rl != 0
    hs = [rl >> (j+1) for j in range(lr)]
    issue = [hs[0]]
    for j in range(1, lr):
        issue.append(issue[-1]-hs[j]+rl*((la+2*hs[j]+rl-1)//rl))
    dmax = 2 if ln2 else max([1]+[issue[j]-issue[j-1]-la for j in range(1, lr)])
    state = ["golden.rsr==native.rsr"]
    adders = []
    for j in range(1, lr-1):
        state.append(f"golden.g_lv[{j}].sr==native.lv{j}")
    for k in range(lanes):
        tree = f"golden.g_tree[{k}]"
        for d in range(1, dmax+1):
            state.append(f"{tree}.td[{d}]==native.td{k}_{d}")
        n = rl//2-1
        for d in range(n):
            delay = "g_one.qr" if n == 1 else ("g_regs.qr" if d == n-1 else f"g_regs.r[{d}]")
            state.append(f"{tree}.u_pd.{delay}==native.pdd{k}_{d}")
        if ln2:
            state.extend([f"{tree}.g_tp.la==native.la{k}", f"{tree}.g_tp.qb==native.qb{k}"])
        else:
            state.append(f"{tree}.g_gen.pd==native.pd{k}")
        adders.append((f"{tree}.u_tree", f"native.tree{k}", False))
    if ln2:
        for m in range(2):
            part = f"golden.g_ln.g_m[{m}]"
            state.extend([f"{part}.qa==native.ln_qa{m}", f"{part}.qb==native.ln_qb{m}"])
            adders.append((f"{part}.{'g_o' if m==0 else 'g_n'}.u_ln", f"native.ln{m}", m==0))
    else:
        for q in range(1, lw+1):
            for k in range(lanes >> q):
                if sh2 and q == 2:
                    continue
                branch = "g_mux" if sh2 and q == 1 and k < lanes//4 else "g_add"
                adders.append((f"golden.g_lg.g_xl[{q}].g_k[{k}].{branch}.u_add", f"native.lane{q}_{k}", False))
    operands, returns = [], []
    for ref, native, duplicate in adders:
        operands.extend(f"{ref}.{port}=={native}.{port}" for port in ["a", "b", "en"])
        returns.append(f"{ref}.y=={native}.y")
        if duplicate:
            returns.append(f"{ref}.yo=={native}.yo")
        if not controller_only:
            for stage, fields in [
                ("s1", ["p1_sp", "p1_sv", "p1_sa", "p1_sub", "p1_e", "p1_d", "p1_ma", "p1_mb"]),
                ("s2", ["p2_sp", "p2_sv", "p2_sa", "p2_sub", "p2_e", "p2_sum"]),
                ("s3", ["p3_sp", "p3_sv", "p3_s", "p3_e", "p3_mn"]),
            ]:
                state.append(f"{ref}.{stage}=={{{','.join(f'{native}.{f}' for f in fields)}}}")
            state.append(f"{ref}.r=={native}.result")
            if duplicate:
                state.append(f"{ref}.ro=={native}.result_copy")
            else:
                for d in range(la-4):
                    delay = "g_one.qr" if la == 5 else ("g_regs.qr" if d == la-5 else f"g_regs.r[{d}]")
                    state.append(f"{ref}.u_pad.{delay}=={native}.pad{d}")
    join = lambda xs: " &&\n    ".join(f"({x})" for x in xs)
    cutpoints = [f"{inst}.{port}" for ref, native, duplicate in adders
                 for inst in [ref, native] for port in (["y", "yo"] if duplicate else ["y"])]
    strobes = [f"golden.rsr[golden.DL+{la}-1]", "golden.ln_l1b", "golden.ln_l2", "golden.ln_l3"]
    lane_collision = " || ".join(f"({strobes[i]} && {strobes[j]})" for i in range(4) for j in range(i+1, 4)) if ln2 else (
        f"golden.l2_v && golden.rsr[golden.DL+{la}-1]" if sh2 else "1'b0")
    return f"""module vtree_miter(input wire clk,rst,en,cap,row_last,
  input wire [7:0] sub, input wire [{lanes*32-1}:0] pacc, output wire ok);
  wire [31:0] pa [{lanes}];
  for(genvar k=0;k<{lanes};k++) assign pa[k]=pacc[k*32+:32];
  wire [31:0] gr,go,nr,no;
  wire gv,nv,nc;
  otpu_vtree #(.LANES({lanes}),.LA({la})) golden(.clk,.rst,.en,.cap,.row_last,.sub,.pacc(pa),
    .root(gr),.root_o(go),.root_v(gv));
  otpu_vtree_sparkle native(.clk,.rst,.en,.cap,.row_last,.sub,.pacc,
    .root(nr),.root_o(no),.root_v(nv),.schedule_collision(nc));
  wire state_equal = {join(state)};
  wire operands_equal = {join(operands)};
  wire returns_equal = {join(returns)};
  logic first=1'b1;
  always @(posedge clk) first<=1'b0;
  always_comb begin
    if(first) assume(state_equal);
    {"assume(returns_equal);" if controller_only else ""}
  end
  wire collision = !rst && en && ((cap && sub>={rl//2} && golden.lv!=0) ||
    ({lane_collision}));
  assign ok = state_equal && operands_equal && gr==nr && go==no && gv==nv && nc==collision;
endmodule
""", cutpoints


def prove(lanes, la, mutation=False, controller_only=False):
    work = WORK / (f"{lanes}_{la}" + ("_control" if controller_only else ""))
    work.mkdir(parents=True, exist_ok=True)
    stem = "arithmetic_mutation" if mutation == "arithmetic" else "mutation"
    source = work / (f"{stem}.sv" if mutation else "native.sv")
    harness, cutpoints = miter(lanes, la, controller_only)
    if mutation:
        original = (work / "native.sv").read_text()
        if mutation == "arithmetic":
            changed, count = re.subn(r"assign y = result;", "assign y = result ^ 32'd1;", original, count=1)
        else:
            changed, count = re.subn(r"assign root_v = (.*);", r"assign root_v = ~(\1);", original, count=1)
        if count != 1:
            raise RuntimeError("VTREE mutation target missing")
        source.write_text(changed)
    else:
        subprocess.run([str(ROOT / ".lake/build/bin/opentpu-gen"), "vtree-core", str(lanes), str(la), str(source)],
                       cwd=ROOT, check=True)
        (work / "miter.sv").write_text(harness)
    script = work / (f"{stem}.ys" if mutation else "proof.ys")
    files = [ROOT / "rtl/vpu/otpu_fp.sv", ROOT / "rtl/vpu/otpu_fpipe.sv",
             ROOT / "rtl/vpu/otpu_vtree.sv", source, work / "miter.sv"]
    cuts = "\n".join(f"select -assert-count 1 w:{point}" for point in cutpoints) + "\ncutpoint " + " ".join(f"w:{point}" for point in cutpoints)
    if not controller_only:
        cuts = ""
    # The reference declares an unused lane-level strobe beyond rsr for LANES=1;
    # SH2 is false there, so it affects neither operands nor the collision output.
    script.write_text("read_slang --top vtree_miter " + ("-Wno-index-oob " if lanes == 1 else "") +
        " ".join(str(p.relative_to(ROOT)) for p in files) + f"""
prep -top vtree_miter -flatten
{cuts}
select *
memory_map
chformal -lower
setattr -unset init w:golden.* w:native.*
opt -full
sat -seq 1 -tempinduct -maxsteps 4 -set-assumes -prove ok 1 -verify -dump_vcd {work.relative_to(ROOT)}/{stem if mutation else 'proof'}_failure.vcd
""")
    files.append(script)
    before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    result = subprocess.run(["yosys", "-Q", "-T", "-s", str(script)], cwd=ROOT,
                            capture_output=True, text=True, timeout=600)
    log = script.with_suffix(".log")
    log.write_text(result.stdout+result.stderr)
    for path, digest in before.items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=digest:
            raise RuntimeError("VTREE proof inputs changed during proof")
    if mutation:
        if result.returncode == 0 or "proof did fail" not in result.stdout+result.stderr:
            raise RuntimeError(f"VTREE mutation was not rejected by a failed proof; see {log}")
        print(f"PASS VTREE checker self-test: {'corrupted FP result' if mutation == 'arithmetic' else 'wrong root-valid timing'} rejected", flush=True)
    else:
        if result.returncode or "Induction step proven: SUCCESS!" not in result.stdout:
            raise RuntimeError(f"VTREE controller induction did not finish successfully; see {log}")
        print(f"PASS VTREE LANES={lanes} LA={la}: {'controller/routing' if controller_only else 'complete datapath/control'} correspondence", flush=True)
    return {"lanes": lanes, "latency": la, "input_sha256": before, "log": str(log),
            "induction_steps": int(re.findall(r"\[induction step (\d+)\]", result.stdout)[-1]) if not mutation else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--controller-only", action="store_true", help="abstract the FP adders at explicit cut points")
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    summary = WORK / ("control_summary.json" if args.controller_only else "summary.json")
    summary.write_text(json.dumps({"status": "running"})+"\n")
    try:
        with (WORK / "build.log").open("w") as log:
            subprocess.run(["lake", "build", "OpenTPU", "opentpu-gen"], cwd=ROOT,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
        proofs = [prove(l, a, controller_only=args.controller_only) for l, a in CONFIGS]
        mutation = prove(8, 4, mutation=True, controller_only=args.controller_only) if args.self_test else None
        arithmetic_mutation = prove(8, 4, mutation="arithmetic") if args.self_test and not args.controller_only else None
        summary.write_text(json.dumps({"status": "passed", "proofs": proofs,
            "abstraction": "equal arbitrary adder results" if args.controller_only else "none; concrete FP pipelines",
            "initial_state": "equal, otherwise arbitrary controller, delay and (unless abstracted) arithmetic registers",
            "yosys": subprocess.check_output(["yosys", "-V"], text=True).strip(),
            "self_test": mutation, "arithmetic_self_test": arithmetic_mutation}, indent=2)+"\n")
    except BaseException as error:
        summary.write_text(json.dumps({"status": "failed", "error": str(error)})+"\n")
        raise


if __name__ == "__main__":
    main()
