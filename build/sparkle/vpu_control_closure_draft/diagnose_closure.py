"""Measured premise/crossing inventory to choose the next assumption discharge."""
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
ROOT = next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'build/sparkle/vpu_joint_physical_draft'),
               str(ROOT/'build/sparkle/vpu_control_partition_draft'),
               str(ROOT/'build/sparkle/vpu_joint_observation_draft')]
from diagnose_physical import pinned
from check_sparkle_fpga_top_complete import bounded_context, require
from qualify_sparkle_specialization_binding import read, normalized_hashes
from joint_partition import owner, storage
from observation_coordinates import Original

PINS = {
 'composition': ('vpu-joint-initialized-composition-first', 'cdf0d979476b12b4e37de7ed63538dbd2016d00bb056705e19b40e97760988cc'),
 'original': ('vpu-original-control-inventory-seventh', '1da5439d3020dda781bbb135be7526b5df5bc48cf82916194d9cf59afb4fea9f'),
 'partition': ('vpu-joint-partition-first', '8c0374eaf99c809be8d64bd01ef126ac092f39fc3a825bf7fc75768db0e84a35'),
 'binding': ('vpu-control-initial-binding-second', '704555cc3e0c7c5c526ef1f7de7f3fc52b025d9e48396c9f7e85b215e48cb1c8')}


