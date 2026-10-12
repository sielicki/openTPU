"""Fetch the pinned public LFM2 checkpoint for existing real-model RTL tests.

Run through sparkle_bounded.py. Downloads stream to a staging directory; only a
complete size/hash-verified snapshot is installed. Interrupted inputs remain there.
No remote Python code is fetched or executed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from check_sparkle_fpga_top_complete import bounded_context
from sparkle_provenance import ROOT, archive

MODEL = 'LiquidAI/LFM2.5-230M'
REVISION = '40cb2ad3b3044d5a41eee083a6103c8b523afa45'
FILES = {'config.json', 'generation_config.json', 'model.safetensors',
         'tokenizer.json', 'tokenizer_config.json', 'chat_template.jinja', 'LICENSE', 'README.md'}


def fetch(url, destination):
    subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                    '--retry', '3', '--connect-timeout', '30', '--max-time', '900',
                    '--output', str(destination), url], check=True, timeout=1000)


def main():
    bounded_context()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    target = ROOT / 'models/LFM2.5-230M'
    if target.exists():
        raise ValueError('Checkpoint already exists: ' + str(target))
    work = args.output.resolve()
    work.mkdir(parents=True, exist_ok=False)
    stage = work / 'download'
    stage.mkdir()
    summary = work / 'summary.json'
    result = {'status': 'incomplete', 'model': MODEL, 'revision': REVISION,
              'target': str(target), 'files': {}, 'script_sha256': archive(Path(__file__))}
    def save():
        summary.write_text(json.dumps(result, indent=2) + '\n')
    save()
    try:
        tree = work / 'remote-tree.json'
        fetch(f'https://huggingface.co/api/models/{MODEL}/tree/{REVISION}?recursive=true', tree)
        result['remote_tree_sha256'] = archive(tree)
        rows = json.loads(tree.read_text())
        entries = {row['path']: row for row in rows if row['type'] == 'file'}
        if not FILES <= entries.keys() or {p for p in entries if p.endswith('.safetensors')} != {'model.safetensors'}:
            raise ValueError('Pinned checkpoint file inventory differs')
        for name in sorted(FILES):
            entry = entries[name]
            path = stage / name
            url = f'https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}'
            fetch(url, path)
            size = path.stat().st_size
            if size != entry['size']:
                raise ValueError('Downloaded size differs: ' + name)
            digest = archive(path)
            if 'lfs' in entry:
                if digest != entry['lfs']['oid'] or size != entry['lfs']['size']:
                    raise ValueError('Downloaded LFS hash differs: ' + name)
            else:
                git = hashlib.sha1(f'blob {size}\0'.encode())
                with path.open('rb') as stream:
                    while chunk := stream.read(1 << 20):
                        git.update(chunk)
                if git.hexdigest() != entry['oid']:
                    raise ValueError('Downloaded Git object differs: ' + name)
            result['files'][name] = {'url': url, 'bytes': size, 'sha256': digest}
            save()
            print('Verified', name, size, 'bytes', flush=True)
        target.parent.mkdir(exist_ok=True)
        if target.exists():
            raise ValueError('Checkpoint target appeared during download')
        stage.rename(target)
        result['status'] = 'downloaded_verified'
    except BaseException as error:
        result['error'] = str(error)
        raise
    finally:
        save()
        archive(summary)


if __name__ == '__main__':
    main()
