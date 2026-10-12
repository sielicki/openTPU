"""Inductively prove the four native sequencer dispatch stages under backpressure.

The reference stage body is extracted with named intermediate expressions; its dispatch authorization,
resolved command/unit/PC and free-window flag are unconstrained cutpoint inputs.
All stage data/valid registers start equal but otherwise arbitrary. Reset may
occur at any time. Fetch/control execution and window storage are outside scope.
"""
import argparse
import json
import re
import subprocess

from prove_sparkle_seq_logic import ROOT, CONFIGS, hashes
from sparkle_transition import expose_steps, step_miter

WORK = ROOT / "build/sparkle/formal_seq_dispatch"
STATES = {f"{s}_{n}": w for s in ["p", "s", "q", "c"]
          for n, w in [("v", 1), ("cmd", 240), ("unit", 3), ("pc", 32)]}
STATES.update(s_pp=192, q_pr=128, c_fp=322)


def harness(depth, slices):
    source = (ROOT / "rtl/seq/otpu_seq.sv").read_text()

    def section(start, end):
        if source.count(start) != 1 or source.count(end) != 1:
            raise RuntimeError("reference dispatch proof extraction needs updating")
        return source.split(start, 1)[1].split(end, 1)[0]

    functions = section("  localparam int TAW = 16;", "  // window")
    body = section("      // ---- Q: footprint ranges\n", "      // ---- RLD's value")
    insert = section("            end else if (r_take) begin\n", "              advance();")
    # Factoring expressions introduces proof correspondence points, whose concrete
    # definitions are themselves checked by equiv_simple. Nothing is blackboxed.
    for expression, name in [("fp_part(fp_ops(p_cmd, D, S))", "_gen_p_parts"),
                             ("fp_sum(s_pp)", "_gen_s_products"),
                             ("fp_seg(q_cmd.op, q_fp)", "_gen_q_segmented")]:
        if body.count(expression) != 1:
            raise RuntimeError("reference dispatch expression changed")
        body = body.replace(expression, name)
    return f"""module seq_dispatch_reference import otpu_pkg::*; (
  input wire clk, rst, dispatch, have_free,
  input cmd_t dcmd,
  input wire [2:0] dunit,
  input wire [31:0] pc,
  output wire take, go, empty, valid,
  output cmd_t command,
  output wire [2:0] unit,
  output wire [31:0] address,
  output wire [321:0] footprint
);
  localparam int D={depth}, S={slices}, TAW=16;
{functions}
  logic p_v, s_v, q_v, c_v;
  cmd_t p_cmd, s_cmd, q_cmd, c_cmd;
  logic [2:0] p_unit, s_unit, q_unit, c_unit;
  logic [31:0] p_pc, s_pc, q_pc, c_pc;
  fpp_t s_pp;
  fpm_t q_pr;
  fp_t q_fp;
  fps_t c_fp;
  wire c_go = c_v && have_free;
  wire q_adv = !c_v || c_go;
  wire s_adv = !q_v || q_adv;
  wire p_adv = !s_v || s_adv;
  wire r_take = !p_v || p_adv;
  wire pipe_empty = !p_v && !s_v && !q_v && !c_v;
  always_comb q_fp = fp_ranges(q_cmd, q_pr, D, S);
  assign take=r_take, go=c_go, empty=pipe_empty, valid=c_v;
  assign command=c_cmd, unit=c_unit, address=c_pc, footprint=c_fp;
  wire [223:0] _gen_p_ops=fp_ops(p_cmd,D,S);
  wire [191:0] _gen_p_parts=fp_part(_gen_p_ops);
  wire [127:0] _gen_s_products=fp_sum(s_pp);
  wire [402:0] _gen_fp_ranges=q_fp;
  wire [321:0] _gen_q_segmented=fp_seg(q_cmd.op,q_fp);
  always_ff @(posedge clk) begin
    if(rst) begin p_v<=0; s_v<=0; q_v<=0; c_v<=0; end
    else begin
{body}
      if(dispatch && r_take) begin
{insert}
      end
    end
  end
endmodule
"""


