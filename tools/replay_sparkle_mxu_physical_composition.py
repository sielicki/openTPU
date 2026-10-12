"""Resume immutable physical-dot contracts with exact post-memory_map folding.

Only opt_expr is added after memory_map: no state optimization, assumptions,
proof-port exclusions or arithmetic abstractions are introduced.
"""
import argparse
import gc
import json
from pathlib import Path
import shutil

import prove_sparkle_mxu_physical_composition as base
from sparkle_provenance import archive, sha256, verify
from audit_sparkle_rtlil_roundtrip import Owners


def state_inventory(path):
    """Stream every owner; retain only state plus its public bit identities."""
    cells, qbits, aliases, clock = {}, set(), {}, None
    with Path(path).open() as stream:
        reader = Owners(stream)
        for root in reader.object():
            if root != 'modules': reader.value(); continue
            for module in reader.object():
                if module != Path(path).stem:
                    reader.value(); continue
                for section in reader.object():
                    if section not in ('cells', 'ports', 'netnames'): reader.value(); continue
                    for name in reader.object():
                        value = reader.value()
                        if section == 'ports' and name == 'clk': clock = value['bits']
                        if section == 'cells' and value['type'] == '$dff':
                            q = value['connections']['Q']
                            base.require(all(type(b) is int for b in q) and len(set(q)) == len(q)
                                         and not qbits.intersection(q), 'Merged/constant or multiply driven state')
                            cells[name] = value; qbits.update(value['connections']['Q'])
                        if section == 'netnames' and not name.startswith('$'):
                            # write_json orders cells before netnames. Fail closed below
                            # if another producer violates this ordering.
                            for index, bit in enumerate(value['bits']):
                                if bit in qbits: aliases.setdefault(bit, set()).add((name, index))
        reader.whitespace()
        base.require(reader.eof and reader.pos == len(reader.buf), 'Trailing state inventory JSON')
    base.require(qbits == aliases.keys(), 'State lacks complete public bit identities')
    result = {}
    for name, cell in cells.items():
        base.require(cell['connections']['CLK'] == clock, 'Unsupported state clock')
        result[name] = {'parameters': cell['parameters'], 'Q': [aliases[b] for b in cell['connections']['Q']]}
    return result


def same_state(before, after):
    if before.keys() != after.keys(): return False
    for name, old in before.items():
        new = after[name]
        if old['parameters'] != new['parameters'] or len(old['Q']) != len(new['Q']): return False
        # Constant-address mux folding adds output aliases to their selected Q.
        # Every preexisting identity must stay on the same DFF bit, while no
        # DFF or bit may be deleted, added, reordered or merged.
        if any(not old_ids <= new_ids for old_ids, new_ids in zip(old['Q'], new['Q'])): return False
    return True
from sparkle_transition import expose_steps, step_miter


def audit(folder):
    folder = Path(folder).resolve()
    out = folder / 'interrupted.json'
    base.require(not out.exists(), 'Preserve original interruption record')
    runner = json.loads((folder / 'Generate.runner.json').read_text())
    inputs = dict(runner['source_sha256'])
    inputs.update(runner['linked_sha256'])
    for path in inputs:
        base.require(sha256(path) == inputs[path], 'Interrupted generation source changed')
    _, leaves = base.authenticate_leaves(16 + (128-1).bit_length())
    base.freeze(inputs, leaves)
    for path in [Path(base.__file__).resolve(), Path(__file__).resolve(),
                 *[p for p in folder.iterdir() if p.is_file()]]:
        inputs[str(path)] = sha256(path)
    for path in inputs: archive(path)
    record = {'status': 'incomplete', 'termination': 'resource_limit_exit137',
              'phase': 'Python transition construction before solver', 'input_sha256': inputs,
              'note': 'Post-termination archive; generated-source hashes are checked against the preexisting compiled runner record.'}
    out.write_text(json.dumps(record, indent=2) + '\n')
    return record


