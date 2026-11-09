"""Pinned, offline public-catalog visibility. Source records are never modified.

Only a last-known HTTP 404/410 marker is exclusion evidence. This is not proof
that an item is permanently private. Missing metadata and transient failures do
not imply withdrawal. Invalid or conflicting withdrawal evidence stops a build.
"""
import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
_ID = re.compile(r'[1-9][0-9]*', re.ASCII)
_SHA = re.compile(r'[0-9a-f]{64}', re.ASCII)
_DATE = re.compile(r'\d{4}-\d{2}-\d{2}', re.ASCII)


def canonical_id(value):
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def canonical_date(value):
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise ValueError('Canonical YYYY-MM-DD visibility date required')
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('Noncanonical visibility date')
    return parsed


def strict_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError('Duplicate metadata key: ' + key)
            out[key] = value
        return out

    def nonfinite(value):
        raise ValueError('Nonfinite metadata constant: ' + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def metadata_success(record, ident):
    if not isinstance(record, dict):return False
    status=record.get('status')
    return (record.get('id')==ident and isinstance(record.get('name'),str) and bool(record['name'].strip()) and record.get('unavailable',False) is False and ('status' not in record or type(status) is int and 200<=status<300))


def read_retained_exclusions(candidate, snapshot_sha256):
    """Read a pinned prior candidate only as the no-restoration set oracle.

    This does not inherit its source, QA, release or current-status assertions.
    The original candidate is never modified. Both reads are descriptor anchored.
    """
    import os
    from verified_source import open_directory, exact_read
    if not isinstance(snapshot_sha256, str) or not _SHA.fullmatch(snapshot_sha256):
        raise ValueError('Pinned prior candidate snapshot SHA256 required')
    fd = open_directory(candidate)
    try:
        snapshot_raw = exact_read(fd, 'snapshot-manifest.json', 128 * 1024 * 1024)
        if hashlib.sha256(snapshot_raw).hexdigest() != snapshot_sha256:
            raise ValueError('Prior candidate snapshot commitment mismatch')
        snapshot = strict_json(snapshot_raw)
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get('files'), dict):
            raise ValueError('Prior candidate inventory required')
        expected = snapshot['files'].get('lists_full.json')
        if not isinstance(expected, str) or not _SHA.fullmatch(expected):
            raise ValueError('Prior lists commitment required')
        lists_raw = exact_read(fd, 'lists_full.json', 128 * 1024 * 1024)
        if hashlib.sha256(lists_raw).hexdigest() != expected:
            raise ValueError('Prior candidate lists commitment mismatch')
        lists = strict_json(lists_raw)
        from visibility_contract import validate_public_visibility
        hidden = validate_public_visibility(lists.get('visibility'))
        pending = set(lists['visibility'].get('pending_metadata_ids', []))
        ids = hidden - pending
        return {'ids': frozenset(ids), 'pending_ids': frozenset(pending),
                'pending_ids_sha256': hashlib.sha256(json_bytes(sorted(pending))).hexdigest(),
                'public_hidden_ids_sha256': hashlib.sha256(json_bytes(sorted(hidden))).hexdigest(),
                'snapshot_sha256': snapshot_sha256,
                'lists_sha256': expected,
                'ids_sha256': hashlib.sha256(json_bytes(sorted(ids))).hexdigest()}
    finally:
        os.close(fd)


