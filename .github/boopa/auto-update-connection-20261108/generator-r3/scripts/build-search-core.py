#!/usr/bin/env python3
"""Build deterministic image-free static search rows and lazy image buckets.

No requests or collector access. All 14 row fields remain at their existing
positions; field 9 alone is replaced with ''. Recombining the ID-keyed image
buckets MUST reproduce every source row exactly. --check never changes files.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import unicodedata


import importlib.util
_codec_spec=importlib.util.spec_from_file_location('trusted_compact_codec',Path(__file__).resolve().parent/'compact_codec.py')
compact_codec=importlib.util.module_from_spec(_codec_spec)
_codec_spec.loader.exec_module(compact_codec)

PARTS = 24
BUCKETS = 512


def encode(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def info(data, rows, measure=True):
    return {'sha256': hashlib.sha256(data).hexdigest(), 'rows': rows,
            'raw_bytes': len(data), 'gzip_bytes': len(gzip.compress(data, compresslevel=9, mtime=0)) if measure else None}


def aggregate(items):
    return {key: sum(item[key] for item in items) if all(item[key] is not None for item in items) else None for key in ('rows', 'raw_bytes', 'gzip_bytes')}


def image_buckets(rows, count):
    buckets = [{} for _ in range(count)]
    for row in rows:
        buckets[int(row[0]) % count][row[0]] = row[9]
    return [dict(sorted(bucket.items(), key=lambda pair: int(pair[0]))) for bucket in buckets]


def normalize(value):
    return unicodedata.normalize('NFKC', str(value or '')).lower()


def transfer_cases(rows):
    # Transfer scenarios, not a claim to reproduce personal relevance ranking.
    # These select the first30 popular matches using existing searchable fields.
    ranked = sorted(rows, key=lambda row: -(row[8] or 0))
    def query(q):
        q = normalize(q)
        return [r for r in ranked if q in '\x01'.join(normalize(r[i]) for i in (1, 12, 13)) or q in normalize(r[7])]
    cases = {'popular': ranked}
    for q in ('メガネ', '衣装', 'vrchat', 'ミルフィ'):
        cases['query:' + q] = query(q)
    cases['free:texture-category'] = [r for r in ranked if r[2] == 0 and r[7] == '3Dテクスチャ 3Dモデル']
    sample_shop = next((r[12] for r in ranked if r[12]), '')
    if sample_shop:
        cases['shop:' + sample_shop] = [r for r in ranked if r[12] == sample_shop]
    return {name: {'total': len(matches), 'ids': [r[0] for r in matches[:30]]} for name, matches in cases.items()}


def build(root, check=False, write_report=True):
    source, all_rows, sources, seen = [], [], [], set()
    for i in range(PARTS):
        path = root / f'search_index_{i}.json'
        data = path.read_bytes()
        rows = json.loads(data)
        if not isinstance(rows, list):
            raise ValueError(f'{path.name}: expected array')
        for row in rows:
            if not isinstance(row, list) or len(row) != 14:
                raise ValueError(f'{path.name}: expected 14-field row')
            if not isinstance(row[0], str) or not re.fullmatch(r'[1-9][0-9]*', row[0]) or row[0] in seen:
                raise ValueError(f'{path.name}: noncanonical or duplicate ID')
            if not isinstance(row[9], str):
                raise ValueError(f'{path.name}: expected image string')
            seen.add(row[0])
        source.append(rows)
        all_rows.extend(rows)
        sources.append({'path': path.name, **info(data, len(rows), write_report)})

    bucket_maps = image_buckets(all_rows, BUCKETS)
    outputs, cores, images = {}, [], []
    for i, rows in enumerate(source):
        stripped = [row[:9] + [''] + row[10:] for row in rows]
        for before, after in zip(rows, stripped):
            restored = after[:]
            restored[9] = bucket_maps[int(after[0]) % BUCKETS][after[0]]
            if restored != before:
                raise ValueError('Exact source-row recombination failed: ' + before[0])
        name = f'search-core/core_{i}.json'
        packed = compact_codec.encode(stripped)
        if not compact_codec.exact(compact_codec.decode(packed), stripped):
            raise ValueError("Compact JSON type/value roundtrip failed")
        data = encode(packed)
        outputs[name] = data
        cores.append({'path': name, **info(data, len(stripped), write_report)})
    for i, bucket in enumerate(bucket_maps):
        name = f'search-core/images_{i}.json'
        data = encode(bucket)
        outputs[name] = data
        images.append({'path': name, **info(data, len(bucket), write_report)})

    cases = transfer_cases(all_rows) if write_report else {}
    comparison = {}
    for count in ((128, 256, 512, 1024) if write_report else ()):
        buckets = bucket_maps if count == BUCKETS else image_buckets(all_rows, count)
        sizes = [info(encode(bucket), len(bucket)) for bucket in buckets]
        measured = {}
        for name, case in cases.items():
            indexes = sorted({int(ident) % count for ident in case['ids']})
            cost = aggregate([sizes[i] for i in indexes])
            measured[name] = {'matched_total': case['total'], 'first_page_ids': case['ids'],
                              'requested_buckets': indexes, 'requests': len(indexes),
                              'image_raw_bytes': cost['raw_bytes'], 'image_gzip_bytes': cost['gzip_bytes'],
                              'core_plus_first_page_gzip_bytes': aggregate(cores)['gzip_bytes'] + cost['gzip_bytes']}
        comparison[str(count)] = {'all_images': aggregate(sizes), 'first_pages': measured}

    report = {'schema': 1, 'rows': len(all_rows), 'unique_ids': len(seen),
              'image_field': 9, 'core_field_count': 14, 'image_buckets': BUCKETS,
              'source': {'files': sources, 'total': aggregate(sources)},
              'core': {'files': cores, 'total': aggregate(cores)},
              'images': {'files': images, 'total': aggregate(images)},
              'bucket_comparison': comparison,
              'verification': {'all_rows_exactly_recombined': True, 'all_other_fields_identical': True,
                               'deterministic_json': 'UTF-8 compact JSON, no ASCII escaping, one trailing LF',
                               'gzip': 'Local gzip level9 mtime0; not observed HTTP Content-Encoding/wire timing',
                               'scenario_ranking': 'Stable descending likes among matching query/category/shop rows; not personal relevance parity'}}
    report['catalog_core'] = {'schema': 1, 'format': 'compact-core-v1', 'rows': len(all_rows), 'part_rows': [len(rows) for rows in source], 'image_buckets': BUCKETS}
    if write_report:
        outputs['reports/search-core-build.json'] = (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    output_dir = root / 'search-core'
    expected = {Path(name).name for name in outputs if name.startswith('search-core/')}
    if output_dir.exists():
        unexpected = {p.name for p in output_dir.iterdir()} - expected
        if unexpected:
            raise ValueError('Unexpected output files; refusing to delete: ' + ', '.join(sorted(unexpected)))
    for name, data in outputs.items():
        path = root / name
        if check:
            if not path.is_file() or path.read_bytes() != data:
                raise ValueError('Generated file missing/stale: ' + name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + '.building')
            temporary.write_bytes(data)
            temporary.replace(path)
    print(json.dumps({'check': check, 'rows': len(all_rows), 'generated_files': sum(name.startswith('search-core/') for name in outputs),
                      'source': aggregate(sources), 'core': aggregate(cores), 'images': aggregate(images),
                      'all_rows_exactly_recombined': True}, indent=2))
    return report


def self_test():
    """Small isolated positive/negative fixtures; never modifies the real catalog."""
    import contextlib
    import io
    import tempfile
    passed = []
    def fixture(root):
        for i in range(PARTS):
            row = [str(i + 1), 'item', 100, 100, 100, 0, 0, 'category', i,
                   '' if i % 2 else 'image' + str(i), 20261029, 1, 'shop', 'tags']
            (root / f'search_index_{i}.json').write_bytes(encode([row]))
    def refuse(root, check):
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                build(root, check)
        except ValueError:
            return
        raise AssertionError('Invalid or stale data was accepted')
    with tempfile.TemporaryDirectory(prefix='boopa-search-core-') as temp:
        root = Path(temp)
        fixture(root)
        with contextlib.redirect_stdout(io.StringIO()):
            build(root)
            build(root, True)
        passed.append('deterministic build/check with empty and nonempty images')
        for name in ('core_3.json', 'images_4.json'):
            path = root / 'search-core' / name
            original = path.read_bytes()
            if name.startswith('core'):
                path.write_bytes(b'[]\n')
            else:
                path.unlink()
            refuse(root, True)
            path.write_bytes(original)
            passed.append('tampered/missing generated file refused: ' + name)
        for kind in ('duplicate', 'shape', 'image-type'):
            fixture(root)
            path = root / 'search_index_1.json'
            row = json.loads(path.read_bytes())[0]
            if kind == 'duplicate':
                row[0] = '1'
            elif kind == 'shape':
                row.pop()
            else:
                row[9] = None
            path.write_bytes(encode([row]))
            refuse(root, False)
            passed.append(kind + ' input refused')
    print(json.dumps({'passed': len(passed), 'tests': passed}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--no-report', action='store_true', help='Producer mode: no report/benchmark output in candidate')
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        build(args.root.resolve(), args.check, write_report=not args.no_report)
