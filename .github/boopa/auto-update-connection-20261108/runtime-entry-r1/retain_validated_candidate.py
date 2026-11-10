"""Local-only candidate export after the exact existing release validator returns.
No token/environment/network/publication calls. Upload is a separate workflow step.
The export contains only the fixed public namespace and two bounded safe receipts.
"""
import hashlib, importlib.util, json, re, shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parent
CONNECTOR_PIN = 'f66c541a3990dafe8c0cbf927dc3ca88f1e23cb8f8344ac743257a9449cf5dfd'
PATHS_PIN = '3bc58d76e1315e9821184df31b301bb971fecfed70a2ba987701e22699eca081'
MAX_TOTAL_BYTES = 512 * 1024 * 1024


def need(value, message):
    if not value:
        raise ValueError('candidate retention: ' + message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load_verified(name, path, pin):
    need(path.is_file() and not path.is_symlink() and sha(path.read_bytes()) == pin,
         'local module pin differs')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def public_paths():
    path = ROOT / 'PUBLIC-PATHS.json'
    need(path.is_file() and not path.is_symlink() and sha(path.read_bytes()) == PATHS_PIN,
         'public namespace pin differs')
    value = json.loads(path.read_bytes())
    names = value['paths']
    need(value['sourceCommit'] == '382478b22fb0ecf280ff5f98716ee076376d1083'
         and len(names) == len(set(names)) == 723, 'fixed public namespace differs')
    for name in names:
        need(name == '.nojekyll' or all(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', part)
             and part not in ('.', '..') for part in name.split('/')), 'unsafe public path')
    need('snapshot-manifest.json' not in names, 'self-referential public manifest')
    return set(names) | {'snapshot-manifest.json'}


def prepare_export(request, publisher, summary, output):
    """Serialization seam; production run() always invokes real preflight first."""
    output = Path(output)
    need(output.is_absolute() and output.parent.resolve() == output.parent
         and not output.exists() and not output.is_symlink(), 'new resolved export required')
    candidate = Path(request['candidate']); prior = Path(request['prior'])
    for source in (candidate, prior):
        need(source.is_absolute() and source.resolve() == source and source.is_dir()
             and not source.is_symlink(), 'resolved candidate/prior root required')
        need(output != source and output not in source.parents and source not in output.parents,
             'export overlaps source')
    # The existing snapshot reader rejects symlinks/hardlinks, changed bytes,
    # unexpected files and mismatched manifest pins before any export is created.
    site = publisher.snapshot(candidate, request['candidate_pin'])
    old = publisher.snapshot(prior, request['prior_pin'])
    names = public_paths()
    need(set(site) == set(old) == names, 'candidate/prior public namespace differs')
    need(sum(map(len, site.values())) <= MAX_TOTAL_BYTES, 'public export size limit')
    safe_keys = {'schema', 'request_sha256', 'candidate_snapshot_sha256', 'expected_public_parent',
                 'price_source_commit', 'status', 'fresh_guard_acquired', 'publish_token_read',
                 'publication_performed', 'independent_review'}
    need(set(summary) == safe_keys and summary['schema'] == 'boopa-release-preflight-local-r1'
         and summary['status'] == 'existing-publisher-validation-returned', 'preflight summary differs')
    need(summary['candidate_snapshot_sha256'] == request['candidate_pin']
         and summary['expected_public_parent'] == request['expected'], 'preflight identity differs')
    need(all(summary[key] is False for key in ('fresh_guard_acquired', 'publish_token_read', 'publication_performed'))
         and summary['independent_review'] == 'NOT-ACCEPTED-CONTENT-FLAG', 'preflight authority differs')
    for key in ('request_sha256', 'candidate_snapshot_sha256'):
        need(type(summary[key]) is str and re.fullmatch('[0-9a-f]{64}', summary[key]), 'summary digest')
    for key in ('expected_public_parent', 'price_source_commit'):
        need(type(summary[key]) is str and re.fullmatch('[0-9a-f]{40}', summary[key]), 'summary commit')
    verification = {**summary, 'schema': 'boopa-retained-candidate-verification-r1',
                    'publication_accepted': False, 'provider_authenticated': False,
                    'whole_catalog_complete': False, 'price_source_is_latest': False,
                    'daily_price_coverage_accepted': False,
                    'scope': 'Existing release validator returned for these exact candidate bytes; no source review, freshness, publication or coverage acceptance.'}
    payloads = {'candidate/' + name: raw for name, raw in site.items()}
    payloads['verification.json'] = (json.dumps(verification, sort_keys=True, indent=2) + '\n').encode()
    inventory = {'schema': 'boopa-retained-candidate-inventory-r1',
                 'files': {name: {'bytes': len(raw), 'sha256': sha(raw)} for name, raw in sorted(payloads.items())},
                 'candidate_snapshot_sha256': request['candidate_pin'], 'public_files': len(site),
                 'source_raw_included': False, 'credential_evidence_included': False,
                 'publication_performed': False}
    payloads['EXPORT.json'] = (json.dumps(inventory, sort_keys=True, indent=2) + '\n').encode()
    output.mkdir(mode=0o700)
    try:
        for name, raw in payloads.items():
            path = output / name; path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(raw)
        for name, raw in payloads.items():
            need((output / name).read_bytes() == raw, 'export readback differs')
    except Exception:
        shutil.rmtree(output)
        raise
    return {'path': str(output / 'EXPORT.json'), 'sha256': sha(payloads['EXPORT.json'])}


def run(request_ref, publisher_group, output):
    # There is no injected publisher or success shortcut in the production entry.
    connection = load_verified('retention_existing_release_connection', ROOT / 'release_connection.py', CONNECTOR_PIN)
    publisher = connection.load_verified_publisher(Path(publisher_group['directory']), publisher_group['freeze'])
    request = connection.load_request(request_ref['path'], request_ref['sha256'])
    need(request['publisher_freeze'] == publisher_group['freeze'], 'request publisher differs')
    summary = connection.read_only_preflight(request_ref['path'], request_ref['sha256'], publisher)
    result = prepare_export(request, publisher, summary, output)
    print(json.dumps({'release_preflight': 'existing-publisher-validation-returned',
                      'candidate_snapshot_sha256': request['candidate_pin'],
                      'retained_export_sha256': result['sha256'],
                      'publication_performed': False, 'publish_token_read': False,
                      'source_review_accepted': False}, sort_keys=True), flush=True)
    return result
