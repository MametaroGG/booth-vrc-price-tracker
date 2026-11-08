"""Local pure snapshot adapter. No transport, credentials, runner or publication.
Commit is an expected caller-verified checkout identity, not independently attested Git.
All regular data/meta files are bound; only JSON and empty .gitkeep are accepted.
"""
import hashlib
from collections.abc import Mapping
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import unicodedata
from datetime import date, datetime, timezone, timedelta
from charts_contract import generate_charts, validate_charts

SCOPE = 'immutable-captured-snapshot-integrity'

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def strict_json(raw):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out: raise ValueError('Duplicate JSON key: '+k)
            out[k] = v
        return out
    def bad(value): raise ValueError('Nonfinite JSON constant: '+value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)

def iso(value):
    if not isinstance(value, str): raise ValueError('Date must be string')
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value: raise ValueError('Noncanonical date')
    return parsed

def commit_value(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}', value):
        raise ValueError('Exact lowercase commit required')
    return value

def file_digest(path):
    """Bound hashing memory independently of total snapshot size."""
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


class CapturedSnapshot(Mapping):
    """Captured digests, not retained raw bytes; reads verify capture identity.

    Memory is O(path inventory + largest individual record), not total bytes.
    No lazy read can silently accept content changed since this capture.
    """
    def __init__(self, tree, hashes):
        self.tree = tree
        self.hashes = hashes

    def __iter__(self):
        return iter(self.hashes)

    def __len__(self):
        return len(self.hashes)

    def __getitem__(self, name):
        expected = self.hashes[name]
        path = self.tree / name
        for parent in path.relative_to(self.tree).parents:
            if (self.tree / parent).is_symlink(): raise ValueError('Linked captured input')
        if not stat.S_ISREG(path.lstat().st_mode): raise ValueError('Nonregular captured input')
        raw = path.read_bytes()
        if digest(raw) != expected: raise ValueError('Input changed since capture: '+name)
        return raw

    def __eq__(self, other):
        if isinstance(other, CapturedSnapshot):
            return self.hashes == other.hashes
        if isinstance(other, Mapping):
            return len(self) == len(other) and all(name in other and self[name] == other[name] for name in self)
        return NotImplemented


def captured_hashes(files):
    return files.hashes if isinstance(files, CapturedSnapshot) else {p:digest(b) for p,b in files.items()}


def snapshot(tree):
    tree = Path(tree)
    if tree.is_symlink() or not tree.is_dir(): raise ValueError('Invalid snapshot root')
    files = {}; folded = set()
    for directory in ('data', 'meta'):
        base = tree / directory
        if base.is_symlink() or not base.is_dir(): raise ValueError('Missing/linked '+directory)
        for root, dirs, names in os.walk(base, followlinks=False):
            for name in dirs:
                if (Path(root)/name).is_symlink(): raise ValueError('Linked directory')
            for name in names:
                path = Path(root)/name
                if not stat.S_ISREG(path.lstat().st_mode): raise ValueError('Nonregular input')
                rel = path.relative_to(tree).as_posix()
                if '\\' in rel or any(ord(c)<32 for c in rel): raise ValueError('Unsafe path')
                key = unicodedata.normalize('NFC',rel).casefold()
                if key in folded: raise ValueError('Normalized path collision')
                folded.add(key); files[rel] = file_digest(path)
    if not files: raise ValueError('Empty snapshot')
    return CapturedSnapshot(tree, files)

def inventory_bytes(files):
    return json.dumps(captured_hashes(files), indent=1, sort_keys=True).encode()

def verify_inventory(files, raw):
    ledger = strict_json(raw)
    actual = captured_hashes(files)
    if not isinstance(ledger,dict) or ledger != actual: raise ValueError('Exact inventory mismatch')
    return ledger

