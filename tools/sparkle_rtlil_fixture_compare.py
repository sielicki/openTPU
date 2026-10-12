"""Independent SMALL-fixture import comparator; never load production JSON here.

Compare two Yosys write_json outputs after read_json versus read_rtlil. Numeric
signal IDs may change bijectively; only explicitly declared introduced aliases
may be added. This helper intentionally caps each loaded fixture at 2 MiB.
Signed constant flags (not fully represented by JSON) need the additional
write_rtlil declaration comparison below. No proof or large-netlist claim.
"""
import json
from pathlib import Path
import re

LIMIT = 2 * 1024 * 1024


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load_small(path):
    path = Path(path)
    require(path.stat().st_size <= LIMIT, 'fixture exceeds small comparator limit')
    with path.open() as stream:
        return json.load(stream)


def compare_imports(reference, candidate, introduced_aliases):
    require(set(reference) == set(candidate), 'top-level inventory differs')
    require(reference.keys() <= {'creator', 'modules'}, 'unsupported top-level schema')
    require(set(reference['modules']) == set(candidate['modules']), 'module inventory differs')
    require(set(introduced_aliases) == set(reference['modules']), 'helper module inventory differs')
    all_helpers = [name for names in introduced_aliases.values() for name in names]
    require(len(all_helpers) == len(set(all_helpers)), 'gold/gate helper names overlap')
    stats = {}
    for module in sorted(reference['modules']):
        left, right = reference['modules'][module], candidate['modules'][module]
        require(list(left['ports']) == list(right['ports']), 'port ID/order differs')
        forward, backward = {}, {}
        helpers = introduced_aliases[module]
        require(len(helpers) == len(set(helpers)), 'duplicate helper alias')
        require(set(right['netnames']) - set(left['netnames']) == set(helpers), 'unexpected introduced alias inventory')
        for name in helpers:
            require(name.startswith('$'), 'helper must be private')
            require(name not in left['netnames'] and name not in right.get('ports', {}), 'helper aliases retained object')
            helper = right['netnames'][name]
            require(helper.get('hide_name') == 1 and not helper.get('attributes'), 'semantic/public helper alias')
            require(set(helper) <= {'hide_name', 'bits', 'attributes', 'offset', 'upto', 'signed'}, 'unknown helper fields')
            require(not any(helper.get(k, 0) for k in ['offset', 'upto', 'signed']), 'helper metadata differs')
            require(all(type(b) is int for b in helper['bits']), 'helper contains constant')
            require(len(helper['bits']) == len(set(helper['bits'])), 'helper merges distinct bits')

        def walk(a, b, path=()):
            signals = ((len(path) == 3 and path[0] in ['ports', 'netnames'] and path[2] == 'bits') or
                       (len(path) == 4 and path[0] == 'cells' and path[2] == 'connections'))
            if signals:
                require(isinstance(a, list) and isinstance(b, list) and len(a) == len(b), f'signal width differs: {path}')
                for x, y in zip(a, b):
                    if type(x) is int:
                        require(type(y) is int, f'wire/constant changed: {path}')
                        require(forward.get(x, y) == y and backward.get(y, x) == x, f'bit alias graph differs: {path}')
                        forward[x], backward[y] = y, x
                    else:
                        require(type(x) is str and x in '01xz' and len(x) == 1 and x == y,
                                f'constant differs: {path}')
                return
            require(type(a) is type(b), f'value type differs: {path}')
            if isinstance(a, dict):
                keys = set(b) - set(helpers) if path == ('netnames',) else set(b)
                require(set(a) == keys, f'object inventory differs: {path}')
                for key in sorted(a): walk(a[key], b[key], path + (key,))
            elif isinstance(a, list):
                require(len(a) == len(b), f'list width differs: {path}')
                for index, (x, y) in enumerate(zip(a, b)): walk(x, y, path + (index,))
            else:
                require(a == b, f'value differs: {path}')
        walk(left, right)
        stats[module] = {'mapped_bits': len(forward), 'retained_aliases': len(left['netnames']),
                         'ports': len(left['ports']), 'cells': len(left['cells'])}
    return stats


def declaration_values(path):
    """Observe signed/string constant syntax independently of JSON's lossy flags.

Capture attributes attached to named modules/wires/cells/memories, module
parameters, and cell parameters from Yosys's own canonical write_rtlil output.
Never parse or normalize constants with converter code.
"""
    path = Path(path)
    require(path.stat().st_size <= LIMIT, 'RTLIL fixture exceeds small limit')
    result, attributes = {}, []
    module = cell = None
    for raw in path.read_text().splitlines():
        text = raw.strip()
        if text.startswith('attribute '):
            attributes.append(text)
        elif text.startswith('module '):
            module = text.split()[-1]
            result[(module, 'module')] = tuple(sorted(attributes)); attributes = []
        elif text.startswith('cell '):
            cell = text.split()[-1]
            result[(module, 'cell', cell)] = tuple(sorted(attributes)); attributes = []
        elif text.startswith(('wire ', 'memory ')):
            name = text.split()[-1]
            result[(module, text.split()[0], name)] = tuple(sorted(attributes)); attributes = []
        elif text.startswith('parameter '):
            match = re.match(r'parameter\s+(?:(?:signed|real|unsized)\s+)*([\\$]\S+)\s*(.*)$', text)
            require(match is not None, 'unrecognized canonical parameter declaration')
            result[(module, 'parameter', cell, match[1])] = text
        elif text == 'end':
            if cell is not None: cell = None
            else: module = None
    require(not attributes, 'unattached canonical attributes')
    return result


def compare_declarations(reference_path, candidate_path, introduced_aliases):
    left, right = declaration_values(reference_path), declaration_values(candidate_path)
    for module, names in introduced_aliases.items():
        mod = module if module.startswith(('\\', '$')) else '\\' + module
        for name in names:
            require(right.pop((mod, 'wire', name), None) == (), 'helper carries canonical attributes')
    require(left == right, 'canonical attribute/parameter declarations differ')
