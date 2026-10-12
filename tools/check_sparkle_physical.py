"""Check that Yosys receives native register and memory attributes.

Also compares current generated circuits with proven functional Verilog tokens.
This is not a placement or timing qualification.
"""
from pathlib import Path
import hashlib
import json
import re
import subprocess

from sparkle_provenance import verify

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build/sparkle/physical"
GEN = ROOT / ".lake/build/bin/opentpu-gen"


def functional_tokens(text):
    # Generated sources contain no escaped identifiers or comment-like strings.
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"\(\*[^*]*\*\)", "", text)
    return re.sub(r"\s+", "", text)


def inspect(name, args, top, expected, expected_memories=None):
    source = WORK / f"{name}.sv"
    subprocess.run([str(GEN), *map(str, args), str(source)], cwd=ROOT, check=True)
    netlist = WORK / f"{name}.json"
    script = WORK / f"{name}.ys"
    package = "rtl/top/otpu_pkg.sv " if args[0] == "seq" else ""
    script.write_text(f"read_slang --top {top} {package}{source.relative_to(ROOT)}\nproc\nwrite_json {netlist.relative_to(ROOT)}\n")
    with (WORK / f"{name}.log").open("w") as log:
        subprocess.run(["yosys", "-Q", "-T", "-s", str(script)], cwd=ROOT,
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)
    module = json.loads(netlist.read_text())["modules"][top]
    wires = module["netnames"]
    for signal, attrs in expected.items():
        actual = wires[signal]["attributes"]
        for attr, value in attrs.items():
            got = actual.get(attr)
            if isinstance(value, int):
                assert got is not None and int(got, 2) == value, (name, signal, attr, got)
            else:
                assert got == value, (name, signal, attr, got)
    for memory, attrs in (expected_memories or {}).items():
        actual = module["memories"][memory]["attributes"]
        for attr, value in attrs.items():
            assert actual.get(attr) == value, (name, memory, attr, actual.get(attr))
    print(f"PASS physical attributes: {name}, {len(expected)} registers, "
          f"{len(expected_memories or {})} memories", flush=True)
    return {"case": name, "checked": expected, "memories": expected_memories or {}, "input_sha256": {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in [source, script]}}


def check_proven_tokens():
    results = []
    for family in ["tmem", "vtree"]:
        proof = json.loads((ROOT / f"build/sparkle/formal_{family}/summary.json").read_text())
        assert proof["status"] == "passed", f"run the {family} proofs first"
        for index, entry in enumerate(proof["proofs"]):
            for path, digest in entry["input_sha256"].items():
                assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == digest, path
            if family == "vtree":
                args = ["vtree-core", entry["lanes"], entry["latency"]]
            else:
                c = entry["configuration"]
                args = ["tmem-core", *[c[k] for k in ["WORDS", "LANES", "NRP", "NWP", "WPB", "GEN_R", "GEN_W", "SH_HOST", "SH_MASK"]]]
            old = next(p for p in entry["input_sha256"] if p.endswith("/native.sv"))
            assert hashlib.sha256((ROOT/old).read_bytes()).hexdigest() == entry["input_sha256"][old]
            new = WORK / f"{family}_{index}_current.sv"
            subprocess.run([str(GEN), *map(str, args), str(new)], cwd=ROOT, check=True)
            assert functional_tokens(new.read_text()) == functional_tokens((ROOT/old).read_text()), args
            results.append({"proven_source": old, "proven_sha256": entry["input_sha256"][old],
                            "current_source": str(new.relative_to(ROOT)),
                            "current_sha256": hashlib.sha256(new.read_bytes()).hexdigest()})
        print(f"PASS {family}: functional tokens unchanged from proven circuits", flush=True)
    return results


