"""Full native sequencer state/output equivalence against the original RTL.

All register and RAM bits are exposed as equal current-state inputs; concrete
next-state logic and outputs are compared. The ISA's loop-depth bound (four)
is assumed, including no push onto a full stack. Other state is arbitrary.
No arithmetic abstraction.
The reference receives only named-expression factoring for proof correspondence.
"""
import argparse
import json
import re
import subprocess

from prove_sparkle_seq_logic import ROOT, hashes
from prove_sparkle_seq_window import correspondence as window_correspondence
from sparkle_transition import expose_steps, step_miter

WORK = ROOT / "build/sparkle/formal_seq"
CONFIGS = [(16, 32, 1, 2), (32, 64, 2, 4), (64, 128, 1, 4)]

DEPTH_ASSUMPTIONS = """
  always @* begin
    assume(state_sp <= 3'd4);
    assume(!(state_ir_v && !state_stopping && !state_halted_q && !state_rl_wait &&
      state_ir[7:0]==8'h04 && state_lp && state_lp_cnt!=0) || state_sp<3'd4);
  end
"""


def equiv_guard(netlist):
    ports = netlist["modules"]["gold"]["ports"]
    declarations = [f"{p['direction']} wire [{len(p['bits'])-1}:0] {name}" for name, p in ports.items()]
    return ("module seq_equiv_guard(\n" + ",\n".join(declarations) +
            "\n);\nequiv core(.*);\n" + DEPTH_ASSUMPTIONS + "endmodule\n")


def reference():
    source = (ROOT / "rtl/seq/otpu_seq.sv").read_text()
    for old, new in [("fp_part(fp_ops(p_cmd, D, S))", "_gen_p_parts"),
                     ("fp_sum(s_pp)", "_gen_s_products"),
                     ("fp_seg(q_cmd.op, q_fp)", "_gen_q_segmented")]:
        if source.count(old) != 1:
            raise RuntimeError("reference sequencer expression changed")
        source = source.replace(old, new)
    extra = """
  wire [223:0] _gen_p_ops=fp_ops(p_cmd,D,S);
  wire [191:0] _gen_p_parts=fp_part(_gen_p_ops);
  wire [127:0] _gen_s_products=fp_sum(s_pp);
  wire [402:0] _gen_fp_ranges=q_fp;
  wire [321:0] _gen_q_segmented=fp_seg(q_cmd.op,q_fp);
"""
    source, count = re.subn(r"(fps_t\s+c_fp;)", r"\g<1>" + extra, source, count=1)
    if count != 1:
        raise RuntimeError("reference sequencer stage declarations changed")
    return source


