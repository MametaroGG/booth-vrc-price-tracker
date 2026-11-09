#!/usr/bin/env python3
"""Offline candidate build. Does not publish, replace prod, deploy, or run collection.
A producer completion manifest binds all frozen inputs.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
BASELINE = '3e05fc01d65d0457cc7dd1ec5fab04c4b879e31b'
STATICS = ('.nojekyll', 'apple-touch-icon.png', 'banner.jpg', 'favicon-192.png', 'favicon.ico',
           'google7556652f03bdf586.html', 'icon-512.png', 'icon-maskable-512.png',
           'manifest.webmanifest', 'ogp-16x9.png', 'site-update.js', 'sw.js',
           'image-search.html', 'image-search-engine.js', 'image-search-faq.js',
           'image-search-i18n.js', 'image-search.css', 'image-search-chrome.css',
           'image-search-page.css', 'image-search-page.js', 'image-drop.js', 'scripts/embed-hero.cjs', 'catalog-cache.js', 'catalog-images.js')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rename_new_directory(source, target):
    # Linux renameat2(RENAME_NOREPLACE) closes the existence-check race. Fail
    # closed on unsupported platforms rather than replacing an unrelated dir.
    import ctypes
    import errno
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    if rename is None:
        raise OSError(errno.ENOTSUP, 'Atomic no-replace rename unavailable')
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))


def load_trusted(name):
    spec = importlib.util.spec_from_file_location(name, HERE / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_statics(source, candidate):
    source=Path(source)
    package=source/'static-manifest.json'
    if package.is_file():
        from static_assets import STATIC_HASHES
        manifest=json.loads(package.read_text())
        if manifest.get('baseline_commit')!=BASELINE or manifest.get('files')!=STATIC_HASHES:
            raise ValueError('Static package inventory/baseline mismatch')
        for name,digest in manifest['files'].items():
            path=source/name
            if path.is_symlink() or source.resolve() not in path.resolve().parents or sha(path)!=digest:
                raise ValueError('Static package integrity failure: '+name)
            content=path.read_bytes()
            if hashlib.sha256(content).hexdigest()!=digest:raise ValueError('Static package changed')
            target=candidate/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
    else:
        for name in STATICS:
            if name in ('catalog-cache.js','catalog-images.js'):
                from static_assets import STATIC_HASHES
                content=(HERE/'pinned-static'/name).read_bytes()
                if hashlib.sha256(content).hexdigest()!=STATIC_HASHES[name]:
                    raise ValueError('Static package integrity failure: '+name)
            else:
                content=subprocess.check_output(['git','-C',str(source),'show',BASELINE+':'+name],timeout=60)
            target=candidate/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)


def freeze_inputs(source, manifest_path, dest):
    source = source.resolve()
    manifest_bytes = manifest_path.read_bytes()
    m = json.loads(manifest_bytes)
    m['_source_manifest_sha256'] = hashlib.sha256(manifest_bytes).hexdigest()
    if m.get('schema') != 1 or m.get('status') != 'complete' or not isinstance(m.get('collection_id'), str) or not m['collection_id']:
        raise ValueError('Producer must supply schema=1, status=complete, and collection_id')
    if not isinstance(m.get('fixture'), bool):
        raise ValueError('Explicit fixture boolean required')
    from datetime import date
    if date.fromisoformat(m['expected_date']).isoformat() != m['expected_date']:
        raise ValueError('Invalid expected_date')
    files = m.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('Nonempty files SHA256 map required')
    actual = set()
    for directory in ('data', 'tracker_meta'):
        folder = source / directory
        if not folder.is_dir() or folder.is_symlink():
            raise ValueError(f'Required input directory: {directory}')
        for p in folder.rglob('*'):
            if p.is_symlink():
                raise ValueError(f'Symlink forbidden: {p}')
            if p.is_file():
                actual.add(p.relative_to(source).as_posix())
    for optional in ('metadata.json', 'charts.json'):
        if (source / optional).exists(): actual.add(optional)
    # Keep full raw-source provenance private; public manifests carry only its digest.
    (dest.parent / 'producer-completion.json').write_bytes(manifest_bytes)
    if actual != set(files):
        raise ValueError('Manifest inventory differs from input inventory')
    if 'charts.json' not in files:
        raise ValueError('Same-snapshot charts.json is required; never silently drop charts')
    for name, digest in files.items():
        rel = PurePosixPath(name)
        if rel.is_absolute() or '..' in rel.parts or str(rel) != name or not (name.endswith('.json') or (rel.name == '.gitkeep' and (source / name).is_file() and (source / name).stat().st_size == 0)):
            raise ValueError(f'Unsafe input path: {name}')
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError(f'Invalid digest: {name}')
        src = source / name
        if source not in src.resolve().parents or src.is_symlink() or sha(src) != digest:
            raise ValueError(f'Input integrity failure: {name}')
        dst = dest / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        if sha(dst) != digest or sha(src) != digest:
            raise ValueError(f'Input changed while freezing: {name}')
    for directory in ('data', 'tracker_meta'): (dest / directory).mkdir(exist_ok=True)
    return m


def build(source, completion, baseline_repo, output, compact=False, relations_bundle=None, relations_approval=None, relation_search_bundle=None, relation_search_approval=None, supplement_bundle=None, supplement_approval=None, daily_coverage_file=None, daily_target_date=None, current_price_projection=None, _projection_clock=None, presentation_proof=None, presentation_sha256=None, verified_completion_sha256=None, retained_exclusions_candidate=None, retained_exclusions_snapshot_sha256=None, quarantine_proof=None, latest_negative_proof=None, run_bindings_path=None, run_bindings_sha256=None):
    import build_full
    import build_prod
    import build_item
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError('Output must be new; existing published trees are never replaced')
    verified = None
    output_parent_fd = None
    candidate_fd = None
    output_capability = None
    lexical_output = output
    if (retained_exclusions_candidate is None) != (retained_exclusions_snapshot_sha256 is None):
        raise ValueError('Retained candidate and external snapshot pin required together')
    if verified_completion_sha256 is None and (quarantine_proof is not None or latest_negative_proof is not None):
        raise ValueError('Saved policy requires verified source profile')
    if (run_bindings_path is None)!=(run_bindings_sha256 is None):
        raise ValueError('Run bindings path and external SHA required together')
    run_bindings = None
    if run_bindings_path is not None:
        if verified_completion_sha256 is None:raise ValueError('Run bindings require verified source')
        from saved_snapshot_policy import RunBindings
        run_bindings=RunBindings(run_bindings_path,run_bindings_sha256)
    retained = None
    quarantine = latest_overlay = None
    if retained_exclusions_candidate is not None:
        if verified_completion_sha256 is None:
            raise ValueError('Retained composition requires the verified source profile')
        from visibility_policy import read_retained_exclusions
        retained = read_retained_exclusions(retained_exclusions_candidate, retained_exclusions_snapshot_sha256)
    if verified_completion_sha256 is not None:
        from verified_source import VerifiedSource, open_directory, exact_read, canonical_absolute
        # Configured source bundles and approvals never receive an output-fd exception.
        for configured_bundle, configured_approval in ((relations_bundle, relations_approval), (relation_search_bundle, relation_search_approval), (supplement_bundle, supplement_approval)):
            if bool(configured_bundle) != bool(configured_approval):
                raise ValueError('Configured bundle and approval required together')
            if configured_bundle is not None:
                source_fd = open_directory(configured_bundle)
                os.close(source_fd)
                approval_path = canonical_absolute(configured_approval)
                approval_fd = open_directory(approval_path.parent)
                try:
                    exact_read(approval_fd, approval_path.name, 128 * 1024 * 1024)
                finally:
                    os.close(approval_fd)
        if Path(completion).absolute() != Path(source).absolute() / 'completion.json':
            raise ValueError('Verified profile requires root completion.json')
        verified = VerifiedSource(source, verified_completion_sha256,run_bindings=run_bindings)
        try:
            if retained is not None and verified.historical_composition is None and verified.saved_snapshot_composition is None:
                raise ValueError('Retained composition requires explicit historical provenance')
            if verified.historical_composition is not None and (retained is None or daily_coverage_file is not None or daily_target_date is not None or current_price_projection is not None):
                raise ValueError('Historical composition requires retention and forbids daily/latest-price claims')
            saved = verified.saved_snapshot_composition
            if saved is not None:
                if retained is None or daily_coverage_file is not None or daily_target_date is not None or current_price_projection is not None or quarantine_proof is None or latest_negative_proof is None:
                    raise ValueError('Saved composition requires floor/proofs and forbids daily/latest-price claims')
                if retained['snapshot_sha256'] != saved['retained_snapshot_sha256']:
                    raise ValueError('Saved floor differs')
                from saved_snapshot_policy import Quarantine, LatestNegativeOverlay
                quarantine = Quarantine(quarantine_proof, saved['quarantine_proof_sha256'], retained,run_bindings=run_bindings)
                latest_overlay = LatestNegativeOverlay(latest_negative_proof, saved['latest_negative_overlay_sha256'], retained,run_bindings=run_bindings)
            elif quarantine_proof is not None or latest_negative_proof is not None:
                raise ValueError('Saved policy proofs require saved composition')
            verified.assert_disjoint(output)
            verified.verify_all()
        except BaseException:
            verified.close()
            raise
    if verified is not None:
        from verified_source import open_directory
        # The caller pre-creates a private output parent. No source-controlled
        # pathname is used for subsequent stage writes, even if ancestors change.
        output_parent_fd = open_directory(output.parent)
        output = Path('/proc') / str(os.getpid()) / 'fd' / str(output_parent_fd) / output.name
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='.' + output.name + '-candidate-', dir=output.parent))
    candidate = run / 'site'
    candidate.mkdir()
    if output_parent_fd is not None:
        from verified_source import VerifiedOutput
        run_fd = os.open(run.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=output_parent_fd)
        try:
            candidate_fd = os.open('site', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=run_fd)
        finally:
            os.close(run_fd)
        output_capability = VerifiedOutput(candidate_fd)
    try:
        if verified is None:
            inputs = run / 'inputs'
            inputs.mkdir()
            manifest = freeze_inputs(source, completion, inputs)
        else:
            inputs = verified.root
            manifest = verified.manifest
            (run / 'producer-completion.json').write_bytes(verified.manifest_bytes)
        daily_coverage, daily_receipt_sha = build_full.read_daily_coverage(daily_coverage_file, run / 'daily-private')
        copy_statics(baseline_repo, candidate)
        visibility_summary = build_full.build(inputs / 'data', inputs / 'tracker_meta', candidate,
                         inputs / 'metadata.json' if ('metadata.json' in verified.hashes if verified else (inputs / 'metadata.json').exists()) else None,
                         daily_coverage=daily_coverage, daily_target_date=daily_target_date, current_price_projection=current_price_projection,
                         tracker_meta_hashes={name: digest for name, digest in manifest['files'].items() if name.startswith('tracker_meta/')},
                         visibility_private_dir=run / 'visibility-private', verified_source=verified, retained_exclusions=retained, quarantine=quarantine, latest_negative_overlay=latest_overlay)
        charts = verified.read_json(inputs / 'charts.json') if verified else json.loads((inputs / 'charts.json').read_text())
        if not isinstance(charts, list): raise ValueError('charts.json must be an array')
        if not charts and not manifest['fixture']:
            raise ValueError('Empty charts allowed only for an explicitly labeled fixture')
        from charts_contract import validate_charts, enrich_bootstrap
        validate_charts(charts, inputs, manifest['fixture'], verified_source=verified)
        from visibility_contract import validate_public_visibility
        chart_hidden=validate_public_visibility(json.loads((candidate/'lists_full.json').read_text())['visibility'])
        chart_visibility={'schema':1,'input_chart_ids':[c['id'] for c in charts],
                          'hidden_chart_ids':[c['id'] for c in charts if c['id'] in chart_hidden],
                          'visible_chart_ids':[c['id'] for c in charts if c['id'] not in chart_hidden],
                          'input_charts_sha256':manifest['files']['charts.json']}
        build_prod.build(candidate, charts, lambda payload: enrich_bootstrap(payload, inputs, manifest['fixture'], verified_source=verified))
        relation_status = 'withdrawn'
        if bool(relations_bundle) != bool(relations_approval):
            raise ValueError('Relations bundle and explicit approval must be supplied together')
        if relations_bundle:
            from preserve_relations import preserve, activate_hook
            relation_status = preserve(relations_bundle, relations_approval, candidate)
            index = candidate / 'index.html'
            index.write_text(activate_hook(index.read_text(), relation_status), encoding='utf-8')
        else:
            index = candidate / 'index.html'
            from preserve_relations import strip_relation_imports
            index.write_text(strip_relation_imports(index.read_text()), encoding='utf-8')
        from preserve_relation_search import configure
        search_status = configure(candidate, relation_search_bundle, relation_search_approval, relation_status)
        from preserve_relation_supplement import configure as configure_supplement
        supplement_status = configure_supplement(candidate, supplement_bundle, supplement_approval, relation_status, verified_output=output_capability)
        subprocess.run(['node', str(candidate / 'scripts/embed-hero.cjs')], check=True, cwd=candidate, timeout=60)
        (candidate / 'item.html').write_text(build_item.build_item((candidate / 'index.html').read_text()), encoding='utf-8')
        if compact:
            load_trusted('build_search_catalog').build(candidate, candidate)
        core = load_trusted('build-search-core').build(candidate, write_report=False)['catalog_core']
        from visibility_overlay import apply_image_visibility
        visibility_overlay = apply_image_visibility(candidate)
        # Display-only guard must run after derived pages, before validation/hashing.
        load_trusted('guard_discount_display').main(candidate)
        if presentation_proof is not None or presentation_sha256 is not None:
            from projection_integration import apply_presentation
            apply_presentation(candidate, presentation_proof, presentation_sha256)
        projection_status = None
        if current_price_projection is not None:
            from projection_integration import finalize_projection
            projection_status = finalize_projection(candidate, current_price_projection, _clock=_projection_clock)
        from visibility_contract import verify_visibility_output
        visibility_validation = verify_visibility_output(candidate, run / 'visibility-private' / 'visibility-ledger.json', visibility_summary, inputs, manifest['files'], verified_source=verified, retained_candidate=retained_exclusions_candidate, retained_snapshot_sha256=retained_exclusions_snapshot_sha256, quarantine=quarantine, latest_negative_overlay=latest_overlay)
        visibility_overlay['final_image_search_engine_sha256']=sha(candidate/'image-search-engine.js')
        validation = load_trusted('validate_snapshot').validate(candidate, manifest['expected_date'])
        if not validation['ok']:
            raise ValueError('Snapshot gate failed: ' + json.dumps(validation))
        hashes = {p.relative_to(candidate).as_posix(): sha(p) for p in sorted(candidate.rglob('*')) if p.is_file()}
        result = {'schema': 1, 'status': 'validated-candidate', 'baseline_commit': BASELINE,
                  'collection_id': manifest['collection_id'], 'fixture': manifest['fixture'],
                  'collection_completion': 'producer-attested-not-independently-verified',
                  'input_manifest_sha256': manifest['_source_manifest_sha256'],
                  'input_inventory': {'files': len(manifest['files']), 'sha256': hashlib.sha256(json.dumps(manifest['files'],sort_keys=True,separators=(',',':')).encode()).hexdigest()},
                  'files': hashes, 'validation': validation, 'compact': compact,
                  'catalog_core': core, 'visibility': visibility_validation, 'visibility_overlay': visibility_overlay, 'chart_visibility': chart_visibility, 'deployed': False, 'relations': relation_status, 'relation_search': search_status, 'relation_supplement': supplement_status}
        if verified is not None and verified.historical_composition is not None:
            result['collection_completion'] = 'historical-prepared-inventory-only'
            result['historical_composition'] = dict(verified.historical_composition)
            result.update(collection_completion_verified=False, whole_catalog_complete=False, price_source_is_latest=False)
            result['retained_exclusion_lineage'] = {k:v for k,v in retained.items() if k not in ('ids','pending_ids')}
        if verified is not None and verified.saved_snapshot_composition is not None:
            result['collection_completion'] = 'bounded-saved-snapshot-inventory-only'
            result['saved_snapshot_composition'] = dict(verified.saved_snapshot_composition)
            result.update(collection_completion_verified=False, whole_catalog_complete=False, price_source_is_latest=False)
            result['retained_exclusion_lineage'] = {k:v for k,v in retained.items() if k not in ('ids','pending_ids')}
            result['latest_negative_overlay'] = latest_overlay.binding()
            result['saved_conflict_quarantine'] = quarantine.finish()
        if presentation_proof is not None:
            result['presentation_proof_sha256'] = presentation_sha256
        if projection_status is not None:
            result['current_price_projection'] = projection_status
        if daily_receipt_sha:
            result['daily_coverage_receipt_sha256'] = daily_receipt_sha
        snapshot_bytes = (json.dumps(result, indent=2) + '\n').encode('utf-8')
        (candidate / 'snapshot-manifest.json').write_bytes(snapshot_bytes)
        checked = load_trusted('validate_snapshot').validate(candidate, manifest['expected_date'], candidate / 'snapshot-manifest.json')
        if not checked['ok']: raise ValueError(json.dumps(checked))
        if verified is not None:
            (run / 'verified-source.json').write_text(json.dumps(verified.finish(), sort_keys=True) + '\n')
        # Same-filesystem rename exposes a complete candidate only. No existing target is removed.
        if output_parent_fd is not None:
            current_parent = open_directory(lexical_output.parent)
            try:
                if (os.fstat(current_parent).st_dev, os.fstat(current_parent).st_ino) != (os.fstat(output_parent_fd).st_dev, os.fstat(output_parent_fd).st_ino):
                    raise ValueError('Output parent replaced during generation')
            finally:
                os.close(current_parent)
        if output.exists(): raise FileExistsError(output)
        if output_parent_fd is not None:
            from verified_source import verify_artifact_directory
            output_capability.assert_root(candidate)
            expected_artifact = {**hashes, 'snapshot-manifest.json': hashlib.sha256(snapshot_bytes).hexdigest()}
            verify_artifact_directory(candidate_fd, expected_artifact)
        rename_new_directory(candidate, output)
        if candidate_fd is not None:
            target_fd = os.open(output.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=output_parent_fd)
            try:
                if (os.fstat(target_fd).st_dev, os.fstat(target_fd).st_ino) != (os.fstat(candidate_fd).st_dev, os.fstat(candidate_fd).st_ino):
                    raise ValueError('Candidate directory identity changed during final rename')
                verify_artifact_directory(target_fd, expected_artifact)
            finally:
                os.close(target_fd)
        diagnostic_output = lexical_output if verified is not None else output
        (run / 'SUCCESS.json').write_text(json.dumps({'candidate': str(diagnostic_output), 'manifest': str(diagnostic_output / 'snapshot-manifest.json')}))
        return result
    except Exception as exc:
        (run / 'FAILED.txt').write_text(str(exc) + '\n')
        diagnostic_run = Path(os.readlink(output.parent)) / run.name if output_parent_fd is not None else run
        raise RuntimeError(f'Build failed; recoverable work retained at {diagnostic_run}: {exc}') from exc
    finally:
        if verified is not None:
            verified.close()
        if output_capability is not None:
            output_capability.close()
        if candidate_fd is not None:
            os.close(candidate_fd)
        if output_parent_fd is not None:
            os.close(output_parent_fd)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-root', type=Path, required=True)
    p.add_argument('--completion-manifest', type=Path, required=True)
    static_source=p.add_mutually_exclusive_group(required=True)
    static_source.add_argument('--baseline-repo', type=Path, dest='baseline_repo')
    static_source.add_argument('--static-root', type=Path, dest='baseline_repo')
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--verified-completion-sha256', help='Opt-in verified prepared-source v1; requires externally pinned completion')
    p.add_argument('--retained-exclusions-candidate', type=Path)
    p.add_argument('--retained-exclusions-snapshot-sha256')
    p.add_argument('--quarantine-proof', type=Path)
    p.add_argument('--latest-negative-proof', type=Path)
    p.add_argument('--run-bindings-path', type=Path)
    p.add_argument('--run-bindings-sha256')
    p.add_argument('--compact', action='store_true', help='Generate lossless compact data only; does not enable a client')
    p.add_argument('--relations-bundle', type=Path)
    p.add_argument('--relations-approval', type=Path)
    p.add_argument('--relation-search-bundle', type=Path)
    p.add_argument('--relation-search-approval', type=Path)
    p.add_argument('--supplement-bundle', type=Path)
    p.add_argument('--supplement-approval', type=Path)
    p.add_argument('--daily-coverage-file', type=Path)
    p.add_argument('--daily-target-date')
    p.add_argument('--projection-package', type=Path)
    p.add_argument('--projection-package-sha256')
    p.add_argument('--projection-evidence', type=Path, action='append', default=[])
    p.add_argument('--presentation-proof', type=Path)
    p.add_argument('--presentation-sha256')
    a = p.parse_args()
    gate = None
    if a.projection_package or a.projection_package_sha256 or a.projection_evidence:
        if not (a.projection_package and a.projection_package_sha256 and a.projection_evidence):
            p.error('projection package, canonical SHA256 and evidence paths are required together')
        from projection_integration import load_projection
        gate = load_projection(a.projection_package, a.projection_package_sha256, a.projection_evidence)
    if bool(a.presentation_proof) != bool(a.presentation_sha256):
        p.error('presentation proof and canonical SHA256 required together')
    presentation = None
    if a.presentation_proof:
        if a.presentation_proof.is_symlink() or not a.presentation_proof.is_file():
            p.error('regular presentation proof file required')
        presentation = json.loads(a.presentation_proof.read_text())
    print(json.dumps(build(a.input_root, a.completion_manifest, a.baseline_repo, a.output_dir, a.compact, a.relations_bundle, a.relations_approval, a.relation_search_bundle, a.relation_search_approval, a.supplement_bundle, a.supplement_approval, daily_coverage_file=a.daily_coverage_file, daily_target_date=a.daily_target_date, current_price_projection=gate, presentation_proof=presentation, presentation_sha256=a.presentation_sha256, verified_completion_sha256=a.verified_completion_sha256, retained_exclusions_candidate=a.retained_exclusions_candidate, retained_exclusions_snapshot_sha256=a.retained_exclusions_snapshot_sha256, quarantine_proof=a.quarantine_proof, latest_negative_proof=a.latest_negative_proof, run_bindings_path=a.run_bindings_path, run_bindings_sha256=a.run_bindings_sha256), indent=2))


if __name__ == '__main__': main()
