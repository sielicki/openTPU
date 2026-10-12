"""Acquire pinned public Qwen text-test checkpoints, with complete verified receipts.

All network/file work requires sparkle_bounded.
Downloads stream; interrupted stages are preserved. No remote Python is fetched.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

from check_sparkle_fpga_top_complete import bounded_context, require
from sparkle_provenance import ROOT, archive, sha256

# Immutable public API metadata audited independently on 2026-10-11.
MODELS = {
    'qwen3': {
        'id': 'Qwen/Qwen3-0.6B', 'directory': 'Qwen3-0.6B',
        'revision': 'c1899de289a04d12100db370d81485cdf75e47ca',
        'weights': {'model.safetensors': (1503300328, 'f47f71177f32bcd101b7573ec9171e6a57f4f4d31148d38e382306f42996874b')},
        'files': {'config.json', 'generation_config.json', 'model.safetensors',
                  'tokenizer.json', 'tokenizer_config.json', 'merges.txt', 'vocab.json', 'LICENSE', 'README.md'},
        'content_sha256': {
            'config.json': '660db3b73d788119c04535e48cf9be5f55bc3100841a718637ae695b442f27dd',
            'generation_config.json': '2325da0f15bb848e018c5ae071b7943332e9f871d6b60e2ed22ca97d4cb993d2',
            'tokenizer.json': 'aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4'},
        'absent': {'model.safetensors.index.json'},
    },
    'qwen35': {
        'id': 'Qwen/Qwen3.5-0.8B', 'directory': 'Qwen3.5-0.8B',
        'revision': '2fc06364715b967f1860aea9cf38778875588b17',
        'weights': {'model.safetensors-00001-of-00001.safetensors': (1746942600, '04b1c301231dd422b8860db31311ab2721511346a32cb1e079c4c4e5f1fe4696')},
        'files': {'config.json', 'model.safetensors-00001-of-00001.safetensors',
                  'model.safetensors.index.json', 'tokenizer.json', 'tokenizer_config.json',
                  'merges.txt', 'vocab.json', 'chat_template.jinja', 'LICENSE', 'README.md'},
        'content_sha256': {
            'config.json': 'b90b86f35c8e6925ef74ee04d0e758f0a845c83a42089ad82bbaa948de9b4204',
            'model.safetensors.index.json': 'd8a08838a613b025eb7952ed9db11696213e57e76a375661ef5c12f9dd5dcf4e',
            'tokenizer.json': '5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42'},
        'absent': {'generation_config.json'},
    },
}


def read_metadata(path):
    require(path.stat().st_size <= 2 << 20, 'Metadata exceeds 2 MiB')
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate metadata key')
            result[key] = value
        return result
    with path.open() as stream:
        return json.load(stream, object_pairs_hook=unique)


def inventory(spec, api, rows):
    require(api['id'] == spec['id'] and api['sha'] == spec['revision'], 'Pinned revision/model differs')
    require(api['private'] is False and api['gated'] is False and api['disabled'] is False,
            'Checkpoint is not the audited public unrestricted model')
    siblings = {}
    for entry in api['siblings']:
        name = entry['rfilename']
        require(name not in siblings, 'Duplicate API file')
        siblings[name] = entry
    files = {}
    for entry in rows:
        require(entry['type'] in ('file', 'directory'), 'Unexpected tree entry type')
        if entry['type'] != 'file':
            continue
        name = entry['path']
        require('/' not in name and name not in files, 'Unexpected/duplicate top-level tree file')
        files[name] = entry
    require(set(files) == {n for n in siblings if '/' not in n}, 'API/tree top-level inventories differ')
    require(spec['files'] <= files.keys() and not spec['absent'] & files.keys(), 'Required/absent metadata differs')
    require({n for n in files if n.endswith('.safetensors')} == set(spec['weights']), 'Incomplete/extra weight shard inventory')
    for name, entry in files.items():
        other = siblings[name]
        require(entry['size'] == other['size'] and entry['oid'] == other['blobId'], 'API/tree object identity differs')
        require(('lfs' in entry) == ('lfs' in other), 'API/tree LFS classification differs')
        if 'lfs' in entry:
            require(entry['lfs']['oid'] == other['lfs']['sha256'] and
                    entry['lfs']['size'] == other['lfs']['size'] == entry['size'], 'API/tree LFS identity differs')
    for name, (size, digest) in spec['weights'].items():
        require(files[name]['size'] == size and files[name]['lfs']['oid'] == digest, 'Weight differs from independently audited pin')
    return files


def verify_download(path, entry, expected=None):
    size = path.stat().st_size
    require(size == entry['size'], 'Downloaded file size differs: ' + path.name)
    digest = sha256(path)
    if 'lfs' in entry:
        require(digest == entry['lfs']['oid'] and size == entry['lfs']['size'], 'Downloaded LFS object differs')
    else:
        git = hashlib.sha1(f'blob {size}\0'.encode())
        with path.open('rb') as stream:
            while chunk := stream.read(1 << 20):
                git.update(chunk)
        require(git.hexdigest() == entry['oid'], 'Downloaded Git blob differs')
    require(expected is None or digest == expected, 'Downloaded content differs from independently audited pin')
    require(archive(path) == digest, 'Artifact changed during archival')
    return digest


def fetch(curl, url, path, headers=None, metadata=False):
    command = [str(curl), '--fail', '--location', '--silent', '--show-error',
               '--proto', '=https', '--proto-redir', '=https', '--retry', '3',
               '--connect-timeout', '30', '--max-time', '900']
    if headers is not None:
        command += ['--dump-header', str(headers)]
    if metadata:
        command += ['--max-filesize', str(2 << 20)]
    command += ['--output', str(path), url]
    process = subprocess.Popen(command, start_new_session=True)
    try:
        require(process.wait(timeout=1000) == 0, 'Download failed: ' + path.name)
    except BaseException:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        raise


def run(model, output):
    bounded_context()
    spec = MODELS[model]
    work = output.resolve()
    require(not work.exists(), 'Fresh receipt directory required')
    work.mkdir(parents=True)
    target = ROOT / 'models' / spec['directory']
    stage = work / 'download'
    stage.mkdir()
    summary = work / 'summary.json'
    record = {'status': 'incomplete', 'model': spec['id'], 'revision': spec['revision'],
              'target': str(target), 'files': {}, 'input_sha256': {}}
    def save():
        temp = work / 'summary.tmp'
        temp.write_text(json.dumps(record, indent=2) + '\n')
        temp.replace(summary)
    save()
    def interrupted(signum, frame):
        raise RuntimeError('Interrupted by signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    try:
        require(not target.exists() and not target.is_symlink(), 'Checkpoint target already exists')
        curl = shutil.which('curl')
        require(curl is not None, 'curl unavailable')
        curl = Path(curl).resolve()
        inputs = {Path(__file__).resolve(), Path(sys.executable).resolve(), curl}
        inputs.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
                      if getattr(m, '__file__', None) and Path(m.__file__).resolve().parent == ROOT / 'tools')
        record['input_sha256'] = {str(p): archive(p) for p in inputs}
        save()
        api_path, tree_path, headers = work/'remote-api.json', work/'remote-tree.json', work/'tree-headers.txt'
        fetch(curl, f'https://huggingface.co/api/models/{spec["id"]}/revision/{spec["revision"]}?blobs=true', api_path, metadata=True)
        fetch(curl, f'https://huggingface.co/api/models/{spec["id"]}/tree/{spec["revision"]}?recursive=false&limit=1000', tree_path, headers, metadata=True)
        require(headers.stat().st_size <= 65536, 'Oversized tree headers')
        require(not any(line.lower().startswith('link:') for line in headers.read_text().splitlines()), 'Paginated tree requires explicit complete collection')
        entries = inventory(spec, read_metadata(api_path), read_metadata(tree_path))
        record['metadata_sha256'] = {str(p): archive(p) for p in (api_path, tree_path, headers)}
        save()
        # All names are a fixed, reviewed top-level allowlist, not server-supplied paths.
        for name in sorted(spec['files']):
            url = f'https://huggingface.co/{spec["id"]}/resolve/{spec["revision"]}/{name}'
            path = stage/name
            fetch(curl, url, path, metadata=entries[name]['size'] <= (2 << 20))
            digest = verify_download(path, entries[name], spec['content_sha256'].get(name))
            record['files'][name] = {'url': url, 'bytes': path.stat().st_size, 'sha256': digest}
            save()
            print('Verified', name, path.stat().st_size, 'bytes', flush=True)
        index = stage/'model.safetensors.index.json'
        if index.exists():
            require(set(read_metadata(index)['weight_map'].values()) == set(spec['weights']), 'Shard index differs from complete downloaded weight inventory')
        for path, digest in record['input_sha256'].items():
            require(sha256(Path(path)) == digest, 'Fetcher input changed')
        for name, entry in record['files'].items():
            require(sha256(stage/name) == entry['sha256'], 'Verified staging file changed')
        target.parent.mkdir(exist_ok=True)
        require(not target.exists() and not target.is_symlink(), 'Checkpoint target appeared during download')
        stage.rename(target)
        record['status'] = 'downloaded_verified'
    except BaseException as error:
        record.update(status='incomplete', error=repr(error))
        raise
    finally:
        save()
        archive(summary)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=MODELS, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(run(args.model, args.output)['status'])