class VisibilityPolicy:
    """Read metadata once and retain only hashes, IDs and exclusion evidence.

    expected_hashes uses the frozen manifest's tracker_meta/... paths. Without
    that map the standalone build binds its own exact metadata reads. Records
    returned by iter_metadata are the same bytes used for each evidence hash.
    """
    def __init__(self, meta_root, expected_hashes=None, generation_time=None, verified_source=None, retained_exclusions=None, quarantine=None, latest_negative_overlay=None):
        self.verified_source = verified_source
        self.quarantine = quarantine
        self.latest_negative_overlay = latest_negative_overlay
        self.pending_ids = frozenset() if latest_negative_overlay is None else getattr(latest_negative_overlay, 'pending_ids', frozenset())
        self.success_metadata_ids = set()
        self.overlay_ids = frozenset() if latest_negative_overlay is None else latest_negative_overlay.ids
        self.root = Path(meta_root)
        self.now = generation_time or datetime.now(timezone.utc)
        if not isinstance(self.now, datetime) or self.now.tzinfo is None:
            raise ValueError('Aware visibility generation timestamp required')
        self.today = self.now.astimezone(JST).date()
        self.expected_hashes = expected_hashes
        if expected_hashes is not None:
            if not isinstance(expected_hashes, dict) or any(
                    not isinstance(path, str) or not path.startswith('tracker_meta/') or
                    not isinstance(sha, str) or not _SHA.fullmatch(sha)
                    for path, sha in expected_hashes.items()):
                raise ValueError('Invalid pinned metadata hash inventory')
        self.metadata_hashes = {}
        self.metadata_ids = set()
        self.markers = {}
        self.backend_ids = set()
        self.hidden_ids = set()
        self.retained_exclusions = retained_exclusions
        self.retained_ids = frozenset() if retained_exclusions is None else retained_exclusions['ids']
        if type(self.retained_ids) is not frozenset or any(not canonical_id(x) for x in self.retained_ids):
            raise ValueError('Invalid retained exclusion IDs')
        for proof in (quarantine, latest_negative_overlay):
            if proof is not None and (retained_exclusions is None or proof.retained != retained_exclusions):
                raise ValueError('Saved policy and retained floor differ')
        if retained_exclusions is not None and retained_exclusions.get('pending_ids') and (latest_negative_overlay is None or getattr(latest_negative_overlay, 'pending_metadata', None) is None):
            raise ValueError('Prior pending requires explicit pending proof')
        self._loaded = False

    def excluded_ids(self):
        return set(self.markers) | self.retained_ids | self.overlay_ids | self.pending_ids

    def iter_metadata(self):
        if self._loaded:
            raise ValueError('Metadata may only be consumed once')
        self._loaded = True
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError('Existing nonlinked metadata directory required')
        paths = self.verified_source.paths('tracker_meta') if self.verified_source else self.root.rglob('*')
        for path in sorted(paths):
            if not self.verified_source and path.is_symlink():
                raise ValueError('Linked metadata input: ' + str(path))
            if not self.verified_source and path.is_dir():
                continue
            if not self.verified_source and not path.is_file():
                raise ValueError('Nonregular metadata input: ' + str(path))
            relative = path.relative_to(self.root)
            name = 'tracker_meta/' + relative.as_posix()
            raw = self.verified_source.read_bytes(path) if self.verified_source else path.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            if self.expected_hashes is not None and self.expected_hashes.get(name) != sha:
                raise ValueError('Unbound metadata input: ' + name)
            self.metadata_hashes[name] = sha
            if path.name == '.gitkeep' and not raw:
                continue
            if path.suffix != '.json':
                raise ValueError('Unsupported metadata input: ' + name)
            # Root JSON files are collector bookkeeping, not product records.
            if len(relative.parts) == 1:
                continue
            try:
                record = strict_json(raw)
            except (ValueError, UnicodeDecodeError) as exc:
                raise ValueError('Invalid metadata ' + name + ': ' + str(exc)) from exc
            ident = path.stem
            if not canonical_id(ident) or ident in self.metadata_ids:
                raise ValueError('Invalid/duplicate metadata path ID: ' + name)
            self.metadata_ids.add(ident)
            if not isinstance(record, dict):
                raise ValueError('Metadata record must be an object: ' + name)
            if 'id' in record and (not canonical_id(record['id']) or record['id'] != ident):
                raise ValueError('Metadata ID/path mismatch: ' + name)
            flag = record.get('unavailable', False)
            if type(flag) is not bool:
                raise ValueError('Nonboolean unavailable marker: ' + name)
            if flag:
                status = record.get('status')
                if type(status) is not int or not 100 <= status <= 599:
                    raise ValueError('Invalid unavailable HTTP status: ' + name)
                if status in (404, 410):
                    if record.get('id') != ident:
                        raise ValueError('Missing canonical unavailable item ID: ' + name)
                    fetched = canonical_date(record.get('fetched_at'))
                    if fetched > self.today:
                        raise ValueError('Future unavailable marker: ' + name)
                    # A success body and an unavailable tombstone cannot be
                    # asserted by the same producer record.
                    if record.get('name'):
                        raise ValueError('Conflicting unavailable metadata body: ' + name)
                    self.markers[ident] = dict(id=ident, path=name, sha256=sha,
                                               status=status, fetched_at=fetched.isoformat())
            elif record.get('status') in (404, 410):
                raise ValueError('Conflicting unavailable flag/status: ' + name)
            if record.get('name') and record.get('id') != ident:
                raise ValueError('Missing canonical metadata ID: ' + name)
            if metadata_success(record, ident):
                self.success_metadata_ids.add(ident)
            yield ident, record
        if self.expected_hashes is not None and set(self.metadata_hashes) != set(self.expected_hashes):
            raise ValueError('Pinned metadata inventory differs from consumed input')

    def observe_product(self, record, raw=None):
        """Validate all saved histories before exclusion; never edit source markers."""
        ident = record.get('id')
        if not canonical_id(ident) or ident in self.backend_ids:
            raise ValueError('Invalid/duplicate backend visibility ID')
        self.backend_ids.add(ident)
        marker = self.markers.get(ident)
        overlay = None if self.latest_negative_overlay is None else self.latest_negative_overlay.entries.get(ident)
        saved_mode = self.quarantine is not None or self.latest_negative_overlay is not None
        total = after = overlay_after = 0
        if marker is not None or saved_mode:
            variations = record.get('variations')
            if not isinstance(variations, dict):
                raise ValueError('Invalid saved history: ' + ident)
            for key, series in variations.items():
                if not isinstance(key, str) or not isinstance(series, list):
                    raise ValueError('Invalid saved variation: ' + ident)
                for observation in series:
                    if not isinstance(observation, dict):
                        raise ValueError('Invalid saved observation: ' + ident)
                    observed_day = canonical_date(observation.get('date'))
                    price = observation.get('price')
                    if type(price) not in (int, float) or not math.isfinite(price) or price < 0:
                        raise ValueError('Invalid saved price: ' + ident)
                    if saved_mode and observed_day > self.today:
                        raise ValueError('Future saved observation: ' + ident)
                    total += 1
                    after += int(marker is not None and observed_day.isoformat() > marker['fetched_at'])
                    overlay_after += int(overlay is not None and observed_day.isoformat() > overlay['fetched_at'])
            # Price and saved-metadata dates retain self.today. Only a separately
            # validated observed overlay may use a later negative observation day.
            overlay_upper_day=self.today
            if overlay is not None and self.latest_negative_overlay.observation_upper_day is not None:
                overlay_upper_day=self.latest_negative_overlay.observation_upper_day
            if overlay is not None and (canonical_date(overlay['fetched_at']) > overlay_upper_day or overlay_after):
                raise ValueError('Latest negative conflicts with saved history: ' + ident)
            if after:
                if self.quarantine is None:
                    raise ValueError('Newer price observation conflicts with unavailable marker: ' + ident)
                self.quarantine.check(record, raw, marker, total, after)
        if marker is not None or ident in self.retained_ids or ident in self.overlay_ids or ident in self.pending_ids:
            self.hidden_ids.add(ident)
            return False
        return True

    def public_payload(self):
        # A metadata-only tombstone must also suppress stale bookmark/history
        # and remote fallback entries. Backend partition counts stay separate.
        value = dict(schema=1, hidden_ids=sorted(self.excluded_ids()))
        if self.latest_negative_overlay is not None and getattr(self.latest_negative_overlay, 'pending_metadata', None) is not None:
            value['pending_metadata_ids'] = sorted(self.pending_ids)
        return value

    def write_evidence(self, directory, source_min_date, source_max_date):
        """Private exact-set ledger; no names or source records are serialized."""
        if self.latest_negative_overlay is not None and getattr(self.latest_negative_overlay, 'pending_metadata', None) is not None:
            self.latest_negative_overlay.validate_population(self.backend_ids, self.metadata_ids, self.success_metadata_ids, set(self.markers) | self.retained_ids | self.overlay_ids, set(self.markers))
        visible = self.backend_ids - self.hidden_ids
        inventory_sha = hashlib.sha256(json_bytes(self.metadata_hashes)).hexdigest()
        counts = dict(backend_total=len(self.backend_ids), visible_total=len(visible),
                      confirmed_hidden_total=len(self.hidden_ids))
        ledger = dict(schema=1, policy='last-known-http-unavailable-v1',
                      evidence_scope='pinned-metadata-and-retained-backend-products',
                      generated_at=self.now.isoformat(),
                      metadata_binding='frozen-input-manifest' if self.expected_hashes is not None else 'exact-standalone-read',
                      metadata_inventory_sha256=inventory_sha,
                      backend_ids=sorted(self.backend_ids), visible_ids=sorted(visible),
                      confirmed_hidden_ids=sorted(self.hidden_ids),
                      confirmed_hidden_evidence=[self.markers[i] for i in sorted(self.hidden_ids) if i in self.markers],
                      known_unavailable_ids=sorted(self.markers),
                      known_unavailable_evidence=[self.markers[i] for i in sorted(self.markers)],
                      metadata_only_unavailable_total=len(set(self.markers) - self.backend_ids),
                      source_min_date=source_min_date, source_max_date=source_max_date,
                      counts=counts)
        if self.retained_exclusions is not None:
            # Retention is a conservative policy decision, not a current HTTP
            # status claim. Never manufacture a marker for a successful record.
            ledger['policy'] = 'current-negative-plus-retained-exclusions-v1'
            ledger['evidence_scope'] = 'current-pinned-metadata-backend-and-prior-exclusion-membership'
            ledger['retained_exclusion_binding'] = {k: v for k, v in self.retained_exclusions.items() if k not in ('ids', 'pending_ids')}
            ledger['retained_exclusion_ids'] = sorted(self.retained_ids)
            ledger['effective_exclusion_ids'] = sorted(self.excluded_ids())
            ledger['confirmed_hidden_ids'] = sorted(self.backend_ids & set(self.markers))
            ledger['confirmed_hidden_evidence'] = [self.markers[i] for i in sorted(self.backend_ids & set(self.markers))]
            ledger['retained_backend_ids'] = sorted(self.backend_ids & self.retained_ids)
            ledger['effective_hidden_backend_ids'] = sorted(self.hidden_ids)
            ledger['counts']['confirmed_hidden_total'] = len(self.backend_ids & set(self.markers))
            ledger['counts']['effective_hidden_total'] = len(self.hidden_ids)
            ledger['counts']['retained_exclusion_total'] = len(self.retained_ids)
            ledger['restoration_allowed'] = False
        if self.quarantine is not None:
            ledger['saved_conflict_quarantine'] = self.quarantine.finish()
            # A conflicting old marker is not a confirmed current availability decision.
            confirmed = (self.backend_ids & set(self.markers)) - self.quarantine.consumed
            ledger['confirmed_hidden_ids'] = sorted(confirmed)
            ledger['confirmed_hidden_evidence'] = [self.markers[i] for i in sorted(confirmed)]
            counts['confirmed_hidden_total'] = len(confirmed)
        if self.latest_negative_overlay is not None:
            ledger['latest_negative_overlay'] = self.latest_negative_overlay.binding()
        if self.latest_negative_overlay is not None and getattr(self.latest_negative_overlay, 'pending_metadata', None) is not None:
            counts['pending_metadata_total'] = len(self.pending_ids)
            ledger['pending_metadata_ids'] = sorted(self.pending_ids)
            ledger['pending_metadata_binding'] = self.latest_negative_overlay.pending_metadata
        raw = json_bytes(ledger)
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / 'visibility-ledger.json'
        path.write_bytes(raw)
        return dict(schema=1, **counts, source_min_date=source_min_date,
                    source_max_date=source_max_date,
                    ledger_sha256=hashlib.sha256(raw).hexdigest(),
                    metadata_inventory_sha256=inventory_sha)