def check_seq_tokens():
    results = []
    for family in ["seq", "seq_window"]:
        proof = json.loads((ROOT / f"build/sparkle/formal_{family}/summary.json").read_text())
        assert proof["status"] == "passed", f"run the {family} proofs first"
        for index, entry in enumerate(proof["proofs"]):
            resolved = verify(entry["input_sha256"])
            if family == "seq":
                c = entry["configuration"]
                args = ["seq", *[c[k] for k in ["IMEM_WORDS", "D", "S", "WIN"]]]
            else:
                args = ["seq-window", entry["slots"]]
            old = next(p for p in entry["input_sha256"] if p.endswith("/native.sv"))
            new = WORK / f"{family}_{index}_current.sv"
            subprocess.run([str(GEN), *map(str, args), str(new)], cwd=ROOT, check=True)
            core = new.read_text()
            if family == "seq":
                # Only the native core has synthesis attributes; the ABI wrapper
                # is covered by the full-system differential integration tests.
                core = core.split("\nmodule otpu_seq import", 1)[0]
            assert functional_tokens(core) == functional_tokens((ROOT / resolved[old]).read_text()), args
            results.append({"proven_source": old, "proven_sha256": entry["input_sha256"][old],
                            "current_source": str(new.relative_to(ROOT)),
                            "current_sha256": hashlib.sha256(new.read_bytes()).hexdigest(),
                            "verified_proof_inputs": resolved})
        print(f"PASS {family}: functional tokens unchanged from proven circuits", flush=True)
    return results


def check_conversion_tokens(kind="float-convert", family="float_convert"):
    proof = json.loads((ROOT / f"build/sparkle/formal_{family}/summary.json").read_text())
    assert proof["status"] == "passed", f"run the {kind} proofs first"
    entry = proof["proof"]
    resolved = verify(entry["input_sha256"])
    old = next(p for p in entry["input_sha256"] if p.endswith("/native.sv"))
    new = WORK / f"{family}_current.sv"
    subprocess.run([str(GEN), kind, str(new)], cwd=ROOT, check=True)
    assert functional_tokens(new.read_text()) == functional_tokens((ROOT / resolved[old]).read_text())
    print(f"PASS {kind}: production output matches proven helper circuits", flush=True)
    return [{"proven_source": old, "proven_sha256": entry["input_sha256"][old],
             "current_source": str(new.relative_to(ROOT)),
             "current_sha256": hashlib.sha256(new.read_bytes()).hexdigest(),
             "verified_proof_inputs": resolved}]


def check_qscale_tokens():
    proof = json.loads((ROOT / "build/sparkle/formal_qscale/summary.json").read_text())
    assert proof["status"] == "passed", "run the quantizer scale proofs first"
    results = []
    assert len(proof["proofs"]) == len(proof["arithmetic"])
    for index, (entry, arithmetic) in enumerate(zip(proof["proofs"], proof["arithmetic"])):
        assert entry["configuration"] == arithmetic["configuration"]
        resolved = verify(entry["input_sha256"])
        arithmetic_inputs = verify(arithmetic["input_sha256"])
        old = next(p for p in entry["input_sha256"] if p.endswith("/native.sv"))
        assert entry["input_sha256"][old] == arithmetic["input_sha256"][old]
        new = WORK / f"qscale_{index}_current.sv"
        subprocess.run([str(GEN), "qscale", *map(str, entry["configuration"]), str(new)], cwd=ROOT, check=True)
        code = new.read_text()
        marker = "`define OTPU_SPARKLE_QSCALE\n"
        assert code.startswith(marker)
        core, wrapper = code[len(marker):].split("\nmodule otpu_qscale #", 1)
        assert wrapper
        assert functional_tokens(core) == functional_tokens((ROOT / resolved[old]).read_text())
        results.append({"proven_source": old, "proven_sha256": entry["input_sha256"][old],
                        "current_source": str(new.relative_to(ROOT)),
                        "current_sha256": hashlib.sha256(new.read_bytes()).hexdigest(),
                        "verified_proof_inputs": resolved, "verified_arithmetic_inputs": arithmetic_inputs})
    print("PASS qscale: production cores match both composition and arithmetic proof inputs", flush=True)
    return results



