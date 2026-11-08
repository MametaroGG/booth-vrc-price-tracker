#!/usr/bin/env python3
"""Render production pages from this candidate's lists; no import-time I/O.
Use build_site.py for the gated, recoverable end-to-end build.
"""
import argparse
import json
from pathlib import Path


def script_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')


def build(out, charts=None, bootstrap_enricher=None):
    import build_prototype as bp
    import build_sale as bs
    import build_pages_extra as bx
    out = Path(out)
    lists = json.loads((out / 'lists_full.json').read_text(encoding='utf-8'))
    # Published bootstrap sizes; never inline the multi-megabyte full catalog.
    # Every initial row/stat still comes from this candidate, not stale payloads.
    visibility = lists.get('visibility', {'schema': 1, 'hidden_ids': []})
    from visibility_contract import validate_public_visibility
    hidden = validate_public_visibility(visibility)
    payload = {'stats': lists['stats'], 'visibility': visibility}
    for name, cap in (('on_sale',12),('drops',10),('active',9),('newest',10)):
        payload[name] = lists.get(name,[])[:cap]
    if not isinstance(charts, list):
        raise ValueError('Explicit same-snapshot chart list required')
    # Explicit source charts remain validated upstream; hidden products must
    # never be resurrected by the separately supplied bootstrap chart input.
    payload['charts'] = [chart for chart in charts if str(chart.get('id')) not in hidden]
    if bootstrap_enricher is not None:
        payload = bootstrap_enricher(payload)
    payload_json = script_json(payload)
    if 'data:image' in payload_json:
        raise ValueError('Production payload must reference images, not embed them')
    html = bp.TEMPLATE.replace('/*__PAYLOAD__*/', payload_json)
    html = bp.add_index_diagnostics(html).replace('/*__BANNER__*/', 'banner.jpg?v=20251028-6')
    (out / 'index.html').write_text(html, encoding='utf-8')
    css = bp.TEMPLATE.split('<style>', 1)[1].split('</style>', 1)[0]
    sale = bs.SALE_TEMPLATE.replace('/*__CSS__*/', css).replace('/*__PAYLOAD__*/', payload_json)
    (out / 'sale.html').write_text(sale, encoding='utf-8')
    for name, fn in [('new', bx.build_newpg), ('free', bx.build_freepg), ('drops', bx.build_dropspg), ('updates', bx.build_updpg), ('bookmarks', bx.build_bookmarks), ('history', bx.build_history), ('ranking', bx.build_ranking)]:
        fn(out / (name + '.html'), css, payload_json)
    bx.build_risingpg(out / 'rising.html', out / 'active.html', css, payload_json)
    for name, fn in [('privacy', bx.build_privacy), ('terms', bx.build_terms), ('app', bx.build_app)]:
        page = out / (name + '.html')
        fn(page, css)
        # These shared-shell pages also expose search/navigation helpers. Bind
        # the same immutable visibility floor before any runtime code executes,
        # without adding product bodies to their otherwise empty bootstrap.
        text = page.read_text(encoding='utf-8')
        anchor = 'const P = {};'
        if text.count(anchor) != 1:
            raise ValueError('Informational page bootstrap anchor differs')
        text = text.replace(anchor, 'const P = ' + script_json({'stats': lists['stats'], 'visibility': visibility}) + ';', 1)
        page.write_text(text, encoding='utf-8')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--charts-file', type=Path, required=True)
    a = p.parse_args()
    build(a.output_dir, json.loads(a.charts_file.read_text()) if a.charts_file else None)


if __name__ == '__main__':
    main()