def replay(source, output, cfg, mutation=None):
    base.bounded_context()
    source, output = Path(source).resolve(), Path(output).resolve()
    base.require(not output.exists(), 'Preserve replay evidence'); output.mkdir(parents=True)
    status = {'status': 'incomplete', 'config': list(cfg), 'mutation': mutation}
    summary = output / 'summary.json'
    def save(): summary.write_text(json.dumps(status, indent=2) + '\n')
    save()
    try:
        record_path = source / ('interrupted.json' if (source / 'interrupted.json').exists() else 'summary.json')
        original = json.loads(record_path.read_text())
        observed = {}
        resolved = verify(original['input_sha256'])
        base.freeze(observed, {str(base.ROOT / actual): original['input_sha256'][old] for old, actual in resolved.items()})
        base.freeze(observed, {str(record_path): sha256(record_path), str(Path(__file__).resolve()): sha256(__file__)})
        d, cols, cl = cfg; sw = 16 + (d-1).bit_length()
        leaves, proof_inputs = base.authenticate_leaves(sw); base.freeze(observed, proof_inputs)
        status['dsp_model_sha256'] = sha256(base.dsp_model())
        runner = json.loads((source / 'Generate.runner.json').read_text())
        status['generation_sha256'] = runner['source_sha256']
        for name in ['native.sv', 'reference.sv', 'native-contracts.sv', 'reference-contracts.sv', 'DSP48E1.sv']:
            base.require(str(source / name) in observed, 'Missing immutable contract binding')
            shutil.copyfile(source / name, output / name)
        base.verify_helper_context(output / 'native.sv', output / 'reference.sv', leaves)
        for side in ['gold', 'gate']:
            old_script = (source / (side + '_extract.ys')).read_text()
            base.require(old_script.count('\nmemory_map\nopt_clean\n') == 1, 'Unexpected preserved extraction flow')
            new_script = old_script.replace('\nmemory_map\nopt_clean\n', '\nmemory_map\nopt_expr\nopt_clean\n')
            new_script = new_script.replace(str(source / (side + '.json')), str(output / (side + '.json')))
            script = output / (side + '_extract.ys'); script.write_text(new_script)
            base.call(script, output / (side + '_extract.log'))
            before = state_inventory(source / (side + '.json'))
            after = state_inventory(output / (side + '.json'))
            base.require(same_state(before, after), 'Combinational folding changed retained state identities')
            status.setdefault('pre_post_state_inventory', {})[side] = {
                'dff_cells': len(before), 'state_bits': sum(len(c['Q']) for c in before.values()),
                'identical': True}
        raw = {'modules': {side: json.loads((output / (side + '.json')).read_text())['modules'][side]
                           for side in ['gold', 'gate']}}
        if mutation == 'leaf_input': raw['modules']['gate']['cells']['physical_pe0_0']['connections']['act'][0] = '0'
        cuts = base.cut_leaves(raw, cfg)
        before_q = {side: {b for cell in module['cells'].values() if cell['type'] == '$dff' for b in cell['connections']['Q']}
                    for side, module in raw['modules'].items()}
        states, removed = base.common_state(raw, cfg)
        removed_ids = {side: sorted(before_q[side] - {b for cell in module['cells'].values() if cell['type'] == '$dff'
                       for b in cell['connections']['Q']}) for side, module in raw['modules'].items()}
        base.require(not removed_ids['gate'], 'Unexpected native removed state')
        base.require(set(removed_ids['gold']) <= set(raw['modules']['gold']['netnames']['g_sys.wc']['bits'])
                     and len(removed_ids['gold']) in (0, d*16), 'Unexpected reference removed state')
        if mutation == 'state_data':
            cell = next(c for c in raw['modules']['gate']['cells'].values() if c['type'] == '$dff'
                        and type(c['connections']['D'][0]) is int)
            cell['connections']['D'][0] = '0'
        transformed = expose_steps(raw, states); step_miter(transformed)
        steps = output / 'steps.json'
        with steps.open('w') as stream: json.dump(transformed, stream)
        del raw, transformed; gc.collect()
        script = output / 'proof.ys'
        script.write_text(f'read_json {steps}\nequiv_make gold gate equiv\nhierarchy -top equiv\n'
            'opt -full\nsimplemap t:$mux\nopt -full\nequiv_simple -short\nequiv_status -assert\n')
        base.freeze(observed, {str(p): sha256(p) for p in output.iterdir() if p.is_file() and p != summary})
        for path in observed: archive(path)
        status.update(input_sha256=observed, cuts=cuts, state_bits=sum(states.values()),
            unobserved_register_bits=removed, removed_state_q_ids=removed_ids,
            leaves={k: {n: v for n, v in leaf.items() if not n.endswith('_body')} for k, leaf in leaves.items()})
        save(); base.call(script, output / 'proof.log', negative=bool(mutation))
        base.require(all(sha256(p) == h for p, h in observed.items()), 'Replay input changed')
        base.require(bool(mutation) or 'Equivalence successfully proven!' in (output / 'proof.log').read_text(), 'Complete proof success missing')
        base.freeze(observed, {str(output / 'proof.log'): sha256(output / 'proof.log')})
        status.update(status='mutation_rejected' if mutation else 'passed',
            solver_status='counterexample' if mutation else 'passed', returncode=1 if mutation else 0,
            proof_log_sha256=sha256(output / 'proof.log'))
        save(); return status
    except BaseException as error:
        status['error'] = repr(error); save(); raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path); parser.add_argument('--output', type=Path)
    parser.add_argument('--config', default='128,4,16'); parser.add_argument('--audit', action='store_true')
    parser.add_argument('--mutation', choices=['leaf_input', 'state_data'])
    args = parser.parse_args(); base.bounded_context()
    result = audit(args.source) if args.audit else replay(args.source, args.output, tuple(map(int, args.config.split(','))), args.mutation)
    print(json.dumps({'status': result['status'], 'state_bits': result.get('state_bits')}))
