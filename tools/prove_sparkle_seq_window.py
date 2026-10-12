"""Check the complete native instruction-window state against the RTL.

The proof exposes every flip-flop and command-RAM cell after memory_map, with
arbitrary equal current state. All next-state bits and outputs must match.
Dispatch commands, footprints, unit handshakes and timestamps are unrestricted.
This covers window storage/control, not fetch, decoding, or the execution units.
"""
import argparse
import json
import re
import subprocess

from prove_sparkle_seq_logic import ROOT, hashes
from sparkle_transition import expose_steps, step_miter

WORK = ROOT / "build/sparkle/formal_seq_window"
CONFIGS = [2, 4, 8, 16, 32]


def harness(slots):
    source = (ROOT / "rtl/seq/otpu_seq.sv").read_text()

    def section(start, end):
        if source.count(start) != 1 or source.count(end) != 1:
            raise RuntimeError("reference window extraction needs updating")
        return source.split(start, 1)[1].split(end, 1)[0]

    functions = section("  localparam int TAW = 16;", "  // window")
    declarations = section("  // window\n", "  // ---- fetch:")
    completions = section("  logic [WIN-1:0] fin;\n", "  // ---- free slot")
    free = section("  always_comb q_fp = fp_ranges(q_cmd, q_pr, D, S);\n", "  // ---- loop-end handling")
    starts = section("  logic [WIN-1:0] same_started [NUNITS];\n", "  // MXU release:")
    release = section("  wire [SW-1:0] rel_slot = ", "\n\n  // Each unit's command")
    commands = section("  logic [SW-1:0] ucs [NUNITS];\n", "\n`ifndef SYNTHESIS\n  // shadow")
    needle = "assign ucmd[u] = cmd_t'(q);"
    if commands.count(needle) != 1:
        raise RuntimeError("reference command interface changed")
    commands = commands.replace(needle, "assign ucmd[240*u+:240] = q;")
    body = section("      // completions\n", "      // ---- Q: footprint ranges")
    sw = slots.bit_length()-1
    return f"""module seq_window_reference import otpu_pkg::*; (
  input logic clk,rst,c_v,
  input cmd_t c_cmd,
  input logic [2:0] c_unit,
  input logic [321:0] c_fp,
  input logic [4:0] urdy,udone,
  input logic [31:0] cyc,event_cyc,
  output wire [1199:0] ucmd,
  output logic [4:0] ustart,
  output logic urel,
  output wire [{slots-1}:0] valid_slots,
  output logic have_free,
  output logic [{sw-1}:0] free_slot,
  output wire c_go,
  output logic [{slots-1}:0] fin,
  output wire [{sw-1}:0] rel_slot,
  output wire can_rel,
  output wire [{5*sw-1}:0] command_slots,
  output wire [159:0] ready_cycles,
  output wire [4:0] busy
);
  localparam int WIN={slots}, SW={sw}, TAW=16;
{functions}
{declarations}
  assign c_go=c_v && have_free;
{completions}
  logic [WIN-1:0] ndep, ndepd;
{free}
  logic [WIN-1:0] same_started[NUNITS];
{starts}
  assign rel_slot = {release.replace('  wire          can_rel  = ', '  assign can_rel = ')}
  logic [SW-1:0] ucs[NUNITS];
{commands}
  always_ff @(posedge clk) begin
    ustart<='0; urel<=0;
    if(rst) begin
      uq_r<='0; sv<='0; sstarted<='0; sready<='0;
      for(int u=0;u<NUNITS;u++) begin uq_h[u]<='0; uq_t[u]<='0; end
      for(int i=0;i<WIN;i++) sdep[i]<='0;
    end else begin
{body}
    end
  end
  assign valid_slots=sv;
  for(genvar u=0;u<NUNITS;u++) begin
    assign command_slots[SW*u+:SW]=ucs[u];
    assign ready_cycles[32*u+:32]=sready[ucs[u]] ? srdy_c[ucs[u]] : event_cyc;
    assign busy[u]=!rst && uq_h[u]!=uq_t[u];
  end
endmodule
"""


