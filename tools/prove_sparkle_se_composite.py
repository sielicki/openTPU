"""Transition and arithmetic-composition checks for the composite engine.

EXT=1 exposes the actual stage results as unrestricted inputs. All control,
metadata, operand outputs, range-reduction logic and retained state are concrete.
EXT=0 checks every arithmetic interface and authenticates the embedded pipelines
against their separate induction proof, under a matched initial-state relation.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path
from prove_sparkle_seq_logic import ROOT, hashes
from prove_sparkle_qscale import yosys
from sparkle_transition import expose_steps, step_miter
from sparkle_provenance import verify
from check_sparkle_physical import module_tokens

WORK = ROOT / 'build/sparkle/formal_se_composite'
CONFIGS = [(1,16,1,2), (4,24,2,1), (8,64,3,2), (2,8,4,7)]


def delay_name(prefix, index, cycles):
    return prefix + ('.g_regs.qr' if index == cycles-1 else f'.g_regs.r[{index}]')


def reference_state(name):
    if m := re.fullmatch(r'uco(\d+)', name):
        return f'uco[{m[1]}]'
    if m := re.fullmatch(r'lp_st(\d+)', name):
        return f'lp_st[{m[1]}]'
    if m := re.fullmatch(r'(cp|md)(\d+)_(\d+)', name):
        prefix = f'g_uc[{m[2]}].u_cp' if m[1] == 'cp' else f'g_sel[{m[2]}].u_md'
        return delay_name(prefix, int(m[3]), 6 if m[1] == 'cp' else 7)
    if m := re.fullmatch(r'mr_(\d+)', name):
        return delay_name('g_sel[0].g_rrm.u_mr', int(m[1]), 3)
    if m := re.fullmatch(r'kd(\d+)_(\d+)_(\d+)', name):
        return delay_name(f'g_lane[{m[1]}].g_st[{m[2]}].u_k', int(m[3]), 7)
    if m := re.fullmatch(r'q([012])_(\d+)', name):
        return f'g_lane[{m[2]}].g_st[0].g_rr.q{m[1]}'
    if m := re.fullmatch(r'r([abc])(\d+)_(\d+)', name):
        return f'g_lane[{m[2]}].g_st[{m[3]}].g_int.r{m[1]}'
    if m := re.fullmatch(r'cd(\d+)_(\d+)_(\d+)', name):
        return delay_name(f'g_lane[{m[1]}].g_st[{m[2]}].g_int.u_ma.u_c', int(m[3]), 2)
    return name


def arithmetic_evidence(source):
    summary = ROOT / 'build/sparkle/formal/summary.json'
    proof = json.loads(summary.read_text())
    if proof['status'] != 'passed':
        raise RuntimeError('run the FP induction proof first')
    entry = proof['fp']
    resolved = verify(entry['input_sha256'])
    for relative in ['rtl/vpu/otpu_fp.sv', 'rtl/vpu/otpu_fpipe.sv']:
        if hashes([ROOT / relative])[relative] != entry['input_sha256'][relative]:
            raise RuntimeError(f'current reference arithmetic differs from proved source: {relative}')
    if 'Induction step proven: SUCCESS!' not in Path(entry['log']).read_text():
        raise RuntimeError('missing FP induction result')
    old = next(p for p in resolved if p.endswith('/float.sv'))
    expected = module_tokens((ROOT / resolved[old]).read_text())
    actual = module_tokens(source.read_text())
    for native, original in [('otpu_se_comp_mul','otpu_fmul_sparkle_2'),
                             ('otpu_se_comp_add','otpu_fadd_sparkle_4')]:
        if actual[native].replace('module'+native+'(', 'module'+original+'(', 1) != expected[original]:
            raise RuntimeError(f'embedded arithmetic differs from proved FP module: {native}')
    return {'verified_proof_inputs': resolved, 'fp_proof': entry}, [summary, *[ROOT/p for p in resolved.values()]]


def prove(cfg, mutation=False, internal=False):
    lanes, width, stages, ahead = cfg
    work = WORK / '_'.join(map(str, cfg))
    if internal:
        work /= 'internal'
    if mutation:
        work /= 'mutation'
    work.mkdir(parents=True, exist_ok=True)
    source = work / 'native.sv'
    generator = work / 'Generate.lean'
    generator.write_text('import OpenTPU.SeComposite\ndef main : IO Unit := do\n'
        f'  let rtl ← IO.ofExcept (OpenTPU.SeComposite.toVerilog ⟨{lanes},{width},{stages},{ahead},{str(not internal).lower()}⟩)\n'
        f'  IO.FS.writeFile "{source}" rtl\n')
    subprocess.run(['lake','env','lean','--run',str(generator)], cwd=ROOT, check=True)
    if mutation:
        code, count = re.subn(r'assign out_v = (.*?);', r'assign out_v = ~(\1);', source.read_text(), count=1)
        if count != 1:
            raise RuntimeError('SE composite mutation target missing')
        source.write_text(code)
    flat = work / 'flat.json'
    hierarchy = work / 'hierarchy.json'
    arithmetic, extra_files = arithmetic_evidence(source) if internal else (None, [])
    extract, _ = yosys(work, 'extract', f'''read_slang --keep-hierarchy --top otpu_se_comp -GLANES={lanes} -GMW={width} -GNS={stages} -GHA={ahead} -GEXT={int(not internal)} rtl/top/otpu_pkg.sv rtl/vpu/otpu_fp.sv rtl/vpu/otpu_fpipe.sv rtl/vpu/otpu_se_comp.sv
rename otpu_se_comp gold
read_slang --keep-hierarchy --top otpu_se_comp_sparkle {source.relative_to(ROOT)}
rename otpu_se_comp_sparkle gate
proc
write_json {hierarchy.relative_to(ROOT)}
''')
    raw = json.loads(hierarchy.read_text())
    if internal:
        found = set()
        for name, module in raw['modules'].items():
            kind = name.split('$')[0]
            if kind not in {'otpu_fmul','otpu_fadd','otpu_se_comp_mul','otpu_se_comp_add'}:
                continue
            if kind in {'otpu_fmul','otpu_fadd'}:
                # Slang elaborates parameters away. A direct-wire padding module
                # establishes the proved base latency (multiply 2, add 4).
                pad = raw['modules'][module['cells']['u_pad']['type']]
                cells = list(pad['cells'].values())
                if (len(cells) != 1 or cells[0]['type'] != '$buf'
                    or cells[0]['connections']['A'] != pad['ports']['d']['bits']
                    or cells[0]['connections']['Y'] != pad['ports']['q']['bits']):
                    raise RuntimeError('unexpected reference arithmetic latency')
            found.add(kind)
            module['cells'] = {}
            module['netnames'] = {}
            module['attributes']['blackbox'] = '1'
        if found != {'otpu_fmul','otpu_fadd','otpu_se_comp_mul','otpu_se_comp_add'}:
            raise RuntimeError(f'missing arithmetic definitions: {found}')
    boxes = work / 'boxes.json'
    boxes.write_text(json.dumps(raw))
    flatten, _ = yosys(work, 'flatten', f'''read_json {boxes.relative_to(ROOT)}
flatten -noscopeinfo gold gate
memory_map
opt_expr
opt_clean
write_json {flat.relative_to(ROOT)}
''')
    modules = json.loads(flat.read_text())['modules']
    raw = {'modules': {kind: modules[kind] for kind in ['gold','gate']}}
    gold, gate = raw['modules'].values()
    if internal:
        for l in range(lanes):
            for s in range(stages):
                for unit, suffix, typ in [('mul','u_m','otpu_fmul'),('add','u_a','otpu_fadd')]:
                    shapes = []
                    for kind, module in raw['modules'].items():
                        name = f'g_lane[{l}].g_st[{s}].g_int.u_ma.{suffix}' if kind == 'gold' else f'{unit}{l}_{s}'
                        cell = module['cells'].pop(name)
                        expected = typ if kind == 'gold' else f'otpu_se_comp_{unit}'
                        if cell['type'].split('$')[0] != expected:
                            raise RuntimeError(f'unexpected arithmetic cell: {cell["type"]}')
                        ports = cell['connections']
                        shapes.append({p:len(b) for p,b in ports.items()})
                        if ports['clk'] != module['ports']['clk']['bits']:
                            raise RuntimeError('arithmetic clock mismatch')
                        for port, bits in ports.items():
                            if port == 'clk':
                                continue
                            key = f'pipe_{unit}{l}_{s}_{port}'
                            module['ports'][key] = {'direction':'input' if port == 'y' else 'output', 'bits':bits}
                            module['netnames'][key] = {'hide_name':0,'bits':bits,'attributes':{}}
                    if shapes != [{'clk':1,'en':1,'a':32,'b':32,'y':32}]*2:
                        raise RuntimeError(f'arithmetic interface mismatch: {shapes}')
    for name in ['in_a','in_b','out_d','st_a','st_b','st_c','st_e','st_y']:
        bits = gold['ports'][name]['bits']
        bits = [b for i in reversed(range(len(bits)//32)) for b in bits[32*i:32*(i+1)]]
        gold['ports'][name]['bits'] = bits
        gold['netnames'][name]['bits'] = bits
    gq = {b for cell in gold['cells'].values() if cell['type'] == '$dff' for b in cell['connections']['Q']}
    nq = {b for cell in gate['cells'].values() if cell['type'] == '$dff' for b in cell['connections']['Q']}
    mapping = {}
    covered = set()
    for name, net in gate['netnames'].items():
        nb = net['bits']
        if name.startswith('_') or not set(nb) <= nq or set(nb) & covered:
            continue
        ref = reference_state(name)
        if ref not in gold['netnames']:
            raise RuntimeError(f'no reference state for {name}: {ref}')
        gb = gold['netnames'][ref]['bits']
        if len(gb) != len(nb) or not set(gb) <= gq:
            raise RuntimeError(f'invalid SE composite state pair: {name}')
        gold['netnames'][name] = {'hide_name': 0, 'bits': gb, 'attributes': {}}
        mapping[name] = len(nb)
        covered.update(nb)
    for module in raw['modules'].values():
        module['netnames'] = {n:v for n,v in module['netnames'].items() if not n.startswith('$')}
    transformed = expose_steps(raw, mapping)
    steps = work / 'steps.json'
    steps.write_text(json.dumps(transformed))
    miter = work / 'miter.sv'
    miter.write_text(step_miter(transformed))
    script = work / 'proof.ys'
    commands = ('equiv_make gold gate equiv\nhierarchy -top equiv\nopt -full\n'
        'simplemap t:$logic_and t:$logic_or t:$logic_not t:$and t:$or t:$not\n'
        'opt -full\nequiv_simple -short\nequiv_status -assert\n')
    if mutation:
        commands = f'read_verilog -sv {miter.relative_to(ROOT)}\nprep -top step_miter -flatten\nopt -full\nsat -prove ok 1 -verify\n'
    script.write_text(f'read_json {steps.relative_to(ROOT)}\n' + commands)
    files = [source,generator,hierarchy,boxes,flat,extract,flatten,steps,miter,script,*extra_files,
        ROOT/'tools/prove_sparkle_se_composite.py',ROOT/'tools/check_sparkle_physical.py',ROOT/'tools/sparkle_provenance.py',
        ROOT/'tools/sparkle_transition.py',
        *[ROOT/'OpenTPU'/f'{n}.lean' for n in ['SeComposite','SeMicrocode','SeHelpers','FloatConvert','Circuit','Backend','SeqWindow']],
        *[ROOT/'rtl/vpu'/f'{n}.sv' for n in ['otpu_se_comp','otpu_fp','otpu_fpipe']], ROOT/'rtl/top/otpu_pkg.sv']
    before = hashes(files)
    log = work / 'proof.log'
    with log.open('w') as output:
        result = subprocess.run(['yosys','-Q','-T','-s',str(script)], cwd=ROOT,
            stdout=output, stderr=subprocess.STDOUT, timeout=600)
    if hashes(files) != before:
        raise RuntimeError('SE composite proof inputs changed')
    transcript = log.read_text()
    if mutation:
        if result.returncode == 0 or 'proof did fail' not in transcript:
            raise RuntimeError(f'SE composite mutation not rejected: {log}')
    elif result.returncode or 'Equivalence successfully proven!' not in transcript:
        raise RuntimeError(f'SE composite proof failed: {log}')
    print(f'PASS SE composite {cfg}: ' + ('completion mutation rejected' if mutation else f'{sum(mapping.values())} state bits and all outputs'), flush=True)
    return {'configuration': cfg, 'external': not internal, 'state_bits': sum(mapping.values()),
            'mutation': mutation, 'arithmetic': arithmetic, 'input_sha256': before, 'log': str(log)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--internal', action='store_true', help='check EXT=0 composition and embedded FP proof inputs')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    summary = WORK / ('summary_internal.json' if args.internal else 'summary.json')
    summary.write_text(json.dumps({'status':'running'})+'\n')
    try:
        with (WORK/'build.log').open('w') as output:
            subprocess.run(['lake','build','OpenTPU.SeComposite'], cwd=ROOT,
                stdout=output, stderr=subprocess.STDOUT, check=True)
        proofs = [prove(cfg, internal=args.internal) for cfg in (CONFIGS[:1] if args.first else CONFIGS)]
        mutation = prove(CONFIGS[0], True, args.internal) if args.self_test else None
        summary.write_text(json.dumps({'status':'passed','proofs':proofs,'self_test':mutation,
            'scope':('EXT=0 composition: complete non-FP state; every FP interface checked and embedded modules match the FP induction proof; matched initial-state relation'
                if args.internal else 'EXT=1; all retained state and outputs, unrestricted inputs and stage results')}, indent=2)+'\n')
    except BaseException as error:
        summary.write_text(json.dumps({'status':'failed','error':str(error)})+'\n')
        raise


if __name__ == '__main__':
    main()
