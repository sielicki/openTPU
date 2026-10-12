"""Actual root issue555, reached native outputs, and27 internal premise discharge."""
import argparse
import json
import signal
import sqlite3
import sys
from pathlib import Path
ROOT = next(p for p in Path(__file__).resolve().parents if (p/'tools/sparkle_bounded.py').is_file())
sys.path[:0] = [str(ROOT/'build/sparkle/vpu_joint_cq_memory_draft'),
               str(ROOT/'build/sparkle/vpu_control_comb_draft'),
               str(ROOT/'build/sparkle/vpu_control_initial_binding_draft'),
               str(ROOT/'build/sparkle/vpu_joint_initialized_composition_draft')]
import check_cq
from cq_session import Session
from check_sparkle_fpga_top_complete import bounded_context
from physical_slices import require
from physical_graph import verify_sigmap
from check_geometry import query, terminal, safe
from composition import chain
from qualify_sparkle_specialization_binding import read
from issue_provenance import PINS, COMB, prepare_sources
from issue_bridge import boundary, closure, crossing_histogram, pair, mutate, INTERNAL, OUTPUTS
from issue_applicability import bind_case
from control_comb import extraction
from check_control_applicability import CURRENT, CURRENT_SHA


def negative_undefined(s, graph, audit):
    folder = s.work/'undefined'; folder.mkdir()
    raw, mapped, model = folder/'raw.json', folder/'post-sigmap.json', folder/'definedness-counterexample.json'
    s.write(raw, graph); s.write(folder/'projection.json', audit)
    s.active.update((mapped, model)); s.checkpoint()
    rc, log = s.script('undefined/import', f'read_json {safe(raw)}\nwrite_json {safe(mapped)}\n')
    require(rc == 0 and mapped.is_file() and 'ERROR:' not in log, 'Actual fault import incomplete')
    s.freeze(mapped); s.write(folder/'sigmap-audit.json', verify_sigmap(graph, read(mapped)))
    try: rc, log = s.script('undefined/definedness', query(mapped, 'definedness', model))
    finally:
        if model.is_file(): s.freeze(model)
    example = read(model) if model.is_file() else None
    terminal(rc, log, 'definedness', True, example)
    return {'returncode': rc, 'model': str(model), 'actual_undefined_output_witness': True}