def extract(slots, mutation=None):
    work = WORK / str(slots)
    work.mkdir(parents=True, exist_ok=True)
    name = f"mutation_{mutation}" if mutation else "proof"
    source = work / (f"{name}.sv" if mutation else "native.sv")
    if mutation:
        original = (work / "native.sv").read_text()
        if mutation == "command":
            changed, count = re.subn(r"(assign ucmd = )(.+);", r"\g<1>(\g<2>) ^ 1200'd1;", original, count=1)
        else:
            changed, count = re.subn(r"(assign _gen_window_go = )(.+);", r"\g<1>~(\g<2>);", original, count=1)
        if count != 1:
            raise RuntimeError("window mutation target missing")
        source.write_text(changed)
    else:
        subprocess.run([str(ROOT / ".lake/build/bin/opentpu-gen"), "seq-window", str(slots), str(source)],
                       cwd=ROOT, check=True)
        (work / "reference.sv").write_text(harness(slots))
    extraction = work / f"{name}_extract.ys"
    raw = work / f"{name}_registers.json"
    extraction.write_text(f"""read_slang --keep-hierarchy --top seq_window_reference rtl/top/otpu_pkg.sv {work.relative_to(ROOT)}/reference.sv
rename seq_window_reference gold
read_slang --keep-hierarchy --top otpu_seq_window_sparkle {source.relative_to(ROOT)}
rename otpu_seq_window_sparkle gate
proc
memory_map
opt_clean
write_json {raw.relative_to(ROOT)}
""")
    with extraction.with_suffix(".log").open("w") as log:
        subprocess.run(["yosys", "-Q", "-T", "-s", str(extraction)], cwd=ROOT,
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
    return work, name, source, extraction, raw


def correspondence(raw, slots):
    sw = slots.bit_length()-1
    gold = raw["modules"]["gold"]["netnames"]
    gate = raw["modules"]["gate"]["netnames"]
    states = {}

    def state(name, width, reference, native=None, offset=0):
        native = native or name
        gb = gold[reference]["bits"][offset:offset+width]
        nb = gate[native]["bits"]
        if len(gb) != width or len(nb) != width:
            raise RuntimeError(f"bad window state mapping: {name}")
        # State ports use stable simple identifiers even for RAM/array names.
        for nets, bits in [(gold, gb), (gate, nb)]:
            nets[name] = {"hide_name": 0, "bits": bits, "attributes": {}}
        states[name] = width

    for n in ["sv", "sstarted", "sready"]:
        state(n, slots, n)
    state("ustart_q", 5, "ustart")
    state("urel_q", 1, "urel")
    state("uq_r", sw+1, "uq_r")
    for i in range(slots):
        for n, w in [("older", slots), ("soh", 5), ("sdep", slots), ("sdepd", slots),
                     ("sfp", 322), ("srdy_c", 32)]:
            state(f"{n}{i}", w, f"{n}[{i}]")
    for u in range(5):
        for n in ["uq_h", "uq_t"]:
            state(f"{n}{u}", sw+1, f"{n}[{u}]")
        state(f"ucs{u}", sw, f"ucs[{u}]")
        state(f"cmd_q{u}", 240, f"g_cmd[{u}].q")
        for i in range(slots):
            # Slang flattens the inner ascending unpacked [0:WIN-1] array
            # with element WIN-1 least significant (packed vectors differ).
            state(f"uq{u}_{i}", sw, f"uq[{u}]", f"queue_mem{u}[{i}]", offset=(slots-1-i)*sw)
            state(f"command_cell{u}_{i}", 240, f"g_cmd[{u}].m[{i}]", f"cmd_mem{u}[{i}]")
    # Concrete intermediate correspondences keep SAT cones small. Every named
    # equivalence must prove; these are not assumed/arbitrary cutpoints.
    for native, reference in [("finish", "fin"), ("have_free", "have_free"),
                              ("free_slot", "free_slot"), ("ndep", "ndep"), ("ndepd", "ndepd"),
                              ("mrdy", "mrdy"), ("crdy", "crdy"), ("can_release", "can_rel"),
                              ("window_go", "c_go"), ("rel_slot", "rel_slot")]:
        gold[f"_gen_{native}"] = dict(gold[reference])
    for u in range(5):
        for native, reference, width in [("can_start", "can_start", 1), ("start_slot", "start_slot", sw),
                                          ("selected", "sel", slots), ("same_started", "same_started", slots),
                                          ("candidate_any", "cand_any", 1)]:
            index = 4-u if reference in ["start_slot", "sel", "same_started"] else u
            gold[f"_gen_{native}{u}"] = {"hide_name": 0,
                "bits": gold[reference]["bits"][index*width:(index+1)*width], "attributes": {}}
    return states


def prove(slots, mutation=None):
    work, name, source, extraction, raw_path = extract(slots, mutation)
    raw = json.loads(raw_path.read_text())
    states = correspondence(raw, slots)
    steps = work / f"{name}_steps.json"
    transformed = expose_steps(raw, states)
    steps.write_text(json.dumps(transformed))
    step_source = work / f"{name}_step_miter.sv"
    step_source.write_text(step_miter(transformed))
    script = work / f"{name}.ys"
    if mutation:
        commands = f"""read_verilog -sv {step_source.relative_to(ROOT)}
prep -top step_miter -flatten
opt -full
sat -prove ok 1 -verify -dump_vcd {work.relative_to(ROOT)}/{name}_failure.vcd
"""
    else:
        commands = """equiv_make gold gate equiv
hierarchy -top equiv
opt -full
equiv_simple -short
equiv_status -assert
"""
    script.write_text(f"read_json {steps.relative_to(ROOT)}\n" + commands)
    files = [source, extraction, raw_path, steps, step_source, script, work / "reference.sv",
             ROOT / "rtl/top/otpu_pkg.sv", ROOT / "rtl/seq/otpu_seq.sv",
             ROOT / "OpenTPU/SeqWindow.lean", ROOT / "OpenTPU/SeqSchedule.lean",
             ROOT / "OpenTPU/SeqLogic.lean", ROOT / "OpenTPU/Circuit.lean",
             ROOT / "OpenTPU/Generate.lean", ROOT / "tools/sparkle_transition.py",
             ROOT / "tools/prove_sparkle_seq_window.py"]
    before = hashes(files)
    log = script.with_suffix(".log")
    with log.open("w") as stream:
        result = subprocess.run(["yosys", "-Q", "-T", "-s", str(script)], cwd=ROOT,
                                stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
    transcript = log.read_text()
    if hashes(files) != before:
        raise RuntimeError("window proof input changed during proof")
    if mutation:
        if result.returncode == 0 or "proof did fail" not in transcript:
            raise RuntimeError(f"window {mutation} mutation not rejected by SAT; see {log}")
        print(f"PASS window checker self-test: incorrect {mutation} rejected", flush=True)
    else:
        if result.returncode or "Equivalence successfully proven!" not in transcript:
            raise RuntimeError(f"window transition proof failed; see {log}")
        print(f"PASS window WIN={slots}: {sum(states.values())} state bits and all outputs", flush=True)
    return {"slots": slots, "state_bits": sum(states.values()), "state_words": len(states),
            "input_sha256": before, "log": str(log), "mutation": mutation}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--slots", type=int, choices=CONFIGS)
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    summary = WORK / (f"summary_{args.slots}.json" if args.slots else "summary.json")
    summary.write_text(json.dumps({"status": "running"}) + "\n")
    try:
        with (WORK / "build.log").open("w") as log:
            subprocess.run(["lake", "build", "OpenTPU", "opentpu-gen"], cwd=ROOT,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
        proofs = []
        for w in ([args.slots] if args.slots else CONFIGS):
            proofs.append(prove(w))
            summary.write_text(json.dumps({"status": "running", "proofs": proofs}, indent=2) + "\n")
        mutations = [prove(2, m) for m in ["command", "dispatch"]] if args.self_test else []
        summary.write_text(json.dumps({"status": "passed", "proofs": proofs,
            "scope": "complete window next-state and output equivalence from equal arbitrary state",
            "yosys": subprocess.check_output(["yosys", "-V"], text=True).strip(),
            "self_tests": mutations}, indent=2) + "\n")
    except BaseException as error:
        summary.write_text(json.dumps({"status": "failed", "error": str(error), "proofs": locals().get("proofs", [])}) + "\n")
        raise


if __name__ == "__main__":
    main()
