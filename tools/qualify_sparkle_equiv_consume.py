"""Small-fixture qualification of experimental gold-consuming equiv_make.

Compare complete prepared graphs and equivalence-cell multisets before solving.
Only auto-generated object names and numeric signal IDs may vary. All original
named objects, ports/order, attributes, parameters and connectivity remain exact.
Positive and negative proofs use unchanged stock equiv_simple/equiv_status.
No production netlist is accepted by this fixture-only runner.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

from build_sparkle_equiv_consume import sha, require
from sparkle_rtlil_fixture_compare import declaration_values, load_small


def fixture(kind='logic', mutation=False):
    modules = []
    for side in ['gold', 'gate']:
        bad = side == 'gate' and mutation
        attrs = f'attribute \\from_{side} 1\nattribute \\overlap "{side}"\n'
        body = r'''
  attribute \keep 1
  wire width 4 offset 3 upto signed input 7 \a
  wire width 4 input 20 \b
  wire input 21 \s
  wire width 4 output 30 \y
  wire width 4 \tmp
  wire width 4 \alias
  wire width 3 \floating
  wire width 0 \empty
  connect \alias { \a [1:0] \a [3:2] }
  connect \floating [0] \a [0]
'''
        if kind == 'logic':
            body += r'''
  attribute \keep 1
  attribute \tag "cell string"
  cell $xor \shared
    parameter \A_SIGNED 0
    parameter \B_SIGNED 0
    parameter \A_WIDTH 4
    parameter \B_WIDTH 4
    parameter \Y_WIDTH 4
    connect \A \alias
    connect \B @B@
    connect \Y \tmp
  end
  cell $mux $private_mux
    parameter \WIDTH 4
    connect \A \tmp
    connect \B \a
    connect \S \s
    connect \Y \y
  end
'''.replace('@B@', '\\a' if bad else '\\b')
        elif kind == 'aliases':
            body += '  connect \\tmp { \\alias [2:0] 1\'0 }\n'
            body += '  connect \\y { \\tmp [3:1] ' + ("1'1" if bad else "1'0") + ' }\n'
        elif kind == 'input_feedback':
            body += '  connect \\b \\a\n'
            body += r'''
  cell $not \shared
    parameter \A_SIGNED 0
    parameter \A_WIDTH 4
    parameter \Y_WIDTH 4
    connect \A \alias
    connect \Y \tmp
  end
  connect \y @OUT@
'''.replace('@OUT@', '\\a' if bad else '\\tmp')
        elif kind == 'state_transition':
            body += r'''
  wire width 4 input 40 \state
  wire width 4 output 41 \next_state
  cell $add $arithmetic
    parameter \A_SIGNED 0
    parameter \B_SIGNED 0
    parameter \A_WIDTH 4
    parameter \B_WIDTH 4
    parameter \Y_WIDTH 4
    connect \A \state
    connect \B @INC@
    connect \Y \tmp
  end
  cell $mux \hold
    parameter \WIDTH 4
    connect \A \state
    connect \B \tmp
    connect \S \s
    connect \Y \next_state
  end
  connect \y \state
'''.replace('@INC@', "4'0010" if bad else "4'0001")
        else: raise ValueError('Unknown fixed fixture')
        modules.append(attrs + 'module \\' + side + '\n' + body + 'end\n')
    return '\n'.join(modules)


def generated(name):
    return name.startswith('$auto$')


def compare_graphs(stock, consumed):
    require(set(stock['modules']) == set(consumed['modules']) == {'equiv'}, 'Prepared module inventory differs')
    a, b = stock['modules']['equiv'], consumed['modules']['equiv']
    require(set(a) == set(b), 'Module field inventory differs')
    forward, backward = {}, {}
    def bits(left, right):
        require(len(left) == len(right), 'Prepared signal width differs')
        for x, y in zip(left, right):
            if type(x) is int:
                require(type(y) is int and forward.get(x,y) == y and backward.get(y,x) == x, 'Prepared alias/connection graph differs')
                forward[x], backward[y] = y, x
            else: require(type(y) is str and x == y, 'Prepared signal constant differs')
    def exact_meta(left, right, except_keys):
        require({k:v for k,v in left.items() if k not in except_keys} ==
                {k:v for k,v in right.items() if k not in except_keys}, 'Prepared metadata differs')
    exact_meta(a, b, {'ports', 'netnames', 'cells'})
    require(list(a['ports']) == list(b['ports']), 'Prepared port inventory/order differs')
    for name in a['ports']:
        exact_meta(a['ports'][name], b['ports'][name], {'bits'})
        bits(a['ports'][name]['bits'], b['ports'][name]['bits'])
    for section in ['netnames', 'cells']:
        left_names = {n for n in a[section] if not generated(n)}
        right_names = {n for n in b[section] if not generated(n)}
        require(left_names == right_names, 'Named object inventory differs')
        for name in sorted(left_names):
            left, right = a[section][name], b[section][name]
            if section == 'netnames':
                exact_meta(left, right, {'bits'}); bits(left['bits'], right['bits'])
            else:
                exact_meta(left, right, {'connections'})
                require(set(left['connections']) == set(right['connections']), 'Cell pin inventory differs')
                for pin in sorted(left['connections']): bits(left['connections'][pin], right['connections'][pin])
    def normalized(value, section, candidate):
        value = json.loads(json.dumps(value))
        def remap(vector):
            out = []
            for bit in vector:
                if type(bit) is int:
                    require(bit in (backward if candidate else forward), 'Unanchored generated signal in fixture')
                    bit = backward[bit] if candidate else bit
                out.append(bit)
            return out
        if section == 'netnames': value['bits'] = remap(value['bits'])
        else: value['connections'] = {pin: remap(vector) for pin,vector in value['connections'].items()}
        return json.dumps(value, sort_keys=True)
    names = [{}, {}]
    for section in ['netnames', 'cells']:
        groups = []
        for index, module in enumerate([a,b]):
            records = []
            for name, value in module[section].items():
                signature = normalized(value, section, bool(index))
                if generated(name):
                    records.append(signature)
                    names[index][name] = '$normalized_' + section + '_' + hashlib.sha256(signature.encode()).hexdigest()
            groups.append(Counter(records))
        require(groups[0] == groups[1], 'Generated object/obligation multiset differs')
    obligations = Counter(normalized(cell, 'cells', False) for cell in a['cells'].values() if cell['type'] == '$equiv')
    require(sum(obligations.values()) > 0, 'Fixture produced no equivalence obligations')
    return {'ports': len(a['ports']), 'cells': len(a['cells']), 'aliases': len(a['netnames']),
            'equiv_cells': sum(obligations.values()), 'mapped_bits': len(forward)}, names


def compare_canonical(stock_path, consumed_path, names):
    records = []
    for index, path in enumerate([stock_path, consumed_path]):
        result = Counter()
        for key, value in declaration_values(path).items():
            key = tuple(names[index].get(item, item) if type(item) is str else item for item in key)
            result[json.dumps([key, value], sort_keys=True)] += 1
        records.append(result)
    require(records[0] == records[1], 'Canonical declaration flags/attributes differ')


def run_yosys(yosys, plugin, source, command, work, prove=True):
    work.mkdir()
    script = work / 'run.ys'
    lines = [f'read_rtlil {json.dumps(str(source))}', command, 'hierarchy -top equiv',
             f'write_json {json.dumps(str(work / "prepared.json"))}',
             f'write_rtlil {json.dumps(str(work / "prepared.il"))}']
    if prove: lines += ['equiv_simple -seq 1', 'equiv_status -assert']
    script.write_text('\n'.join(lines) + '\n')
    args = [str(yosys), '-Q', '-T', '-m', str(plugin), '-s', str(script)]
    with (work / 'yosys.log').open('w') as log:
        result = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, timeout=30)
    return result.returncode


def qualify(build_dir, work):
    from check_sparkle_fpga_top_complete import bounded_context
    bounded_context()
    build_dir, work = Path(build_dir).resolve(), Path(work).resolve()
    require(not work.exists(), 'Qualification work must be new')
    manifest_path = build_dir / 'build.json'; manifest = json.loads(manifest_path.read_text())
    plugin = build_dir / 'equiv_make_consume.so'
    require(manifest['status'] == 'built_not_qualified' and sha(plugin) == manifest['plugin_sha256'], 'Plugin build authentication failed')
    require(all(sha(path) == digest for path,digest in manifest['input_sha256'].items()), 'Plugin build input changed')
    yosys = next(Path(p) for p in manifest['input_sha256'] if Path(p).name == 'yosys')
    before = {str(p):sha(p) for p in [manifest_path, plugin, Path(__file__).resolve(),
                                     Path(__file__).with_name('sparkle_rtlil_fixture_compare.py')]}
    work.mkdir(); summary = work / 'summary.json'
    summary.write_text(json.dumps({'status':'incomplete','input_sha256':before}) + '\n')
    records = []
    for kind in ['logic', 'aliases', 'input_feedback', 'state_transition']:
        for mutation in [False, True]:
            case = work / (kind + ('-negative' if mutation else '-positive')); case.mkdir()
            source = case / 'source.il'; source.write_text(fixture(kind, mutation))
            exits = []
            for mode in ['stock', 'consume']:
                cmd = ('equiv_make' if mode == 'stock' else 'equiv_make_consume') + ' gold gate equiv'
                exits.append(run_yosys(yosys, plugin, source, cmd, case / mode))
            stats,names = compare_graphs(load_small(case / 'stock/prepared.json'), load_small(case / 'consume/prepared.json'))
            compare_canonical(case / 'stock/prepared.il', case / 'consume/prepared.il', names)
            require(exits == ([1,1] if mutation else [0,0]), 'Positive/negative proof outcomes differ')
            for mode in ['stock','consume']:
                log = (case / mode / 'yosys.log').read_text()
                require(('unproven $equiv cells' in log) if mutation else ('Equivalence successfully proven!' in log), 'Expected solver verdict absent')
            records.append({'fixture':kind,'mutation':mutation,'graph':stats,'exit_codes':exits,
                'input_sha256':sha(source), 'artifacts':{str(p.relative_to(work)):sha(p) for p in case.rglob('*') if p.is_file()}})
    require(all(sha(path) == digest for path,digest in before.items()) and
            all(sha(path) == digest for path,digest in manifest['input_sha256'].items()), 'Qualification input changed')
    result = {'status':'small_fixtures_passed','production_status':'not_run','plugin_sha256':sha(plugin),
              'build_manifest_sha256':sha(manifest_path),'input_sha256':before,'cases':records,
              'scope':__doc__}
    summary.write_text(json.dumps(result,indent=2) + '\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('build',type=Path); parser.add_argument('work',type=Path)
    args=parser.parse_args(); print(json.dumps(qualify(args.build,args.work),indent=2))


if __name__ == '__main__': main()