def check_quant_datapath_tokens(family):
    proof = json.loads((ROOT / f"build/sparkle/formal_{family}/summary.json").read_text())
    assert proof["status"] == "passed", f"run the {family} proofs first"
    assert len(proof["proofs"]) == len(proof["arithmetic"])
    results = []
    for index, (entry, arithmetic) in enumerate(zip(proof["proofs"], proof["arithmetic"])):
        assert entry["lanes"] == arithmetic["lanes"]
        resolved = verify(entry["input_sha256"])
        arithmetic_inputs = verify(arithmetic["input_sha256"])
        old = next(p for p in entry["input_sha256"] if p.endswith("/native.sv"))
        assert entry["input_sha256"][old] == arithmetic["input_sha256"][old]
        new = WORK / f"{family}_{index}_current.sv"
        subprocess.run([str(GEN), family, str(entry["lanes"]), str(new)], cwd=ROOT, check=True)
        code = new.read_text()
        marker = f"`define OTPU_SPARKLE_{family.upper()}\n"
        assert code.startswith(marker)
        core, wrapper = code[len(marker):].split(f"\nmodule otpu_{family} #", 1)
        assert wrapper
        assert functional_tokens(core) == functional_tokens((ROOT / resolved[old]).read_text())
        results.append({"proven_source": old, "proven_sha256": entry["input_sha256"][old],
                        "current_source": str(new.relative_to(ROOT)),
                        "current_sha256": hashlib.sha256(new.read_bytes()).hexdigest(),
                        "verified_proof_inputs": resolved, "verified_arithmetic_inputs": arithmetic_inputs})
    print(f"PASS {family}: production cores match composition and arithmetic proof inputs", flush=True)
    return results



def module_tokens(code):
    modules = {}
    for match in re.finditer(r"^module\s+(\w+)\b.*?^endmodule\s*$", code, re.MULTILINE | re.DOTALL):
        name = match.group(1)
        assert name not in modules, f"duplicate module {name}"
        modules[name] = functional_tokens(match.group(0))
    return modules


def check_quant_tokens():
    proof = json.loads((ROOT / "build/sparkle/formal_quant/summary.json").read_text())
    assert proof["status"] == "passed", "run the complete quantizer proofs first"
    dependencies = {}
    for family in ["qread", "qscale", "qwrite"]:
        data = json.loads((ROOT / f"build/sparkle/formal_{family}/summary.json").read_text())
        assert data["status"] == "passed"
        dependencies[family] = data
    results = []
    for index, entry in enumerate(proof["proofs"]):
        depth, lanes = entry["configuration"]
        resolved = verify(entry["input_sha256"])
        old = next(p for p in entry["input_sha256"] if p.endswith("/native.sv"))
        new = WORK / f"quant_{index}_current.sv"
        subprocess.run([str(GEN), "quant", str(depth), str(lanes), str(new)], cwd=ROOT, check=True)
        core, wrapper = new.read_text().split("\nmodule otpu_quant import", 1)
        assert wrapper
        assert functional_tokens(core) == functional_tokens((ROOT / resolved[old]).read_text())
        actual = module_tokens(core)
        expected = {"otpu_quant_sparkle": actual["otpu_quant_sparkle"]}
        child_evidence = []
        for family, data in dependencies.items():
            key, value = ("configuration", [2,4,2]) if family == "qscale" else ("lanes", lanes)
            sub = next(p for p in data["proofs"] if p[key] == value)
            arithmetic = next(p for p in data["arithmetic"] if p[key] == value)
            sub_inputs = verify(sub["input_sha256"])
            arithmetic_inputs = verify(arithmetic["input_sha256"])
            sub_source = next(p for p in sub["input_sha256"] if p.endswith("/native.sv"))
            assert arithmetic["input_sha256"][sub_source] == sub["input_sha256"][sub_source]
            children = module_tokens((ROOT / sub_inputs[sub_source]).read_text())
            assert children and not (children.keys() & expected.keys())
            expected.update(children)
            child_evidence.append({"family": family, "verified_proof_inputs": sub_inputs,
                                   "verified_arithmetic_inputs": arithmetic_inputs})
        assert actual == expected, "embedded pipeline differs from its independently proven circuit"
        results.append({"proven_source": old, "proven_sha256": entry["input_sha256"][old],
                        "current_source": str(new.relative_to(ROOT)),
                        "current_sha256": hashlib.sha256(new.read_bytes()).hexdigest(),
                        "verified_proof_inputs": resolved, "embedded_pipeline_proofs": child_evidence})
    print("PASS quant: controller/storage and every embedded pipeline match their proof inputs", flush=True)
    return results


