"""Pure local prototype; consumes a pinned current-SKU snapshot, never mutates raw."""
from datetime import datetime

SUPPORTED = {'official_scoped_promotion', 'variant_discount_badge'}
def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))

def select_price(snapshot, evidence, legacy_variant_id=None):
    observed = stamp(snapshot['observed_at'])
    rows = [v for v in snapshot['variants'] if v.get('active') is True]
    ids = [v['id'] for v in rows]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate current variant ID')
    for v in rows:
        if type(v['price']) is not int or v['price'] < 0:
            raise ValueError('invalid price')
    verified = []
    for order, v in enumerate(rows):
        matches = [e for e in evidence if e.get('item_id') == snapshot['item_id']
            and e.get('variant_id') == v['id']
            and e.get('snapshot_id') == snapshot['snapshot_id']
            and e.get('price') == v['price']
            and e.get('kind') in SUPPORTED
            and e.get('review_status') == 'verified'
            and e.get('source_content_sha256')
            and stamp(e['valid_from']) <= observed <= stamp(e['valid_through'])]
        if matches:
            verified.append((v['price'], order, v['id'], v, matches[0]))
    if verified:
        _, _, _, row, proof = min(verified, key=lambda p: p[:3])
        reason, sale = 'verified_sale_lowest_current_price', True
    else:
        row = next((v for v in rows if v['id'] == legacy_variant_id), rows[0] if rows else None)
        proof, reason, sale = None, 'no_verified_sale_preserve_active_legacy', None
    free_ids = [v['id'] for v in rows if v['price'] == 0]
    return {
        'schema': 1, 'item_id': snapshot['item_id'], 'snapshot_id': snapshot['snapshot_id'],
        'selected_variant_id': row['id'] if row else None,
        'selected_variant_name': row['name'] if row else None,
        'selected_price': row['price'] if row else None,
        'selected_sale': sale, 'selected_sale_evidence_id': proof['evidence_id'] if proof else None,
        'selection_reason': reason, 'selection_observed_at': snapshot['observed_at'],
        'free_variant_ids': free_ids, 'free_coverage_complete': snapshot['current_variants_complete'],
        'raw_history_changed': False,
    }