def inspect_records(files, minimum, as_of, max_age_days):
    minimum=iso(minimum); as_of=iso(as_of)
    if type(max_age_days) is not int or max_age_days<0: raise ValueError('Invalid age budget')
    latest=None; ids=set(); placeholders=[]
    for name in sorted(files):
        raw = files[name]
        if Path(name).name=='.gitkeep' and not raw:
            placeholders.append(name); continue
        if Path(name).suffix!='.json': raise ValueError('Unsupported non-JSON input: '+name)
        record = strict_json(raw)
        if not name.startswith('data/'): continue
        if name == 'data/collection_receipt.json':
            # C1 collector metadata, never a product. Keep the exact bytes in
            # the capture/inventory/staged output. Authenticated run, eligibility
            # and ledger binding remain the resolver's responsibility; this
            # adapter only validates the narrow metadata format, not authority.
            if (not isinstance(record, dict) or 'id' in record or 'variations' in record or
                    record.get('schema') != 'boopa-collection-receipt-v1' or
                    record.get('repository') != 'MametaroGG/booth-vrc-price-tracker' or
                    record.get('scope') != 'bounded-filtered-search-observation' or
                    record.get('whole_catalog_complete') is not False):
                raise ValueError('Invalid collector receipt metadata')
            for key in ('run_id', 'run_attempt'):
                if not isinstance(record.get(key), str) or not re.fullmatch('[1-9][0-9]{0,19}', record[key]):
                    raise ValueError('Invalid collector receipt identity')
            if record.get('reservation_id') != record['run_id']+'-'+record['run_attempt']:
                raise ValueError('Invalid collector receipt reservation')
            commit_value(record.get('source_commit'))
            if (record.get('status') not in ('completed', 'paused') or
                    record.get('failed') is not False or
                    record.get('reservation_completed') is not True or
                    type(record.get('continueCollection')) is not bool):
                raise ValueError('Invalid collector receipt outcome')
            if ((record['status'] == 'completed' and 'reason' in record) or
                    (record['status'] == 'paused' and record.get('reason') not in ('deadline', 'day-boundary'))):
                raise ValueError('Invalid collector receipt stop reason')
            for key in ('started_at_ms', 'stopped_at_ms', 'deadline_ms', 'blocked_until_ms', 'pending_retry_count'):
                if type(record.get(key)) is not int or record[key] < 0:
                    raise ValueError('Invalid collector receipt counters')
            metrics = record.get('metrics')
            keys = ('searchPages', 'searchFailures', 'itemSuccess', 'itemFailures', 'unavailable',
                    'retries', 'duplicatesAvoided', 'chargedHttpAttempts', 'dailyChargedRequests')
            if not isinstance(metrics, dict) or any(type(metrics.get(k)) is not int or metrics[k] < 0 for k in keys):
                raise ValueError('Invalid collector receipt metrics')
            continue
        if name in ('data/crawl_state.json','data/request_budget.json'):
            if not isinstance(record,dict) or 'id' in record or 'variations' in record:
                raise ValueError('Invalid tracker state')
            continue
        if not isinstance(record,dict): raise ValueError('Invalid product')
        ident=record.get('id')
        if not isinstance(ident,str) or not re.fullmatch('[1-9][0-9]*',ident) or ident in ids:
            raise ValueError('Invalid/duplicate ID')
        if name != 'data/'+ident[:3]+'/'+ident+'.json': raise ValueError('ID/path mismatch')
        ids.add(ident); variations=record.get('variations')
        if not isinstance(variations,dict): raise ValueError('Invalid variations')
        representative=[]
        for series in variations.values():
            if not isinstance(series,list): raise ValueError('Invalid history')
            for row in series:
                if not isinstance(row,dict): raise ValueError('Invalid row')
                day=iso(row.get('date')); price=row.get('price')
                if type(price) not in (int,float) or not math.isfinite(price) or price<0 or day>as_of:
                    raise ValueError('Invalid observation')
            if len(series)>len(representative): representative=series
        if representative:
            day=max(iso(row['date']) for row in representative)
            latest=day if latest is None else max(latest,day)
    if not ids or latest is None: raise ValueError('No dated products')
    if latest<minimum or (as_of-latest).days>max_age_days: raise ValueError('Stale/regressing snapshot')
    return latest.isoformat(), placeholders

