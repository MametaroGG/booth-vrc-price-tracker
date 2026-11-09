"""Same-workflow read acquisition entry; no publication or archive download.

Installed workflow must verify this script's SHA before execution. Dependency
hashes are checked before importing any project module. Token never persisted.
"""
import io
import stat
import zipfile
import hashlib
import json
import os
from pathlib import Path
import sys

PINS = {
    'acquire_saved_handoff.py': '1214d8c4b1cfdc1441de395ca81a84c6061deb99e39bde557eb4e7a17350f7ba',
    'verify_saved_handoff.py': 'de5d1929249e92ebc8949448a5f839bb2893c5067b2484c916a7ba38c94fece5',
}


def need(ok, label):
    if not ok:
        raise ValueError(label)


def prepare(code_dir, workflow_path, output, env):
    """No network; validates installation and turns explicit needs into a dict."""
    code_dir = Path(code_dir).resolve(strict=True)
    for name, pin in PINS.items():
        p = code_dir / name
        need(not p.is_symlink() and p.is_file(), 'Invalid installed module')
        need(hashlib.sha256(p.read_bytes()).hexdigest() == pin, 'Installed module mismatch')
    wf = Path(workflow_path)
    need(not wf.is_symlink() and wf.is_file(), 'Missing immutable workflow checkout')
    wf_pin = hashlib.sha256(wf.read_bytes()).hexdigest()
    out = Path(output).absolute()
    need(out.parent.resolve(strict=True) == out.parent and not out.exists() and not out.is_symlink(), 'New resolved output required')
    need(out != code_dir and code_dir not in out.parents and out not in code_dir.parents, 'Code/output overlap')
    needs = {
        'result': env.get('BOOPA_SCRAPE_RESULT'),
        'saved_commit': env.get('BOOPA_SAVED_COMMIT'),
        'artifact_id': env.get('BOOPA_ARTIFACT_ID'),
        'artifact_digest': env.get('BOOPA_ARTIFACT_DIGEST'),
    }
    return code_dir, wf_pin, out, needs


def persist(out, result):
    """Private runner-local evidence only. Signed redirect and token absent."""
    need(set(result['inputs']) == {'context.json', 'artifact.json', 'receipt.zip', 'collection_receipt.json', 'saved-commit.json', 'workflow.yml'}, 'Input closure')
    inputs = dict(result['inputs'])
    wrapper = inputs['receipt.zip']
    need(type(wrapper) is bytes and 0 < len(wrapper) <= 65536, 'Bounded receipt ZIP required')
    with zipfile.ZipFile(io.BytesIO(wrapper)) as archive:
        rows = archive.infolist()
        need(len(rows) == 1 and rows[0].filename == 'saved-collection.json' and not rows[0].is_dir(), 'Exact flat receipt ZIP closure required')
        member = rows[0]
        need(not member.flag_bits & 1 and stat.S_IFMT(member.external_attr >> 16) in (0, stat.S_IFREG) and 0 < member.file_size <= 65536, 'Ordinary bounded unencrypted receipt required')
        saved_raw = archive.read(member)
    evidence = result['selection']['evidence']
    need(set(evidence) == set(inputs) | {'saved-collection.json'}, 'Selection evidence closure')
    inputs['saved-collection.json'] = saved_raw
    for name, raw in inputs.items():
        need(type(raw) is bytes and type(evidence[name]) is dict and set(evidence[name]) == {'bytes', 'sha256'}, 'Exact selection evidence required')
        need(type(evidence[name]['bytes']) is int and len(raw) == evidence[name]['bytes'] and hashlib.sha256(raw).hexdigest() == evidence[name]['sha256'], 'Selection evidence bytes differ')
    need(hashlib.sha256(saved_raw).hexdigest() == result['selection']['saved_collection_sha256'], 'Saved receipt commitment differs')
    out.mkdir(mode=0o700)
    for name, raw in inputs.items():
        need(type(raw) is bytes, 'Expected byte evidence')
        with (out / name).open('xb') as f:
            f.write(raw)
    for name, value in [('SELECTION.json', result['selection']), ('ACQUISITION.json', result['acquisition'])]:
        with (out / name).open('x') as f:
            json.dump(value, f, sort_keys=True, indent=2)
            f.write('\n')
    # Written last; partial output does not have this local completion marker.
    files = {}
    for p in sorted(out.iterdir()):
        raw = p.read_bytes()
        files[p.name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    receipt = {'schema': 'boopa-runner-acquisition-output-r1', 'files': files,
               'publication_performed': False, 'whole_catalog_complete': False}
    with (out / 'COMPLETE.json').open('x') as f:
        json.dump(receipt, f, sort_keys=True, indent=2)
        f.write('\n')
    return receipt


def main():
    need(len(sys.argv) == 4, 'Expected code-dir workflow-file new-output')
    code, pin, out, needs = prepare(*sys.argv[1:], os.environ)
    sys.path.insert(0, str(code))
    import acquire_saved_handoff
    result = acquire_saved_handoff.acquire_current_actions(needs, pin)
    persist(out, result)
    print('Saved handoff acquired and verified; no publication performed.')


if __name__ == '__main__':
    main()