def prove(cfg, mutation=None):
    depth, slices = cfg
    work = WORK / f"{depth}_{slices}"
    work.mkdir(parents=True, exist_ok=True)
    name = f"mutation_{mutation}" if mutation else "proof"
    source = work / (f"{name}.sv" if mutation else "native.sv")
    if mutation:
        original = (work / "native.sv").read_text()
        if mutation == "reset":
            pattern = r"(if \(rst\)\s+c_v <= )1'd0;"
            changed, count = re.subn(pattern, r"\g<1>1'd1;", original, count=1)
        else:
            changed, count = re.subn(r"(assign _gen_p_parts = )(.+);",
                                    r"\g<1>(\g<2>) ^ 192'd1;", original, count=1)
        if count != 1 or changed == original:
            raise RuntimeError(f"dispatch {mutation} mutation target missing")
        source.write_text(changed)
    else:
        subprocess.run([str(ROOT / ".lake/build/bin/opentpu-gen"), "seq-dispatch",
                        str(depth), str(slices), str(source)], cwd=ROOT, check=True)
        (work / "reference.sv").write_text(harness(depth, slices))
    extraction = work / f"{name}_extract.ys"
    netlist = work / f"{name}_registers.json"
    steps = work / f"{name}_steps.json"
    step_source = work / f"{name}_step_miter.sv"
    extraction.write_text(f"""read_slang --keep-hierarchy --top seq_dispatch_reference rtl/top/otpu_pkg.sv {work.relative_to(ROOT)}/reference.sv
rename seq_dispatch_reference gold
read_slang --keep-hierarchy --top otpu_seq_dispatch_sparkle {source.relative_to(ROOT)}
rename otpu_seq_dispatch_sparkle gate
proc
opt_clean
write_json {netlist.relative_to(ROOT)}
""")
    sources = [source, extraction, work / "reference.sv", ROOT / "rtl/top/otpu_pkg.sv",
               ROOT / "rtl/seq/otpu_seq.sv", ROOT / "OpenTPU/SeqDispatch.lean",
               ROOT / "OpenTPU/SeqLogic.lean", ROOT / "OpenTPU/Circuit.lean",
               ROOT / "OpenTPU/Generate.lean", ROOT / "tools/sparkle_transition.py",
               ROOT / "tools/prove_sparkle_seq_dispatch.py"]
    original_hashes = hashes(sources)
    with extraction.with_suffix(".log").open("w") as log:
        subprocess.run(["yosys", "-Q", "-T", "-s", str(extraction)], cwd=ROOT,
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
    raw = json.loads(netlist.read_text())
    transformed = expose_steps(raw, STATES)
    steps.write_text(json.dumps(transformed))
    step_source.write_text(step_miter(transformed))
    # Fail closed if the state projection silently accepts an incomplete mapping.
    try:
        expose_steps(raw, {k: v for k, v in STATES.items() if k != "c_v"})
    except RuntimeError:
        pass
    else:
        raise RuntimeError("transition checker accepted an omitted register")
    script = work / f"{name}.ys"
    if mutation:
        # A SAT counterexample is required: incomplete equiv reasoning alone is
        # insufficient evidence that a deliberate corruption was detected.
        stimulus = "-set rst 1" if mutation == "reset" else (
            "-set rst 0 -set state_p_v 1 -set state_s_v 0 -set state_p_cmd 0")
        commands = f"""read_verilog -sv {step_source.relative_to(ROOT)}
prep -top step_miter -flatten
opt -full
sat {stimulus} -prove ok 1 -verify -dump_vcd {work.relative_to(ROOT)}/{name}_failure.vcd
"""
    else:
        commands = """equiv_make gold gate equiv
hierarchy -top equiv
opt_clean
equiv_simple -short
equiv_status -assert
"""
    script.write_text(f"read_json {steps.relative_to(ROOT)}\n" + commands)
    inputs = sources + [script, netlist, steps, step_source]
    before = hashes(inputs)
    log = script.with_suffix(".log")
    with log.open("w") as stream:
        result = subprocess.run(["yosys", "-Q", "-T", "-s", str(script)], cwd=ROOT,
                                stdout=stream, stderr=subprocess.STDOUT, timeout=600)
    transcript = log.read_text()
    if hashes(inputs) != before or hashes(sources) != original_hashes:
        raise RuntimeError("dispatch proof inputs changed during proof")
    if mutation:
        if result.returncode == 0 or "proof did fail" not in transcript:
            raise RuntimeError(f"dispatch mutation not rejected by SAT; see {log}")
        print(f"PASS dispatch checker self-test: incorrect {mutation} rejected", flush=True)
    else:
        if result.returncode or "Equivalence successfully proven!" not in transcript:
            raise RuntimeError(f"dispatch induction failed; see {log}")
        print(f"PASS dispatch D={depth} S={slices}: all {sum(STATES.values())} state bits and outputs, concrete next-state equivalence", flush=True)
    return {"configuration": {"D": depth, "S": slices}, "input_sha256": before,
            "log": str(log), "mutation": mutation, "state_words": len(STATES),
            "state_bits": sum(STATES.values()), "arithmetic_abstraction": "none"}


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
        mutations = [prove(CONFIGS[0], m) for m in ["reset", "arithmetic"]] if args.self_test else []
        summary.write_text(json.dumps({"status": "passed", "proofs": proofs,
            "scope": "four dispatch stages, equal arbitrary initial registers, unrestricted inputs",
            "yosys": subprocess.check_output(["yosys", "-V"], text=True).strip(),
            "method": "complete current-state inputs; prove all next-state bits and outputs",
            "self_tests": mutations}, indent=2) + "\n")
    except BaseException as error:
        summary.write_text(json.dumps({"status": "failed", "error": str(error)}) + "\n")
        raise


if __name__ == "__main__":
    main()