def attest(tree, commit, inventory, minimum, *, as_of=None, max_age_days=1, fixture=False):
    commit_value(commit)
    if type(fixture) is not bool: raise ValueError('Fixture must be boolean')
    # Tracker histories and request-budget observation dates are JST calendar days.
    # Keep explicit as_of unchanged and retain the existing future/age bounds.
    as_of=as_of or datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    raw=Path(inventory).read_bytes(); files=snapshot(tree); ledger=verify_inventory(files,raw)
    latest, placeholders=inspect_records(files,minimum,as_of,max_age_days)
    return {'schema':1,'status':'complete','collection_id':commit,'fixture':fixture,
            'tracker_commit':commit,'expected_date':latest,'completion_scope':SCOPE,
            'scope_limit':'Not crawl/daily-coverage completion; commit must be verified by caller checkout.',
            'inventory_digest':digest(raw),'inventory_count':len(ledger),'files':ledger,
            'as_of':as_of,'minimum_source_date':minimum,'max_source_age_days':max_age_days,
            'bound_empty_placeholders':placeholders}

def prepare(tree, inventory, attestation, output, *, expected_commit, charts=None):
    """Stage in a new local directory. No overwrite, source mutation or network."""
    commit_value(expected_commit)
    claim_raw=Path(attestation).read_bytes(); claim=strict_json(claim_raw)
    if not isinstance(claim,dict) or type(claim.get('schema')) is not int or claim.get('schema')!=1 or claim.get('status')!='complete' or type(claim.get('fixture')) is not bool:
        raise ValueError('Explicit complete attestation required')
    if claim.get('tracker_commit')!=expected_commit or claim.get('collection_id')!=expected_commit or claim.get('completion_scope')!=SCOPE:
        raise ValueError('Attestation identity/scope mismatch')
    raw=Path(inventory).read_bytes(); files=snapshot(tree); ledger=verify_inventory(files,raw)
    if claim.get('inventory_digest')!=digest(raw) or type(claim.get('inventory_count')) is not int or claim['inventory_count']!=len(ledger) or claim.get('files')!=ledger:
        raise ValueError('Attestation inventory commitment mismatch')
    latest, placeholders=inspect_records(files,claim['minimum_source_date'],claim['as_of'],claim['max_source_age_days'])
    if latest!=claim.get('expected_date') or placeholders!=claim.get('bound_empty_placeholders'):
        raise ValueError('Attestation date/placeholders mismatch')
    output=Path(output)
    if output.exists() or output.is_symlink(): raise FileExistsError(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.'+output.name+'-',dir=output.parent))
    try:
        for name, data in files.items():
            dest=stage/('tracker_meta/'+name[5:] if name.startswith('meta/') else name)
            dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(data)
        for directory in ('data','tracker_meta'): (stage/directory).mkdir(exist_ok=True)
        chart_data=Path(charts).read_bytes() if charts else json.dumps(generate_charts(stage),ensure_ascii=False).encode()
        validate_charts(strict_json(chart_data),stage,claim['fixture'])
        (stage/'charts.json').write_bytes(chart_data)
        # Re-read the source and commitment to reject a changed snapshot during staging.
        if snapshot(tree)!=files or Path(inventory).read_bytes()!=raw or Path(attestation).read_bytes()!=claim_raw:
            raise ValueError('Inputs changed during preparation')
        out_files={p.relative_to(stage).as_posix():digest(p.read_bytes()) for p in stage.rglob('*') if p.is_file()}
        result={'schema':1,'status':'complete','fixture':claim['fixture'],'collection_id':expected_commit,
                'tracker_commit':expected_commit,'expected_date':latest,'inventory_digest':digest(raw),
                'inventory_count':len(ledger),'producer_attestation_sha256':digest(claim_raw),
                'bound_empty_placeholders':placeholders,'files':out_files}
        (stage/'completion.json').write_text(json.dumps(result,indent=2)+'\n')
        # Isolated adapter targets are private; no externally writable concurrent destination.
        if output.exists() or output.is_symlink(): raise FileExistsError(output)
        stage.rename(output)
        return result
    except Exception as exc:
        (stage/'FAILED.txt').write_text(str(exc)+'\n')
        raise
