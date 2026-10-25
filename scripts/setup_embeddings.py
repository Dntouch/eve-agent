#!/usr/bin/env python3
"""Fetch pinned E5 ONNX assets once; inference itself is fully offline."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.request

REPOSITORY = 'intfloat/multilingual-e5-small'
REVISION = '614241f622f53c4eeff9890bdc4f31cfecc418b3'
FILES = {'model.onnx': 'onnx/model.onnx', 'tokenizer.json': 'onnx/tokenizer.json'}
SHA256 = {
    'model.onnx': 'ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665',
    'tokenizer.json': '0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39',
}


def file_digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'data/models/multilingual-e5-small')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest = {'repository': REPOSITORY, 'revision': REVISION, 'sha256': {}}
    for local, remote in FILES.items():
        path = args.output / local
        if path.is_file() and file_digest(path) == SHA256[local]:
            manifest['sha256'][local] = SHA256[local]
            print(local, 'bereits geprüft', flush=True)
            continue
        temporary = path.with_suffix(path.suffix + '.part')
        digest = hashlib.sha256()
        print('Lade', remote, flush=True)
        try:
            with urllib.request.urlopen(f'https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{remote}', timeout=60) as response, temporary.open('wb') as out:
                for block in iter(lambda: response.read(1024 * 1024), b''):
                    out.write(block)
                    digest.update(block)
            if digest.hexdigest() != SHA256[local]:
                raise ValueError('Embedding-Datei hat eine unerwartete Prüfsumme: ' + local)
            os.chmod(temporary, 0o600)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        manifest['sha256'][local] = digest.hexdigest()
        print(local, path.stat().st_size, 'Bytes', flush=True)
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Lokale CPU-Embeddings vorbereitet:', args.output)


if __name__ == '__main__':
    main()
