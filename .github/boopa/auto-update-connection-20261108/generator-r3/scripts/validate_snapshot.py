#!/usr/bin/env python3
"""Read-only publication gate. Consistency is NOT proof a collection batch completed."""
import argparse
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

REQUIRED = ('index.html', 'item.html', 'lists_full.json', 'site-update.js', 'sw.js',
            'scripts/embed-hero.cjs', 'image-search.html', 'image-search-engine.js',
            'image-search-page.js', 'image-search-i18n.js', 'image-search-faq.js',
            'image-search.css', 'image-search-page.css', 'image-search-chrome.css', 'image-drop.js')

def validate(root, expected_date=None, manifest=None):
    root = Path(root).resolve()
    errors = []
    def fail(message): errors.append(message)
    def read(name):
        try: return json.loads((root / name).read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            fail(f'{name}: {exc}'); return None
    for name in REQUIRED:
        if not (root / name).is_file() or (root / name).stat().st_size == 0:
            fail(f'missing/empty required file: {name}')
    lists = read('lists_full.json')
    if not isinstance(lists, dict):
        fail('lists_full.json must be an object'); lists = {}
    stats = lists.get('stats')
    if not isinstance(stats, dict):
        fail('lists.stats must be an object'); stats = {}
    dates = [lists.get('max_date'), stats.get('max_date')]
    for date in dates:
        try:
            if not isinstance(date, str) or datetime.date.fromisoformat(date).isoformat() != date:
                raise ValueError()
        except ValueError: fail(f'invalid max_date: {date!r}')
    if dates[0] != dates[1]: fail('lists.max_date differs from stats.max_date')
    if expected_date is not None and dates[0] != expected_date:
        fail(f'max_date {dates[0]!r} != expected date {expected_date!r}')
    spec=importlib.util.spec_from_file_location('trusted_validate_search_core',Path(__file__).with_name('validate_search_core.py'))
    core_validator=importlib.util.module_from_spec(spec);spec.loader.exec_module(core_validator)
    try:core_validator.validate(root)
    except (ValueError,OSError,KeyError,TypeError) as exc:fail('search core: '+str(exc))
    seen = set(); count = 0
    for i in range(24):
        name = f'search_index_{i}.json'; rows = read(name)
        if not isinstance(rows, list): fail(f'{name}: expected array'); continue
        for offset, row in enumerate(rows):
            count += 1
            if not isinstance(row, list) or len(row) != 14:
                fail(f'{name}[{offset}]: expected 14-column row'); continue
            item_id = row[0]
            if not isinstance(item_id, str) or not item_id.isascii() or not item_id.isdecimal() or item_id.startswith('0'):
                fail(f'{name}[{offset}]: noncanonical positive decimal string ID'); continue
            if item_id in seen: fail(f'duplicate item ID {item_id}')
            seen.add(item_id)
    total = stats.get('total')
    if type(total) is not int or total < 1: fail('stats.total must be a positive integer')
    if total != count: fail(f'stats.total {total!r} != shard rows {count}')
    if len(seen) != count: fail(f'unique valid IDs {len(seen)} != shard rows {count}')
    if (root / 'scripts/embed-hero.cjs').is_file():
        try:
            result = subprocess.run(['node', str(root / 'scripts/embed-hero.cjs'), '--check'], cwd=root,
                                    capture_output=True, text=True, timeout=60)
            if result.returncode: fail('embed-hero --check failed: ' + (result.stderr or result.stdout).strip())
        except (OSError, subprocess.TimeoutExpired) as exc: fail(f'embed-hero --check: {exc}')
    if manifest:
        try:
            data = json.loads(Path(manifest).read_text(encoding='utf-8'))
            files = data['files']
            if data.get('schema') != 1 or not isinstance(files, dict) or not files:
                raise ValueError('expected schema=1 and nonempty files mapping')
            try:core_validator.validate(root,data)
            except (ValueError,OSError,KeyError,TypeError) as exc:fail('search core: '+str(exc))
            mandatory = set(REQUIRED) | {f'search_index_{i}.json' for i in range(24)}
            for name in sorted(mandatory - files.keys()): fail(f'manifest missing required entry: {name}')
            for name, digest in files.items():
                if not isinstance(name, str):
                    fail('manifest path must be a string'); continue
                target = (root / name).resolve()
                if Path(name).is_absolute() or root not in target.parents:
                    fail(f'unsafe manifest path: {name}'); continue
                if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                    fail(f'invalid SHA256: {name}'); continue
                try:
                    if hashlib.sha256(target.read_bytes()).hexdigest() != digest: fail(f'hash mismatch: {name}')
                except OSError as exc: fail(f'manifest file {name}: {exc}')
        except (OSError, ValueError, KeyError, TypeError) as exc: fail(f'invalid snapshot manifest: {exc}')
    return {'ok': not errors, 'max_date': dates[0], 'rows': count, 'unique_ids': len(seen),
            'collection_completion_verified': False, 'errors': errors}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--expected-date', help='Explicit YYYY-MM-DD snapshot date; no wall-clock assumption')
    parser.add_argument('--manifest', type=Path, help='Optional schema 1 {files:{relative_path:sha256}} manifest')
    args = parser.parse_args()
    result = validate(args.root, args.expected_date, args.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result['ok'] else 1)