def main():
    bounded_context(); records = {}; maps = {}
    for key, (folder, digest) in PINS.items():
        path = ROOT/'build/sparkle'/folder/'summary.json'
        records[key] = read(pinned(path, digest)); maps[key] = normalized_hashes(records[key]['input_sha256'])
    def artifact(key, path):
        path = str(Path(path).resolve()); require(path in maps[key], 'Missing exact direct artifact owner '+path)
        return pinned(Path(path), maps[key][path])
    for key in ('original',):
        folder, digest = PINS[key]
        require(maps['composition'].get(str(ROOT/'build/sparkle'/folder/'summary.json')) == digest, 'Composition owner receipt join differs')
    require(records['composition']['conditional_initialized_1159_relation_proven'] is True and
            records['composition']['hc_cut_discharged'] is True and records['composition']['environment_contract_required'] is True,
            'Completed conditional composition absent')
    require(records['partition']['storage_frontier_inventory_complete'] is True and
            records['partition']['counts']['crossings'] == 2455, 'Complete crossing inventory absent')
    require(records['binding']['status'] == 'four_local_initialized_control_contracts_bound_to_production' and
            records['binding']['local_contracts_bound'] is True, 'Completed local production binding absent')
    rtl = str(ROOT/'rtl/vpu/otpu_vpu.sv')
    require(maps['original'].get(rtl) is not None and maps['binding'].get(rtl) == maps['original'][rtl],
            'Binding/original RTL source identity differs')
    folder, digest = PINS['original']
    require(records['partition']['owner_sha256'] == digest and
            maps['partition'].get(str(ROOT/'build/sparkle'/folder/'summary.json')) == digest, 'Crossings/original owner join differs')
    cert = read(artifact('composition', ROOT/'build/sparkle'/PINS['composition'][0]/'composition-certificate.json'))
    original = records['original']; candidates = read(artifact('original', original['control_candidates']))
    db = sqlite3.connect(artifact('original', original['owner_database']).as_uri()+'?mode=ro&immutable=1', uri=True)
    db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA cache_size=-8192')
    try:
        selected, sq, words = storage(db, candidates); require(len(sq) == 679 and words == {'cq': {0,1}}, 'Selected state changed')
        graph = Original(db); control_q = defaultdict(list)
        for field in candidates['fields']:
            if field['classification'] != 'physical_DFF_Q': continue
            for i, bit in enumerate(field['original_bits']):
                control_q[bit].append({'unit': field['unit'], 'field': field['field'], 'position': i})
        # Full bound component interfaces identify provider CANDIDATES; this
        # diagnostic does not turn textual edge matching into a semantic proof.
        cases = records['binding']['cases']; require([c['name'] for c in cases] == ['gen1','gen2','bundle'], 'Production case inventory differs')
        signatures = []; providers = {}
        for case in cases:
            ports = {}; edges = {}
            for component in case['components']:
                unit = component['unit']; wires = dict(component['edge'])
                require(len(wires) == len(component['edge']), 'Duplicate component edge pin')
                for name, direction, width in component['all_ports']:
                    if direction != 'output': continue
                    expr = wires[name]; require(expr not in ports, 'Duplicate native provider')
                    ports[expr] = {'unit': unit, 'port': name, 'width': width}
                edges[unit] = component['edge']
            signatures.append({'providers': ports, 'edges': edges}); providers = ports
        require(signatures[0] == signatures[1] == signatures[2], 'Reached production wiring differs')
        def describe(bit):
            if type(bit) is str: return {'kind': 'literal', 'value': bit}
            drivers = db.execute('SELECT owner,pin FROM drivers WHERE module="otpu_vpu" AND bit=?', (bit,)).fetchall()
            require(len(drivers) <= 1, 'Ambiguous actual driver')
            aliases = [{'name': n, 'position': i} for n, i in db.execute(
                'SELECT name,position FROM aliases WHERE module="otpu_vpu" AND bit=? ORDER BY name,position', (bit,))]
            result = {'bit': bit, 'aliases': aliases, 'control_coordinates': control_q.get(bit, [])}
            if bit in sq: result['kind'] = 'selected_joint_state'
            elif bit in control_q: result['kind'] = 'other_control_state'
            elif not drivers: result['kind'] = 'undriven'
            elif drivers[0][0].startswith('port:'): result['kind'] = 'top_input'
            else:
                cell = owner(db, 'cells', drivers[0][0]); result['driver_type'] = cell['type']
                result['kind'] = 'child_output' if not cell['type'].startswith('$') or cell['type'].startswith('$paramod') else 'memory_output' if cell['type'].startswith('$mem') else 'other_original_state' if cell['type'] == '$dff' else 'combinational_provider'
            result['driver'] = list(drivers[0]) if drivers else None
            return result
        groups = {}; contract_count = 0
        for row in cert['remaining_environment']:
            name = row['field']; g = groups.setdefault(name, {'coordinate_count': 0, 'contract_count': 0,
                'actual_original_kinds': Counter(), 'control_field_counts': Counter(), 'samples': [],
                'provider_candidate': providers.get(name.removeprefix('external_'))})
            detail = describe(row['original_underlying'])
            g['coordinate_count'] += 1; g['contract_count'] += int(row['per_cycle_contract'])
            g['actual_original_kinds'][detail['kind']] += 1
            for coordinate in detail.get('control_coordinates', []):
                g['control_field_counts'][coordinate['unit']+'.'+coordinate['field']] += 1
            if len(g['samples']) < 3: g['samples'].append({**row, 'actual_original': detail})
            contract_count += int(row['per_cycle_contract'])
        head = {graph.canonical(bit) for bit in graph.alias('hc')}; crossing_groups = {}; count = 0
        with artifact('partition', records['partition']['owner_manifest']).open() as stream:
            for line in stream:
                row = json.loads(line)
                if row['record'] != 'crossing': continue
                count += 1; bit = row['bit']; normalized = graph.canonical(bit)
                if normalized in sq: support = 'selected_state_or_buffer_chain'
                elif normalized in head: support = 'current_head_or_buffer_chain'
                else: support = 'additional_observation_required'
                target = row['consumer']; destination = None
                if target.startswith('port:'): kind = 'top_output'
                else:
                    cell = owner(db, 'cells', target); kind = cell['type']
                    if cell['type'] == '$dff' and row['pin'] == 'D':
                        q = cell['connections']['Q'][row['position']]; destination = control_q.get(q, [])
                key = json.dumps([support, kind, sorted({p['unit'] for p in destination or []})])
                g = crossing_groups.setdefault(key, {'support': support, 'consumer_type': kind,
                    'destination_control_units': sorted({p['unit'] for p in destination or []}), 'count': 0, 'samples': []})
                g['count'] += 1
                if len(g['samples']) < 4:
                    g['samples'].append({**row, 'normalized_source': normalized,
                                         'source_aliases': describe(bit)['aliases'], 'destination_fields': destination})
        require(count == 2455, 'Complete outward crossing count differs')
        result = {'status': 'remaining_control_environment_and_crossings_diagnostic_only', 'proof': False,
                  'receipt_pins': PINS, 'environment_coordinates': len(cert['remaining_environment']),
                  'per_cycle_contract_coordinates': contract_count, 'fields': groups,
                  'all_crossings': count, 'crossing_groups': list(crossing_groups.values()),
                  'other3072_original_state_and_layout_bridge_proven': False,
                  'native_provider_candidates_only': True, 'no_internal_premise_discharged_by_this_diagnostic': True}
        print(json.dumps(result, indent=2), flush=True)
    finally: db.close()


if __name__ == '__main__': main()
