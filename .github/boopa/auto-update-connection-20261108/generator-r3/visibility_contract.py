"""Read-only public-output consistency for the separately captured visibility ledger."""
import hashlib
import json
import re
from pathlib import Path

ID = re.compile(r'[1-9][0-9]*\Z')

def validate_public_visibility(value):
    if not isinstance(value, dict) or set(value) != {'schema', 'hidden_ids'} or type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError('Invalid public visibility schema')
    ids = value['hidden_ids']
    if not isinstance(ids, list) or any(not isinstance(x, str) or not ID.fullmatch(x) for x in ids) or len(set(ids)) != len(ids):
        raise ValueError('Invalid/duplicate hidden IDs')
    return set(ids)

def verify_visibility_output(site, ledger_path, summary, frozen_root, input_hashes, verified_source=None, retained_candidate=None, retained_snapshot_sha256=None, quarantine=None, latest_negative_overlay=None):
    site, ledger_path = Path(site), Path(ledger_path)
    raw = ledger_path.read_bytes()
    ledger = json.loads(raw)
    if not isinstance(summary, dict) or summary.get('ledger_sha256') != hashlib.sha256(raw).hexdigest():
        raise ValueError('Visibility evidence digest mismatch')
    from datetime import datetime, date, timedelta, timezone
    from visibility_policy import strict_json, json_bytes, read_retained_exclusions
    if (retained_candidate is None) != (retained_snapshot_sha256 is None):
        raise ValueError('Prior candidate and its external pin required together')
    retained = None if retained_candidate is None else read_retained_exclusions(retained_candidate, retained_snapshot_sha256)
    retained_ids = set() if retained is None else set(retained['ids'])
    quarantine = None if quarantine is None else quarantine.fresh()
    overlay_ids = set() if latest_negative_overlay is None else set(latest_negative_overlay.ids)
    expected_policy = 'last-known-http-unavailable-v1' if retained is None else 'current-negative-plus-retained-exclusions-v1'
    if type(ledger.get('schema')) is not int or ledger.get('schema') != 1 or type(summary.get('schema')) is not int or summary.get('schema') != 1 or ledger.get('policy') != expected_policy or ledger.get('metadata_binding') != 'frozen-input-manifest':
        raise ValueError('Unbound visibility ledger schema')
    for key in ('backend_ids','visible_ids','confirmed_hidden_ids','known_unavailable_ids'):
        seq=ledger.get(key)
        if not isinstance(seq,list) or any(not isinstance(x,str) or not ID.fullmatch(x) for x in seq) or len(seq)!=len(set(seq)):
            raise ValueError('Invalid visibility ledger ID set: '+key)
    frozen_root=Path(frozen_root)
    if not isinstance(input_hashes,dict):raise ValueError('Pinned input hash map required')
    meta_hashes={k:v for k,v in input_hashes.items() if k.startswith('tracker_meta/')}
    generated=datetime.fromisoformat(ledger['generated_at'])
    if generated.tzinfo is None or generated>datetime.now(timezone.utc):raise ValueError('Invalid visibility evidence time')
    day=generated.astimezone(timezone(timedelta(hours=9))).date()
    expected_markers={}; backend_source=set(); minimum=None; maximum=''
    actual_meta=set();actual_data=set()
    for directory in ('tracker_meta','data'):
        paths = verified_source.paths(directory) if verified_source else (frozen_root/directory).rglob('*')
        for path in paths:
            if not verified_source and path.is_symlink():raise ValueError('Linked visibility source')
            if not verified_source and not path.is_file():continue
            rel=path.relative_to(frozen_root).as_posix();raw_input=verified_source.read_bytes(path) if verified_source else path.read_bytes()
            if hashlib.sha256(raw_input).hexdigest()!=input_hashes.get(rel):raise ValueError('Visibility source hash mismatch: '+rel)
            (actual_meta if directory=='tracker_meta' else actual_data).add(rel)
            local=path.relative_to(frozen_root/directory)
            if len(local.parts)!=2 or path.suffix!='.json':continue
            record=strict_json(raw_input);ident=path.stem
            if directory=='tracker_meta':
                if record.get('unavailable') is True and type(record.get('status')) is int and record['status'] in (404,410):
                    stamp=record.get('fetched_at')
                    if record.get('id')!=ident or not ID.fullmatch(ident) or record.get('name') or not isinstance(stamp,str) or date.fromisoformat(stamp).isoformat()!=stamp or date.fromisoformat(stamp)>day:
                        raise ValueError('Invalid independent unavailable evidence')
                    expected_markers[ident]={'id':ident,'path':rel,'sha256':input_hashes[rel],'status':record['status'],'fetched_at':stamp}
            else:
                if record.get('id')!=ident or not ID.fullmatch(ident) or ident in backend_source:raise ValueError('Invalid independent backend ID')
                backend_source.add(ident)
                series=[v for v in (record.get('variations') or {}).values() if isinstance(v,list) and v]
                if series:
                    rep=max(series,key=len);first=min(x['date'] for x in rep);last=max(x['date'] for x in rep)
                    minimum=first if minimum is None else min(minimum,first);maximum=max(maximum,last)
                # Metadata is traversed first; positive observations newer than
                # the withdrawal marker must not be silently suppressed.
                marker=expected_markers.get(ident)
                overlay=None if latest_negative_overlay is None else latest_negative_overlay.entries.get(ident)
                if marker is not None or quarantine is not None or overlay is not None:
                    import math
                    from visibility_policy import canonical_date
                    variations=record.get('variations')
                    if not isinstance(variations,dict):raise ValueError('Invalid independent history')
                    total=after=overlay_after=0
                    for key,observations in variations.items():
                        if not isinstance(key,str) or not isinstance(observations,list):raise ValueError('Invalid independent variations')
                        for observation in observations:
                            if not isinstance(observation,dict):raise ValueError('Invalid independent observation')
                            observed=canonical_date(observation.get('date'))
                            price=observation.get('price')
                            if type(price) not in (int,float) or not math.isfinite(price) or price<0:raise ValueError('Invalid independent price')
                            if quarantine is not None and observed>day:raise ValueError('Future independent observation')
                            total+=1
                            after+=int(marker is not None and observed.isoformat()>marker['fetched_at'])
                            overlay_after+=int(overlay is not None and observed.isoformat()>overlay['fetched_at'])
                    if overlay is not None and (canonical_date(overlay['fetched_at'])>day or overlay_after):raise ValueError('Independent latest negative conflict')
                    if after:
                        if quarantine is None:raise ValueError('Conflicting independent source history')
                        quarantine.check(record,raw_input,marker,total,after)
    if actual_meta!=set(meta_hashes) or actual_data!={k for k in input_hashes if k.startswith('data/')}:
        raise ValueError('Visibility frozen source inventory differs')
    quarantined=set() if quarantine is None else set(quarantine.consumed)
    if quarantine is not None and ledger.get('saved_conflict_quarantine')!=quarantine.finish():raise ValueError('Quarantine ledger differs')
    if latest_negative_overlay is not None and ledger.get('latest_negative_overlay')!=latest_negative_overlay.binding():raise ValueError('Latest negative binding differs')
    source_hidden=(backend_source & set(expected_markers)) - quarantined
    effective_exclusions = set(expected_markers) | retained_ids | overlay_ids
    effective_hidden = backend_source & effective_exclusions
    if set(ledger['backend_ids'])!=backend_source or set(ledger['known_unavailable_ids'])!=set(expected_markers) or set(ledger['confirmed_hidden_ids'])!=source_hidden:
        raise ValueError('Visibility source/ledger IDs differ')
    if ledger.get('known_unavailable_evidence') != [expected_markers[x] for x in sorted(expected_markers)] or ledger.get('confirmed_hidden_evidence') != [expected_markers[x] for x in sorted(source_hidden)]:
        raise ValueError('Visibility source/ledger evidence differs')
    counts={'backend_total':len(backend_source),'visible_total':len(backend_source-effective_hidden),'confirmed_hidden_total':len(source_hidden)}
    if retained is not None:
        if (ledger.get('evidence_scope') != 'current-pinned-metadata-backend-and-prior-exclusion-membership' or
                ledger.get('retained_exclusion_binding') != {k:v for k,v in retained.items() if k != 'ids'} or
                ledger.get('retained_exclusion_ids') != sorted(retained_ids) or
                ledger.get('effective_exclusion_ids') != sorted(effective_exclusions) or
                ledger.get('retained_backend_ids') != sorted(backend_source & retained_ids) or
                ledger.get('effective_hidden_backend_ids') != sorted(effective_hidden) or
                ledger.get('restoration_allowed') is not False):
            raise ValueError('Retained exclusion lineage or effective union differs')
        counts['effective_hidden_total'] = len(effective_hidden)
        counts['retained_exclusion_total'] = len(retained_ids)
    if type(ledger.get('metadata_only_unavailable_total')) is not int or ledger['metadata_only_unavailable_total'] != len(set(expected_markers) - backend_source):
        raise ValueError('Metadata-only unavailable count differs')
    inventory_sha=hashlib.sha256(json_bytes(meta_hashes)).hexdigest()
    for obj in (ledger,summary):
        if obj.get('source_min_date')!=minimum or obj.get('source_max_date')!=maximum or obj.get('metadata_inventory_sha256')!=inventory_sha:
            raise ValueError('Visibility source date/inventory summary differs')
    if ledger.get('counts')!=counts or any(type(summary.get(k)) is not int or summary.get(k)!=v for k,v in counts.items()):raise ValueError('Visibility summary counts differ')
    lists = json.loads((site / 'lists_full.json').read_text())
    hidden = validate_public_visibility(lists.get('visibility'))
    backend = set(ledger['backend_ids']); visible = set(ledger['visible_ids'])
    backend_hidden=effective_hidden
    if hidden != effective_exclusions or backend_hidden != hidden & backend or visible != backend - backend_hidden or visible & hidden or visible | backend_hidden != backend:
        raise ValueError('Visibility population partition mismatch')
    rows = []
    for i in range(24):
        rows.extend(json.loads((site / f'search_index_{i}.json').read_text()))
    actual = [r[0] for r in rows]
    if set(actual) != visible or len(actual) != len(visible) or lists['stats']['total'] != len(visible):
        raise ValueError('Public search/count differs from visibility evidence')
    def check_records(value):
        if isinstance(value, dict):
            if 'id' in value and str(value['id']) in hidden:
                raise ValueError('Hidden product leaked into public list')
            for k, v in value.items():
                if k != 'visibility': check_records(v)
        elif isinstance(value, list):
            for v in value: check_records(v)
    check_records(lists)
    for path in site.glob('shop_items_*.json'):
        obj = json.loads(path.read_text())
        if any(str(row[0]) in hidden for products in obj.values() for row in products):
            raise ValueError('Hidden product leaked into shop index')
    return dict(summary, public_population_verified=True)
