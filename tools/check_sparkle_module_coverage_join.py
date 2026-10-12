"""Join module-definition applicability; elaborated hierarchy/signoff stay separate.

This combines authenticated qualification records for the exact three assemblies.
It does not replace their assumptions with an unconditional behavioral theorem.
"""
import argparse
import copy
import json
import sys
from pathlib import Path
from check_sparkle_fpga_top_complete import bounded_context, require
from check_sparkle_physical_proof_binding import read, remember, authenticate
from sparkle_provenance import ROOT, archive, sha256

CASES = {'gen1', 'gen2', 'bundle'}
ABI = {'otpu_dma_split', 'otpu_mem_ch'}
SHELL = {'otpu_fpga_top_ld', 'otpu_fpga_top_ld_sparkle'}


def join(inventory, abi, shell):
    require(inventory['status'] == 'inventory_complete_scope_incomplete', 'Inventory incomplete')
    require(set(inventory['cases']) == CASES, 'Inventory case set differs')
    require(abi['status'] == 'synthesis_abi_identity_passed', 'ABI proof incomplete')
    require(shell['status'] == 'shell_applicability_passed', 'Shell proof incomplete')
    result = copy.deepcopy(inventory['cases'])
    seen = set()
    for role, record, expected_count in [('abi', abi, 6), ('shell', shell, 3)]:
        require(len(record['cases']) == expected_count, 'Incomplete ' + role + ' case count')
        for entry in record['cases']:
            case = entry['name']; require(case in CASES, 'Unexpected assembly case')
            target = result[case]
            require(entry['assembly'] == target['assembly'] and
                    entry['assembly_sha256'] == target['assembly_sha256'], 'Assembly identity differs')
            modules = entry['matched_module_sha256']
            if role == 'abi':
                require(entry['wrapper'] in ABI and set(modules) == {entry['wrapper']}, 'ABI module scope differs')
                key = (role, case, entry['wrapper'])
            else:
                require(set(modules) == SHELL, 'Shell module scope differs')
                require(entry['configuration'] == target['configuration']['fpga'], 'Shell configuration differs')
                key = (role, case)
            require(key not in seen, 'Duplicate applicability case'); seen.add(key)
            for name, digest in modules.items():
                require(name in target['modules'] and target['modules'][name]['sha256'] == digest,
                        'Module definition differs: ' + name)
                target['modules'][name]['coverage'].append(role + '_applicability')
    for case, target in result.items():
        missing = sorted(n for n, m in target['modules'].items() if not m['coverage'])
        require(not missing, 'Uncovered module definitions: ' + repr(missing))
        target['uncovered_modules'] = missing
        target['covered_module_count'] = len(target['modules'])
        require(target['module_count'] == len(target['modules']), 'Module count inconsistent')
        for instance in target['instances']:
            instance['coverage'] = target['modules'].get(instance['type'], {}).get('coverage', [])
        target['uncovered_instance_occurrences'] = [i for i in target['instances'] if not i['coverage']]
        # Syntactic external occurrences remain visible; they are not coverage failures
        # that can be silently removed from the design's scope.
    return result


def run(inventory_path, abi_path, shell_path, output):
    bounded_context(); require(not output.exists(), 'Preserve previous evidence')
    output.mkdir(parents=True); summary = output / 'summary.json'; observed = {}
    report = {'status': 'incomplete', 'scope': __doc__, 'whole_closure': False}
    def save(): summary.write_text(json.dumps(report, indent=2) + '\n')
    save()
    try:
        for module in list(sys.modules.values()):
            p = getattr(module, '__file__', None)
            if p and Path(p).resolve().parent == ROOT / 'tools': remember(Path(p), observed)
        remember(Path(__file__), observed)
        records = []
        for path in (inventory_path, abi_path, shell_path):
            remember(path, observed); record = read(path)
            authenticate(record['input_sha256'], observed); records.append(record)
        cases = join(*records)
        for case in cases.values():
            remember(Path(case['assembly']), observed, case['assembly_sha256'])
        report.update(cases=cases, remaining_obligations=[
            'Independent elaborated instance/parameter applicability and reachability',
            'Inherited component assumptions and reference-undefined behavior scopes',
            'External vendor primitive/IP contracts and actual implementation',
            'CDC endpoint/constraint qualification, placed timing/DRC and hardware signoff',
            'Broader runtime/model regressions'])
        require(all(sha256(p) == h for p, h in observed.items()), 'Join inputs changed')
        for p in observed: archive(p)
        report.update(status='module_definitions_bound_scope_incomplete', input_sha256=observed)
        save(); archive(summary)
    except BaseException as error:
        report.update(status='incomplete', error=repr(error), input_sha256=observed)
        save(); archive(summary); raise
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('inventory', 'abi', 'shell', 'output'): parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    print(run(args.inventory.resolve(), args.abi.resolve(), args.shell.resolve(), args.output.resolve())['status'])