def main(work, resume=None, resume_sha=None):
    bounded_context(); s = None; db = None
    try:
        s = Session(ROOT, work, resume, resume_sha)
        s.report.update(actual_root_issue_555_proven=False, internal_27_premises_discharged=False,
                        public_528_crossings_proven=False, remaining_internal_provider_bits=2,
                        whole_control_proven=False, c_hold_producer_equality_proven=False,
                        additional_3072_state_bridge_proven=False, all_2455_crossings_proven=False)
        for key, (folder, digest) in {**PINS, 'comb': COMB}.items():
            s.record(key, ROOT/'build/sparkle'/folder/'summary.json', digest)
        comp, original, binding, comb = (s.records[k] for k in ('composition','original','binding','comb'))
        require(comp['conditional_initialized_1159_relation_proven'] is True and comp['hc_cut_discharged'] is True,
                'Initialized selected-state composition absent')
        require(binding['local_contracts_bound'] is True and
                binding['status'] == 'four_local_initialized_control_contracts_bound_to_production' and
                comb['local_combinational_proven'] is True, 'Completed local production/source contracts absent')
        op = str(ROOT/'build/sparkle'/PINS['original'][0]/'summary.json')
        require(s.maps['composition'].get(op) == s.maps['partition'].get(op) == PINS['original'][1], 'Exact original owner joins differ')
        require(s.maps['binding'].get(str(CURRENT)) == CURRENT_SHA, 'Current assembly owner join differs')
        assemblies = s.record('assemblies', CURRENT, CURRENT_SHA)
        require(assemblies['status'] == 'composite_diagnostic_current_assemblies_correspondence_validated', 'Current assemblies incomplete')
        jp = ROOT/'build/sparkle'/check_cq.PINS['joint'][0]/'summary.json'
        require(s.maps['composition'].get(str(jp)) == check_cq.PINS['joint'][1], 'Exact joint native state relation absent')
        joint = s.record('joint', jp, check_cq.PINS['joint'][1])
        require(joint['joint_1159_proven'] is True, 'Joint native state theorem incomplete')
        bp = ROOT/'build/sparkle'/PINS['binding'][0]/'summary.json'
        require(s.maps['joint'].get(str(bp)) == PINS['binding'][1], 'Joint/native production binding owner differs')
        physical, implementation = prepare_sources(s, list(sys.modules.values()), ROOT,
                                                    Path(__file__).parent, check_cq.PHYSICAL)
        for p,h in assemblies['runner']['source_sha256'].items(): s.freeze(Path(p), h)
        binaries = [p for p in s.maps['comb'] if p.endswith('/bin/yosys')]
        require(len(binaries) == 1, 'Unique proved solver binary absent')
        s.binary = Path(binaries[0]); binary_sha = s.freeze(s.binary, s.maps['comb'][str(s.binary)])
        # Link the current solver to the concrete model already audited by the
        # completed679/CQ composition. No new source/binary identity is assumed.
        require(physical['proof_identity']['binary_sha256'] == binary_sha and
                physical['proof_identity']['solver_model']['executable_source_link_verified'] is True, 'Solver/model differs')
        rtl = ROOT/'rtl/vpu/otpu_vpu.sv'
        require(s.maps['original'].get(str(rtl)) is not None and
                s.maps['comb'].get(str(rtl)) == s.maps['original'][str(rtl)], 'Actual original source identity differs')
        native_source = s.artifact('comb', ROOT/'build/sparkle'/COMB[0]/'issue/native.sv')
        case_dir = ROOT/'build/sparkle'/COMB[0]/'issue/none'
        require(s.artifact('comb', case_dir/'native.sv').read_text() == native_source.read_text(), 'Compiled native source differs')
        expected = extraction(ROOT/'rtl/top/otpu_pkg.sv', ROOT/'build/sparkle'/COMB[0]/'issue/reference.sv',
                              case_dir/'native.sv', 'issue', case_dir/'raw.json')
        require(s.artifact('comb', case_dir/'extract.ys').read_text() == expected, 'Exact historical native extraction recipe differs')
        require(read(s.artifact('comb', case_dir/'extract-result.json')) == {'returncode': 0} and
                'ERROR:' not in s.artifact('comb', case_dir/'extract.log').read_text(), 'Historical native extraction incomplete')
        actual_cmd = read(s.artifact('comb', case_dir/'extract-command.json'))
        require(actual_cmd == {'argv': [str(s.binary), '-Q', '-T', '-s', str(case_dir/'extract.ys')], 'cwd': str(ROOT)},
                'Historical native extraction invocation differs')
        production = []
        require([c['name'] for c in binding['cases']] == [c['name'] for c in assemblies['cases']] == ['gen1','gen2','bundle'], 'Complete production cases differ')
        for case, current in zip(binding['cases'], assemblies['cases']):
            require(case['assembly'] == current['new_assembly'] and case['assembly_sha256'] == current['new_assembly_sha256'] and
                    s.maps['assemblies'].get(str(Path(case['assembly']).resolve())) == case['assembly_sha256'], 'Exact production assembly identity differs')
            for unit in ('command','sequence'):
                component = next(c for c in case['components'] if c['unit'] == unit)
                require(component['edge'] == [[n,e] for n,d,w,e in joint['actual_edges'][unit]], 'Reached/joint complete child edge differs')
            production.append(bind_case(s.artifact('assemblies', case['assembly']), native_source, case))
        s.write(s.work/'production-applicability.json', production)
        cert = read(s.artifact('composition', ROOT/'build/sparkle'/PINS['composition'][0]/'composition-certificate.json'))
        raw = read(s.artifact('comb', case_dir/'raw.json'))
        require(set(raw['modules']) == {'gold','gate'}, 'Historical native graph module set differs')
        native = raw['modules']['gate']; del raw
        db = sqlite3.connect(s.artifact('original', original['owner_database']).as_uri()+'?mode=ro&immutable=1', uri=True)
        db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA cache_size=-8192')
        bound = boundary(db, native, cert); measured = closure(bound)
        require(all(not v['frontier'] for v in measured.values()), 'Actual issue closure has unbound state/provider')
        crossings = crossing_histogram(s.artifact('partition', s.records['partition']['owner_manifest']), bound)
        manifest = bound['manifest']; parts = [list(range(i,min(i+16,len(manifest)))) for i in range(0,len(manifest),16)]
        manifest_sha = s.write(s.work/'complete-obligations.json', {'observations': manifest, 'partitions': parts,
            'boundary_relation': bound['relation'], 'actual_input_binding': bound['actual_input_binding'],
            'actual_output_binding': bound['actual_output_binding'], 'closure': measured, 'crossings': crossings})
        s.report['proof_identity'] = json.loads(json.dumps({'pins': {**PINS, 'comb': COMB, 'assemblies': [str(CURRENT),CURRENT_SHA]},
            'implementation': implementation, 'binary_sha256': binary_sha, 'solver_model': physical['proof_identity']['solver_model'],
            'manifest_sha256': manifest_sha, 'partition_width': 16, 'new_traffic_or_state_assumptions': []}))
        if s.prior is not None: require(s.prior.get('proof_identity') == s.report['proof_identity'], 'Resume complete domain/source identity differs')
        s.checkpoint()
        for i, indices in enumerate(parts):
            observations = [manifest[k] for k in indices]; graph, audit = pair(bound, observations)
            audit['exact_observations'] = observations
            s.prove(f'none/partition-{i:04d}', graph, audit)
            del graph, audit
        for fault in ('flip','undefined'):
            changed, mutation = mutate(native, fault); cb = boundary(db, changed, cert)
            require(cb['relation'] == bound['relation'], 'Actual fault changed boundary')
            target = [r for r in cb['manifest'] if r['kind'] == 'D' and r['field'] == 'ta_en' and r['position'] == 0]
            require(len(target) == 1, 'Fault target missing')
            graph, audit = pair(cb, target); audit['actual_module_mutation'] = mutation
            s.write(s.work/(fault+'-actual-native.json'), {'modules': {'gate': changed}})
            s.report['cases'][fault] = (s.prove('flip/proof', graph, audit, negative=True) if fault == 'flip'
                                       else negative_undefined(s, graph, audit))
            del graph, audit, cb, changed
        removed = []; retained = []
        by_output = {(r['field'],r['position']): r for r in manifest if r['kind'] == 'D'}
        for row in cert['remaining_environment']:
            name = row['field'].removeprefix('external_control_')
            if row['field'].startswith('external_control_') and name in INTERNAL:
                actual = by_output[(name,row['position'])]
                path = chain(bound['original_graph'], actual['original'], row['original_underlying'], bound['original_graph'].producer)
                require('control_'+name in joint['inputs'] and joint['inputs']['control_'+name] == INTERNAL[name], 'Old premise input ABI differs')
                removed.append({'old_premise': row, 'actual_issue_observation': actual, 'normalized_original_buffer_chain': path,
                                'native_provider_expression': 'control_'+name})
            else: retained.append(row)
        require(len(removed) == 27 and {(r['old_premise']['field'],r['old_premise']['position']) for r in removed} ==
                {('external_control_'+n,i) for n,w in INTERNAL.items() for i in range(w)}, 'Exact27 premise removal differs')
        require(sum(r['per_cycle_contract'] for r in retained) == 310, 'Remaining original contract count differs')
        s.write(s.work/'premise-discharge.json', {'removed': removed, 'retained_original_rows': retained,
            'added_actual_datapath_interface': bound['actual_input_binding']['c_hold'],
            'remaining_per_cycle_bits_including_hold': 311, 'remaining_internal_control_bits': 2,
            'remaining_datapath_bits_including_hold': 66, 'top_interface_bits': 243,
            'induction_order': 'current_related_selected_state_and_actual_hold_then_issue_outputs_then_selected_D'})
        db.close(); db = None; s.ev.finish()
        s.report.update(status='actual_root_native_issue555_and27_internal_premises_proven',
                        actual_root_issue_555_proven=True, internal_27_premises_discharged=True,
                        public_528_crossings_proven=True, output_bits=555,
                        actual_observation_pairs=len(manifest), partitions=len(parts), remaining_per_cycle_contract_bits=311)
        s.checkpoint()
    except BaseException as error:
        if s is not None:
            for sig in s.handlers: signal.signal(sig, signal.SIG_IGN)
            s.report.update(actual_root_issue_555_proven=False, internal_27_premises_discharged=False, public_528_crossings_proven=False)
        if db is not None:
            try: db.close()
            except BaseException as e:
                if s is not None: s.report.setdefault('preservation_errors', []).append({'cleanup': repr(e)})
        if s is not None: s.fail(error)
        raise
    finally:
        if s is not None: s.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--work', type=Path, required=True)
    p.add_argument('--resume', type=Path); p.add_argument('--resume-sha256')
    a = p.parse_args(); main(a.work, a.resume, a.resume_sha256)
