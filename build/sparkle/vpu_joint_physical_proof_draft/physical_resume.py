"""Pure direct-owner/query binding for immutable successful partition reuse."""
import json
from pathlib import Path
from physical_slices import require


def requalify(record, owner_map, resolve, raw_sha, audit_sha, identity, root, binary, query, terminal, graph):
    require(record['identity'] == identity and record['raw_sha256'] == raw_sha and
            record['projection_sha256'] == audit_sha, 'Resume domain/manifest/graph identity differs')
    require(record['returncode'] == 0 and record['negative'] is False and record['cwd'] == str(root),
            'Only exact successful positive queries can be resumed')
    require(set(record['artifacts']) == {'raw', 'projection', 'graph', 'script', 'log', 'command', 'result'},
            'Incomplete reusable query artifacts')
    paths = {}
    for name, a in record['artifacts'].items():
        require(a['query_path'] == record['query_paths'][name], 'Query/artifact path binding differs')
        stored = str(Path(a['stored_path']).resolve())
        require(owner_map.get(stored) == a['sha256'], 'Artifact not directly owned by resume receipt')
        paths[name] = resolve(stored, a['sha256'])
    require(record['artifacts']['raw']['sha256'] == raw_sha and
            record['artifacts']['projection']['sha256'] == audit_sha, 'Actual prior raw/projection bytes differ')
    expected = query(Path(record['query_paths']['graph']), record['kind'], Path(record['model_target']))
    require(paths['script'].read_text() == expected, 'Exact prior query differs')
    require(json.loads(paths['command'].read_text()) ==
            {'argv': [str(binary), '-Q', '-T', '-s', record['query_paths']['script']],
             'cwd': str(root), 'timeout': 120}, 'Prior command identity differs')
    require(json.loads(paths['result'].read_text()) == {'returncode': 0}, 'Prior terminal return code differs')
    terminal(0, paths['log'].read_text(), record['kind'], False, None)
    from physical_graph import verify_sigmap
    verify_sigmap(graph, json.loads(paths['graph'].read_text()))
    return paths