def check_dma_tokens():
    proof = json.loads((ROOT / "build/sparkle/formal_dma/summary.json").read_text())
    assert proof["status"] == "passed", "run the DMA proofs first"
    results = []
    for index, entry in enumerate(proof["proofs"]):
        resolved = verify(entry["input_sha256"])
        d, lanes, depth, streams = entry["configuration"]
        old = next(p for p in entry["input_sha256"] if p.endswith("/native.sv"))
        new = WORK / f"dma_{index}_current.sv"
        subprocess.run([str(GEN), "dma-core", *map(str, [d, lanes, depth, int(streams)]), str(new)], cwd=ROOT, check=True)
        assert functional_tokens(new.read_text()) == functional_tokens((ROOT / resolved[old]).read_text())
        results.append({"proven_source": old, "proven_sha256": entry["input_sha256"][old],
                        "current_source": str(new.relative_to(ROOT)),
                        "current_sha256": hashlib.sha256(new.read_bytes()).hexdigest(),
                        "verified_proof_inputs": resolved})
    print("PASS DMA: production controller and memories match proven circuits", flush=True)
    return results


def check_se_microcode_tokens():
    proof = json.loads((ROOT / "build/sparkle/formal_se_microcode/summary.json").read_text())
    assert proof["status"] == "passed", "run the SE microcode proofs first"
    results = []
    for entry in proof["proofs"]:
        resolved = verify(entry["input_sha256"])
        old = next(p for p in entry["input_sha256"] if p.endswith("/native.sv"))
        new = WORK / f"se_microcode_{entry['stages']}_current.sv"
        subprocess.run([str(GEN), "se-microcode", str(entry["stages"]), str(new)], cwd=ROOT, check=True)
        assert functional_tokens(new.read_text()) == functional_tokens((ROOT / resolved[old]).read_text())
        results.append({"proven_source": old, "proven_sha256": entry["input_sha256"][old],
                        "current_source": str(new.relative_to(ROOT)),
                        "current_sha256": hashlib.sha256(new.read_bytes()).hexdigest(),
                        "verified_proof_inputs": resolved})
    print("PASS SE microcode: production ROMs match proven circuits", flush=True)
    return results


def check_se_composite_tokens():
    results = []
    for external in [True, False]:
        suffix = '' if external else '_internal'
        proof = json.loads((ROOT / f'build/sparkle/formal_se_composite/summary{suffix}.json').read_text())
        assert proof['status'] == 'passed', 'run the composite engine proofs first'
        for index, entry in enumerate(proof['proofs']):
            assert entry['external'] == external
            resolved = verify(entry['input_sha256'])
            old = next(p for p in entry['input_sha256'] if p.endswith('/native.sv'))
            new = WORK / f'se_composite{suffix}_{index}_current.sv'
            subprocess.run([str(GEN), 'se-comp-core', *map(str, entry['configuration']),
                            str(int(external)), str(new)], cwd=ROOT, check=True)
            assert functional_tokens(new.read_text()) == functional_tokens((ROOT / resolved[old]).read_text())
            results.append({'proven_source': old, 'proven_sha256': entry['input_sha256'][old],
                            'current_source': str(new.relative_to(ROOT)),
                            'current_sha256': hashlib.sha256(new.read_bytes()).hexdigest(),
                            'verified_proof_inputs': resolved})
    print('PASS composite: production cores match external and internal composition proofs', flush=True)
    return results