def correspondence(raw, cfg):
    words, depth, slices, slots = cfg
    states = window_correspondence(raw, slots)
    gold = raw["modules"]["gold"]["netnames"]
    gate = raw["modules"]["gate"]["netnames"]

    def state(name, width, reference=None, native=None, offset=0):
        reference = reference or name
        native = native or name
        gb = gold[reference]["bits"][offset:offset+width]
        nb = gate[native]["bits"]
        if len(gb) != width or len(nb) != width:
            raise RuntimeError(f"bad sequencer state mapping: {name}")
        for nets, bits in [(gold, gb), (gate, nb)]:
            nets[name] = {"hide_name": 0, "bits": bits, "attributes": {}}
        states[name] = width

    for stage in ["p", "s", "q", "c"]:
        for field, width in [("v", 1), ("cmd", 240), ("unit", 3), ("pc", 32)]:
            state(f"{stage}_{field}", width)
    for field, width in [("s_pp", 192), ("q_pr", 128), ("c_fp", 322),
                         ("pc", 32), ("cyc", 32), ("fa", 32), ("ir", 256), ("ir_v", 1),
                         ("irow", depth*8), ("sp", 3), ("stopping", 1), ("rl_wait", 1),
                         ("rl_rd", 4), ("lp", 1), ("lp_cnt", 32), ("lp_len", 32)]:
        state(field, width)
    for field, width in [("halted", 1), ("error", 1), ("icount", 32),
                         ("ch_req", 1), ("ch_addr", 32), ("ch_n", 32)]:
        state(f"{field}_q", width, field)
    for i in range(16):
        state(f"R{i}", 32, f"R[{i}]")
    for i in range(4):
        for field in ["stk_start", "stk_end"]:
            state(f"{field}{i}", 32, f"{field}[{i}]", f"start_mem[{i}]" if field == "stk_start" else None)
        state(f"stk_rem{i}", 32, "stk_rem", offset=(3-i)*32)
    for i in range(words // (8*(depth//32))):
        state(f"instruction_cell{i}", depth*8, f"imem[{i}]", f"imem[{i}]")
    for field, offset, width in [("ret", 0, 2), ("busy", 2, 5), ("e", 7, 32),
                                  ("g_slot", 39, 5), ("g", 44, 1), ("d_w3", 235, 32),
                                  ("d_w2", 267, 32), ("d_w1", 299, 32), ("d_op", 331, 8),
                                  ("d_pc", 339, 32), ("d_slot", 371, 5), ("d", 376, 1), ("cyc", 377, 32)]:
        state(f"ev_{field}", width, "evq", offset=offset)
    for native, original in [("ld", "ld"), ("fe", "fe"), ("fa_n", "fa_n"),
                              ("fetch_successor", "succ"), ("loop_zero", "lp_z"),
                              ("at_end", "at_end"), ("rva", "lp_a"), ("r_ret", "r_ret"),
                              ("r_take", "r_take"), ("c_go", "c_go"), ("p_adv", "p_adv"),
                              ("q_adv", "q_adv"), ("s_adv", "s_adv"), ("pipe_empty", "pipe_empty"),
                              ("decoded_command", "dcmd"), ("decoded_unit", "dunit")]:
        gold[f"_gen_{native}"] = dict(gold[original])
    # Original unpacked ports [0:N-1] flatten MS element first; the native ABI
    # puts array element zero least significant. Packed ports already agree.
    module = raw["modules"]["gold"]
    for port, width, count in [("ucmd", 240, 5), ("rinit", 32, 8)]:
        bits = module["ports"][port]["bits"]
        value = [bit for i in reversed(range(count)) for bit in bits[i*width:(i+1)*width]]
        module["ports"][port]["bits"] = value
        module["netnames"][port]["bits"] = value
    return states


def prove(cfg, mutation=False):
    words, depth, slices, slots = cfg
    work = WORK / "_".join(map(str, cfg))
    work.mkdir(parents=True, exist_ok=True)
    name = "mutation" if mutation else "proof"
    native = work / ("mutated.sv" if mutation else "native.sv")
    if mutation:
        original = (work / "native.sv").read_text()
        changed, count = re.subn(r"assign halted = halted_q;", "assign halted = ~halted_q;", original, count=1)
        if count != 1:
            raise RuntimeError("sequencer mutation target missing")
        native.write_text(changed)
    else:
        subprocess.run([str(ROOT / ".lake/build/bin/opentpu-gen"), "seq-core", *map(str, cfg), str(native)],
                       cwd=ROOT, check=True)
        (work / "reference.sv").write_text(reference())
    extraction = work / f"{name}_extract.ys"
    registers = work / f"{name}_registers.json"
    extraction.write_text(f"""read_slang --keep-hierarchy --top otpu_seq -GIMEM_WORDS={words} -GD={depth} -GS={slices} -GWIN={slots} rtl/top/otpu_pkg.sv {work.relative_to(ROOT)}/reference.sv
rename otpu_seq gold
read_slang --keep-hierarchy --top otpu_seq_sparkle {native.relative_to(ROOT)}
rename otpu_seq_sparkle gate
proc
memory_map
# Retain the unobservable R0 flop for a complete state correspondence. Buffer
# cleanup is still needed so every named state net refers to its flop's Q bits.
setattr -set keep 1 w:R0
opt_clean
write_json {registers.relative_to(ROOT)}
""")
    with extraction.with_suffix(".log").open("w") as log:
        subprocess.run(["yosys", "-Q", "-T", "-s", str(extraction)], cwd=ROOT,
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
    raw = json.loads(registers.read_text())
    states = correspondence(raw, cfg)
    transformed = expose_steps(raw, states)
    steps = work / f"{name}_steps.json"
    steps.write_text(json.dumps(transformed))
    step_source = work / f"{name}_step_miter.sv"
    step_source.write_text(step_miter(transformed).replace("endmodule", DEPTH_ASSUMPTIONS + "endmodule"))
    guard_source = work / f"{name}_guard.sv"
    guard_source.write_text(equiv_guard(transformed))
    script = work / f"{name}.ys"
    if mutation:
        commands = f"""read_verilog -formal -sv {step_source.relative_to(ROOT)}
prep -top step_miter -flatten
chformal -lower
opt -full
sat -set-assumes -set rst 1 -prove ok 1 -verify -dump_vcd {work.relative_to(ROOT)}/failure.vcd
"""
    else:
        commands = f"""equiv_make gold gate equiv
read_verilog -formal -sv {guard_source.relative_to(ROOT)}
hierarchy -top seq_equiv_guard
proc
flatten
chformal -lower
opt -full
equiv_simple -short -nogroup -set-assumes
equiv_status -assert
"""
    script.write_text(f"read_json {steps.relative_to(ROOT)}\n" + commands)
    files = [native, work / "reference.sv", extraction, registers, steps, step_source, guard_source, script,
             ROOT / "rtl/seq/otpu_seq.sv", ROOT / "rtl/top/otpu_pkg.sv",
             ROOT / "docs/isa.md",
             *[ROOT / "OpenTPU" / f"{n}.lean" for n in ["Seq", "SeqFetch", "SeqWindow", "SeqDispatch",
                                                         "SeqSchedule", "SeqLogic", "Circuit", "Generate"]],
             ROOT / "tools/prove_sparkle_seq.py", ROOT / "tools/prove_sparkle_seq_window.py",
             ROOT / "tools/sparkle_transition.py"]
    before = hashes(files)
    log = script.with_suffix(".log")
    with log.open("w") as stream:
        result = subprocess.run(["yosys", "-Q", "-T", "-s", str(script)], cwd=ROOT,
                                stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
    transcript = log.read_text()
    if hashes(files) != before:
        raise RuntimeError("sequencer proof inputs changed during proof")
    if mutation:
        if result.returncode == 0 or "proof did fail" not in transcript:
            raise RuntimeError(f"sequencer mutation not rejected by SAT; see {log}")
        print("PASS sequencer checker self-test: incorrect HALT output rejected", flush=True)
    else:
        if result.returncode or "Equivalence successfully proven!" not in transcript:
            raise RuntimeError(f"full sequencer transition proof failed; see {log}")
        print(f"PASS sequencer {cfg}: all {sum(states.values())} state bits and outputs", flush=True)
    return {"configuration": dict(zip(["IMEM_WORDS", "D", "S", "WIN"], cfg)),
            "state_bits": sum(states.values()), "input_sha256": before, "log": str(log)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--first", action="store_true")
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    summary = WORK / ("summary_first.json" if args.first else "summary.json")
    summary.write_text(json.dumps({"status": "running"}) + "\n")
    try:
        with (WORK / "build.log").open("w") as log:
            subprocess.run(["lake", "build", "OpenTPU", "opentpu-gen"], cwd=ROOT,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
        proofs = [prove(cfg) for cfg in (CONFIGS[:1] if args.first else CONFIGS)]
        mutation = prove(CONFIGS[0], True) if args.self_test else None
        summary.write_text(json.dumps({"status": "passed", "proofs": proofs,
            "scope": "complete sequencer next-state/output equivalence from equal state within the ISA depth-four loop contract",
            "yosys": subprocess.check_output(["yosys", "-V"], text=True).strip(),
            "self_test": mutation}, indent=2) + "\n")
    except BaseException as error:
        summary.write_text(json.dumps({"status": "failed", "error": str(error)}) + "\n")
        raise


if __name__ == "__main__":
    main()