def check_actram_tokens():
    proof = json.loads((ROOT / 'build/sparkle/formal_actram/summary.json').read_text())
    assert proof['status'] == 'passed', 'run the ACT RAM controller proofs first'
    results = []
    for index, entry in enumerate(proof['proofs']):
        resolved = verify(entry['input_sha256'])
        old = next(p for p in resolved if p.endswith('/native.sv'))
        new = WORK / f'actram_{index}_current.sv'
        subprocess.run([str(GEN), 'actram-core', *map(str, entry['configuration']), str(new)], cwd=ROOT, check=True)
        assert functional_tokens(new.read_text()) == functional_tokens((ROOT / resolved[old]).read_text())
        results.append({'proven_source': old, 'proven_sha256': entry['input_sha256'][old],
                        'current_source': str(new.relative_to(ROOT)),
                        'current_sha256': hashlib.sha256(new.read_bytes()).hexdigest(),
                        'verified_proof_inputs': resolved})
    print('PASS ACT RAM: production controller and packed RAM match proven circuits', flush=True)
    return results


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    summary = WORK / "summary.json"
    summary.write_text(json.dumps({"status": "running"})+"\n")
    try:
        with (WORK / "build.log").open("w") as log:
            subprocess.run(["lake", "build", "OpenTPU", "opentpu-gen", "opentpu-test"], cwd=ROOT,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
        subprocess.run([str(ROOT / ".lake/build/bin/opentpu-test")], cwd=ROOT, check=True)
        keep = {"keep": "true"}
        endpoint = {"keep": "true", "shreg_extract": "no"}
        results = [inspect("duplicate", ["fpipe"], "otpu_fadd2_sparkle", {"result_copy": keep}),
                   inspect("mul_padding", ["float", 3, 7], "otpu_fmul_sparkle_3", {"pad0": endpoint}),
                   inspect("add_padding", ["float", 3, 7], "otpu_fadd_sparkle_7", {"pad2": endpoint})]
        act = {f"{name}_{stage}": {"shreg_extract": "no"}
               for name in ["we", "w_row", "w_idx", "w_data", "w_dup", "w_off", "swe", "s_row", "s_blk", "s_data"]
               for stage in ["i", "h"]}
        act.update({f"{name}{j}_{p}": keep for j in range(4) for p in range(4) for name in ["wb", "wsel", "wg"]})
        results.append(inspect("actram", ["actram-core", 128, 4, 4, 128, 8], "otpu_actram_sparkle", act))
        tm = {f"{name}{i}": {"max_fanout": 16} for i in range(8) for name in ["pwv", "pwa", "pwd"]}
        tm.update({f"rot{p*4+l}": keep for p in [1, 3] for l in range(4)})
        results.append(inspect("tmem", ["tmem-core", 64, 4, 4, 3, 2, 5, 7, 0, 10], "otpu_tmem_sparkle", tm))
        tree = {f"pdd{k}_2": endpoint for k in range(8)}
        tree["ln0.result_copy"] = keep
        results.append(inspect("vtree", ["vtree-core", 8, 4], "otpu_vtree_sparkle", tree))
        memories = {f"cmd_mem{u}": {"ram_style": "distributed"} for u in range(5)}
        results.append(inspect("seq", ["seq", 1024, 128, 2, 16], "otpu_seq_sparkle", {}, memories))
        scale = {}
        for i in range(3):
            scale.update({f"two{i}_2": endpoint, f"yd{i}_7": endpoint, f"k{i}_10": endpoint})
        scale.update({"flags_32": endpoint, "scale_32": endpoint, "final_flags_2": endpoint, "tag_36": endpoint})
        for name in ["inv_mul", "scale_mul", *[f"{unit}{i}" for i in range(3) for unit in ["t_mul", "t_add", "y_mul"]]]:
            scale[f"{name}.pad0"] = endpoint
        results.append(inspect("qscale", ["qscale-core", 3, 5, 1], "otpu_qscale_sparkle", scale))
        results.append(inspect("qwrite", ["qwrite-core", 8], "otpu_qwrite_sparkle",
                               {"metadata3": endpoint, "scale3": endpoint}))
        read = {"metadata_4": endpoint, "address_5": endpoint}
        read.update({f"column{l}_1": endpoint for l in range(8)})
        results.append(inspect("qread", ["qread-core", 8], "otpu_qread_sparkle", read))
        combined = {f"reader.{name}": attrs for name, attrs in read.items()}
        combined.update({"writer.metadata3": endpoint, "writer.scale3": endpoint})
        for i in range(3):
            combined.update({f"scaler.two{i}_1": endpoint, f"scaler.yd{i}_5": endpoint, f"scaler.k{i}_7": endpoint})
        combined.update({f"scaler.{name}": endpoint for name in ["flags_23", "scale_23", "final_flags_1", "tag_26"]})
        results.append(inspect("quant", ["quant-core", 96, 8], "otpu_quant_sparkle", combined))
        dma = {name: {"max_fanout": 64} for name in ["pe", "gh", "ds_wr", "pp"]}
        dma.update({f"{name}{l}": keep for name in ["ow_a", "gb_eq"] for l in range(8)})
        dma.update({f"{name}{p}_{l}": keep for name in ["gb_we", "gb_wa"] for p in range(4) for l in range(8)})
        dmamem = {"lb": {"ram_style": "block"}, "lm": {"ram_style": "distributed"}}
        dmamem.update({f"ob{l}": {"ram_style": "distributed"} for l in range(8)})
        dmamem.update({f"gb{p}_{l}": {"ram_style": "distributed"} for p in range(4) for l in range(8)})
        results.append(inspect("dma", ["dma-core", 128, 8, 64, 1], "otpu_dma_sparkle", dma, dmamem))
        composite = {"mr_2": endpoint}
        composite.update({f"{name}{s}_{last}": endpoint for s in range(3)
                          for name, last in [("cp", 5), ("md", 6)]})
        composite.update({f"kd{l}_{s}_6": endpoint for l in range(8) for s in range(3)})
        results.append(inspect("se_composite_external", ["se-comp-core", 8, 64, 3, 2, 1],
                               "otpu_se_comp_sparkle", dict(composite)))
        composite.update({f"cd{l}_{s}_1": endpoint for l in range(8) for s in range(3)})
        results.append(inspect("se_composite_internal", ["se-comp-core", 8, 64, 3, 2, 0],
                               "otpu_se_comp_sparkle", composite))
        equivalent = check_actram_tokens() + check_se_composite_tokens() + check_conversion_tokens("se-helpers", "se_helpers") + check_se_microcode_tokens() + check_dma_tokens() + check_quant_tokens() + check_quant_datapath_tokens("qread") + check_quant_datapath_tokens("qwrite") + check_proven_tokens() + check_seq_tokens() + check_conversion_tokens() + check_qscale_tokens()
        summary.write_text(json.dumps({"status": "passed", "attributes": results,
            "functional_equivalence": equivalent,
            "input_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [ROOT / "OpenTPU/Backend.lean", ROOT / "OpenTPU/Physical.lean",
                          ROOT / "OpenTPU/Generate.lean", ROOT / "OpenTPU/Dma.lean", ROOT / "OpenTPU/DmaABI.lean", ROOT / "OpenTPU/QuantScale.lean",
                          ROOT / "OpenTPU/QuantRead.lean", ROOT / "OpenTPU/QuantWrite.lean", ROOT / "OpenTPU/Quant.lean", ROOT / "tools/check_sparkle_physical.py",
                          ROOT / "OpenTPU/SeComposite.lean", ROOT / "OpenTPU/SeCompositeABI.lean",
                          ROOT / "tools/sparkle_provenance.py"]},
            "scope": "attribute preservation and functional token equality; no placement/timing check",
            "yosys": subprocess.check_output(["yosys", "-V"], text=True).strip()}, indent=2)+"\n")
    except BaseException as error:
        summary.write_text(json.dumps({"status": "failed", "error": str(error)})+"\n")
        raise


if __name__ == "__main__":
    main()
