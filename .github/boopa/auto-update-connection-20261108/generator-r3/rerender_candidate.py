#!/usr/bin/env python3
"""Offline UI rerender of an exact, fully verified existing raw-build candidate.
Does not collect/rebuild raw data, publish, change cron, or overwrite a candidate.
The supplied source manifest SHA is a required external trust anchor.
"""
import argparse
from datetime import date
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile

from build_site import HERE, BASELINE, STATICS, load_trusted, rename_new_directory
from static_assets import STATIC_HASHES

DATA_FILES = ({f'{prefix}_{i}.json' for prefix in ('search_index','shop_items') for i in range(24)}
              | {f'relations_children_{i}.json' for i in range(8)}
              | {'lists_full.json','shop_digest.json','cat_cards.json'})
PAGES = {name+'.html' for name in ('index','item','sale','new','free','drops','updates','rising','active','bookmarks','history','ranking','privacy','terms','app')}


def digest(data):return hashlib.sha256(data).hexdigest()

def parse_json(data):
    def invalid(value):raise ValueError('Non-finite JSON constant: '+value)
    def pairs(items):
        out={}
        for k,v in items:
            if k in out:raise ValueError('Duplicate JSON key: '+k)
            out[k]=v
        return out
    return json.loads(data,parse_constant=invalid,object_pairs_hook=pairs)


def canonical_id(value):
    return isinstance(value,str) and re.fullmatch('[1-9][0-9]*',value) is not None


def validate_variations(variations):
    if not isinstance(variations,dict) or not variations:raise ValueError('Nonempty variations object required')
    for name,series in variations.items():
        if not isinstance(name,str):raise ValueError('Variation name must be a string')
        rows=series.get('p') if isinstance(series,dict) else series
        if not isinstance(rows,list) or not rows:raise ValueError('Nonempty variation rows required')
        previous=''
        for row in rows:
            if not isinstance(row,list) or len(row) not in (3,4):raise ValueError('Invalid variation row shape')
            day,price,sale=row[:3]
            if not isinstance(day,str) or date.fromisoformat(day).isoformat()!=day or day<previous:raise ValueError('Invalid variation date/order')
            if type(price) not in (int,float) or not math.isfinite(price) or price<0 or type(sale) is not int or sale not in (0,1):raise ValueError('Invalid variation price/sale')
            if len(row)==4 and (type(row[3]) is not int or row[3] not in (0,1)):raise ValueError('Invalid outlier flag')
            previous=day
        if isinstance(series,dict):
            if type(series.get('d')) is not int or series['d']<len(rows) or type(series.get('sd')) is not int or not 0<=series['sd']<=series['d']:
                raise ValueError('Invalid variation observation counts')
            if 'average_source' in series:
                a=series['average_source']
                if not isinstance(a,dict) or set(a)!={'sum','count'} or type(a['sum']) not in (int,float) or not math.isfinite(a['sum']) or not 0<=a['sum']<=9007199254740991 or type(a['count']) is not int or not 0<a['count']<=min(series['d'],9007199254740991):
                    raise ValueError('Invalid variation average statistics')


def validate_payload(index_html, lists, ids, fixture, chart_visibility=None):
    # Parse data only. Never eval, import, run scripts, or execute the source HTML.
    matches=re.findall(r'^const P = (.*);$',index_html,re.M)
    if len(matches)!=1:raise ValueError('Expected exactly one canonical JSON bootstrap assignment')
    payload=parse_json(matches[0])
    expected_keys={'stats','on_sale','drops','active','newest','charts'} | ({'visibility'} if 'visibility' in lists else set())
    if not isinstance(payload,dict) or set(payload)!=expected_keys:
        raise ValueError('Unexpected bootstrap schema')
    if 'visibility' in lists:
        from visibility_contract import validate_public_visibility
        hidden=validate_public_visibility(lists['visibility'])
        if payload.get('visibility')!=lists['visibility'] or hidden & ids:raise ValueError('Bootstrap visibility differs from public catalog')
    if payload['stats']!=lists.get('stats'):raise ValueError('Bootstrap stats differ from source lists')
    for name,cap in (('on_sale',12),('drops',10),('active',9),('newest',10)):
        records=payload[name];expected=lists.get(name,[])[:cap]
        if not isinstance(records,list) or len(records)!=len(expected):raise ValueError('Bootstrap count differs: '+name)
        for record,wanted in zip(records,expected):
            if not isinstance(record,dict) or {k:v for k,v in record.items() if k!='vars'}!=wanted:
                raise ValueError('Bootstrap record differs from source lists: '+name)
            if 'vars' in record:validate_variations(record['vars'])
    charts=payload['charts']
    if not isinstance(charts,list):raise ValueError('Invalid production charts')
    if chart_visibility is not None:
        proof=chart_visibility
        if not isinstance(proof,dict) or set(proof)!={'schema','input_chart_ids','hidden_chart_ids','visible_chart_ids','input_charts_sha256'} or type(proof['schema']) is not int or proof['schema']!=1:raise ValueError('Invalid chart visibility proof')
        for key in ('input_chart_ids','hidden_chart_ids','visible_chart_ids'):
            seq=proof[key]
            if not isinstance(seq,list) or any(not canonical_id(x) for x in seq) or len(seq)!=len(set(seq)):raise ValueError('Invalid chart visibility IDs')
        if not re.fullmatch('[0-9a-f]{64}',proof['input_charts_sha256']):raise ValueError('Invalid input chart digest')
        denied=validate_public_visibility(lists.get('visibility'))
        if proof['hidden_chart_ids']!=[x for x in proof['input_chart_ids'] if x in denied] or proof['visible_chart_ids']!=[x for x in proof['input_chart_ids'] if x not in denied] or proof['visible_chart_ids']!=[x.get('id') for x in charts]:raise ValueError('Chart visibility partition mismatch')
    if not charts and not fixture and not (chart_visibility and chart_visibility['input_chart_ids'] and chart_visibility['hidden_chart_ids']==chart_visibility['input_chart_ids']):raise ValueError('Invalid/empty production charts')
    seen=set()
    for chart in charts:
        if not isinstance(chart,dict) or not canonical_id(chart.get('id')) or chart['id'] not in ids or chart['id'] in seen:
            raise ValueError('Invalid, duplicate, or unknown chart ID')
        if not isinstance(chart.get('name'),str) or not chart['name']:raise ValueError('Chart name required')
        validate_variations(chart.get('variations'));seen.add(chart['id'])
    return payload


def verify_source(source, expected_manifest_sha, allow_fixture=False, *, _derived_static_hashes=None):
    source=Path(source).resolve();manifest_path=source/'snapshot-manifest.json'
    if not re.fullmatch('[0-9a-f]{64}',expected_manifest_sha):raise ValueError('Exact source manifest SHA256 required')
    if manifest_path.is_symlink():raise ValueError('Source manifest symlink forbidden')
    raw=manifest_path.read_bytes()
    if digest(raw)!=expected_manifest_sha:raise ValueError('Source manifest SHA does not match external pin')
    m=parse_json(raw)
    if m.get('schema')!=1 or m.get('status')!='validated-candidate' or m.get('baseline_commit')!=BASELINE or m.get('deployed') is not False:
        raise ValueError('Source must be an undeployed validated candidate')
    if type(m.get('fixture')) is not bool or (m['fixture'] and not allow_fixture):raise ValueError('Fixture source is not authorized')
    if m.get('collection_completion')!='producer-attested-not-independently-verified' or not m.get('collection_id'):
        raise ValueError('Raw producer provenance missing')
    if not re.fullmatch('[0-9a-f]{64}',m.get('input_manifest_sha256','')) or not isinstance(m.get('input_inventory'),dict):
        raise ValueError('Raw input integrity commitment missing')
    inventory=m['input_inventory']
    if type(inventory.get('files')) is not int or inventory['files']<1 or not re.fullmatch('[0-9a-f]{64}',inventory.get('sha256','')):
        raise ValueError('Invalid raw inventory commitment')
    if not m.get('validation',{}).get('ok'):raise ValueError('Source validation was not successful')
    files=m.get('files');required=DATA_FILES|PAGES|set(STATICS)
    if not isinstance(files,dict) or required-set(files):raise ValueError('Source manifest missing required data/pages/static assets')
    actual=set()
    for p in source.rglob('*'):
        if p.is_symlink():raise ValueError('Source symlinks forbidden')
        if p.is_file():actual.add(p.relative_to(source).as_posix())
    if actual!=set(files)|{'snapshot-manifest.json'}:raise ValueError('Source inventory differs from manifest')
    for name,expected in files.items():
        relative=PurePosixPath(name);path=source/name
        if relative.is_absolute() or '..' in relative.parts or str(relative)!=name or source not in path.resolve().parents:
            raise ValueError('Unsafe source manifest path')
        if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected) or digest(path.read_bytes())!=expected:
            raise ValueError('Source file integrity mismatch: '+name)
    # No source code is executed. Only approved pinned static code can be copied.
    static_pins = dict(STATIC_HASHES if _derived_static_hashes is None else _derived_static_hashes)
    visibility_lists=parse_json((source/'lists_full.json').read_bytes())
    if 'visibility' in visibility_lists and _derived_static_hashes is None:
        from visibility_overlay import derived_static_hashes
        static_pins.update(derived_static_hashes(visibility_lists['visibility'],visibility_lists.get('stats',{}).get('max_date')))
    if set(static_pins) != set(STATIC_HASHES):raise ValueError('Derived static pin inventory mismatch')
    if any(files[name]!=expected for name,expected in static_pins.items()):raise ValueError('Source static files differ from trusted pins')
    def read_verified(name):
        data=(source/name).read_bytes()
        if digest(data)!=files[name]:raise ValueError('Source changed while reading: '+name)
        return data
    lists=parse_json(read_verified('lists_full.json'));ids=set();rows_count=0
    for i in range(24):
        rows=parse_json(read_verified(f'search_index_{i}.json'))
        if not isinstance(rows,list):raise ValueError('Search shard must be an array')
        for row in rows:
            if not isinstance(row,list) or len(row)!=14 or not canonical_id(row[0]) or row[0] in ids:raise ValueError('Invalid/duplicate search row')
            ids.add(row[0]);rows_count+=1
    if rows_count!=lists.get('stats',{}).get('total') or rows_count!=m['validation'].get('rows') or rows_count!=m['validation'].get('unique_ids'):
        raise ValueError('Source catalog count mismatch')
    if lists.get('max_date')!=lists.get('stats',{}).get('max_date') or lists.get('max_date')!=m['validation'].get('max_date'):
        raise ValueError('Source date mismatch')
    load_trusted('validate_search_core').validate(source,m,required=True)
    payload=validate_payload(read_verified('index.html').decode('utf-8'),lists,ids,m['fixture'],m.get('chart_visibility'))
    return m,raw,payload


def rerender(source, expected_manifest_sha, output, relations_bundle=None, relations_approval=None, allow_fixture=False, relation_search_bundle=None, relation_search_approval=None, supplement_bundle=None, supplement_approval=None, *, current_price_projection=None, projection_raw_records=None, presentation_proof=None, presentation_sha256=None, _projection_clock=None):
    import build_prod,build_item
    from preserve_relations import preserve,activate_hook,strip_relation_imports
    source=Path(source).resolve();output=Path(output).resolve()
    if output==source or source in output.parents:raise ValueError('Output/staging must be outside immutable source candidate')
    if output.exists() or output.is_symlink():raise FileExistsError(output)
    derived_statics = None
    if (source/'current-price-projection.json').exists():
        if current_price_projection is None or projection_raw_records is None:
            raise ValueError('Projection source requires explicit proof and frozen raw records')
        from rerender_projection import prepare_context
        derived_statics, current_price_projection = prepare_context(source, current_price_projection, projection_raw_records, presentation_proof, presentation_sha256, expected_manifest_sha=expected_manifest_sha, _clock=_projection_clock)
    elif current_price_projection is not None:
        raise ValueError('Cannot add a projection during UI-only rerender')
    m,manifest_bytes,payload=verify_source(source,expected_manifest_sha,allow_fixture,_derived_static_hashes=derived_statics)
    if bool(m.get('presentation_proof_sha256')) != (presentation_proof is not None) or m.get('presentation_proof_sha256') != presentation_sha256:
        raise ValueError('Exact source presentation proof is required')
    if presentation_proof is not None:
        from current_price_projection import digest as canonical_digest
        if canonical_digest(presentation_proof) != presentation_sha256:raise ValueError('Presentation proof digest mismatch')
    if bool(relations_bundle)!=bool(relations_approval):raise ValueError('Complete relation bundle and approval required together')
    if not m['fixture'] and not relations_bundle:raise ValueError('Production UI rerender must preserve explicitly approved public relations')
    if any(name.startswith('relation-supplement/') or name=='relationship-supplement.js' for name in m['files']) and not supplement_bundle:
        raise ValueError('Source supplement requires explicit approved preservation bundle')
    output.parent.mkdir(parents=True,exist_ok=True)
    run=Path(tempfile.mkdtemp(prefix='.'+output.name+'-rerender-',dir=output.parent));candidate=run/'site';candidate.mkdir()
    (run/'source-snapshot-manifest.json').write_bytes(manifest_bytes)
    try:
        for name,expected in m['files'].items():
            # Replace only these known UI namespaces as complete approved bundles.
            if name.startswith(('relation-data/','relation-search/','relation-supplement/','search-core/')) or name in ('relationship-data.js','relationship-ui-draft.js','relationship-search.js','relationship-supplement.js'):
                continue
            data=(source/name).read_bytes()
            if digest(data)!=expected:raise ValueError('Source changed while staging: '+name)
            target=candidate/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        has_visibility='visibility' in payload
        if derived_statics is not None or has_visibility:
            from rerender_projection import reset_static
            reset_static(candidate)
        build_prod.build(candidate,payload['charts'],lambda _:payload)
        relation_status='withdrawn';index=candidate/'index.html'
        if relations_bundle:
            relation_status=preserve(relations_bundle,relations_approval,candidate)
            if not m['fixture'] and not relation_status.get('activate'):raise ValueError('Production rerender cannot withdraw already-public relation UI')
            index.write_text(activate_hook(index.read_text(),relation_status))
        else:index.write_text(strip_relation_imports(index.read_text()))
        from preserve_relation_search import configure
        search_status=configure(candidate,relation_search_bundle,relation_search_approval,relation_status)
        from preserve_relation_supplement import configure as configure_supplement
        supplement_status=configure_supplement(candidate,supplement_bundle,supplement_approval,relation_status)
        subprocess.run(['node',str(candidate/'scripts/embed-hero.cjs')],check=True,cwd=candidate,timeout=60)
        (candidate/'item.html').write_text(build_item.build_item(index.read_text()))
        for name in DATA_FILES:
            if digest((candidate/name).read_bytes())!=m['files'][name]:raise ValueError('Data changed in UI-only rerender: '+name)
        core=load_trusted('build-search-core').build(candidate,write_report=False)['catalog_core']
        if has_visibility:
            from visibility_overlay import apply_image_visibility
            visibility_overlay=apply_image_visibility(candidate)
        # Display-only guard must run after derived pages, before validation/hashing.
        load_trusted('guard_discount_display').main(candidate)
        projection_status = None
        if presentation_proof is not None:
            from projection_integration import apply_presentation
            apply_presentation(candidate,presentation_proof,presentation_sha256)
        if current_price_projection is not None:
            from projection_integration import finalize_projection
            projection_status=finalize_projection(candidate,current_price_projection,_clock=_projection_clock)
            if digest((candidate/'current-price-projection.json').read_bytes())!=m['files']['current-price-projection.json']:
                raise ValueError('Projection payload changed during UI-only rerender')
        if has_visibility:visibility_overlay['final_image_search_engine_sha256']=digest((candidate/'image-search-engine.js').read_bytes())
        validation=load_trusted('validate_snapshot').validate(candidate,m['validation']['max_date'])
        if not validation['ok']:raise ValueError('Rerender validation failed: '+json.dumps(validation))
        files={p.relative_to(candidate).as_posix():digest(p.read_bytes()) for p in sorted(candidate.rglob('*')) if p.is_file()}
        result={k:m[k] for k in ('schema','baseline_commit','collection_id','fixture','collection_completion','input_manifest_sha256','input_inventory','compact')}
        result.update(catalog_core=core,status='validated-candidate',files=files,validation=validation,deployed=False,relations=relation_status,relation_search=search_status,relation_supplement=supplement_status,
                      build_mode='verified-data-rerender',raw_rebuild_performed=False,
                      source_candidate_manifest_sha256=expected_manifest_sha,
                      raw_provenance_note='Inherited exact verified source candidate; no new collection or raw rebuild claimed')
        if has_visibility:
            result['visibility']=m.get('visibility')
            result['visibility_overlay']=visibility_overlay
            result['chart_visibility']=m.get('chart_visibility')
        if projection_status is not None:result['current_price_projection']=projection_status
        if presentation_proof is not None:result['presentation_proof_sha256']=presentation_sha256
        manifest=candidate/'snapshot-manifest.json';manifest.write_text(json.dumps(result,indent=2)+'\n')
        final=load_trusted('validate_snapshot').validate(candidate,validation['max_date'],manifest)
        if not final['ok']:raise ValueError('Final manifest gate failed: '+json.dumps(final))
        rename_new_directory(candidate,output)
        (run/'SUCCESS.json').write_text(json.dumps({'candidate':str(output),'source_manifest_sha256':expected_manifest_sha,'raw_rebuild_performed':False}))
        return result
    except Exception as exc:
        (run/'FAILED.txt').write_text(str(exc)+'\n')
        raise RuntimeError(f'Rerender failed; private work retained at {run}: {exc}') from exc


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-candidate',type=Path,required=True);p.add_argument('--expected-source-manifest-sha256',required=True)
    p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--relations-bundle',type=Path);p.add_argument('--relations-approval',type=Path)
    p.add_argument('--allow-fixture',action='store_true')
    p.add_argument('--relation-search-bundle',type=Path);p.add_argument('--relation-search-approval',type=Path)
    p.add_argument('--supplement-bundle',type=Path);p.add_argument('--supplement-approval',type=Path)
    a=p.parse_args();result=rerender(a.source_candidate,a.expected_source_manifest_sha256,a.output_dir,a.relations_bundle,a.relations_approval,a.allow_fixture,a.relation_search_bundle,a.relation_search_approval,a.supplement_bundle,a.supplement_approval)
    print(json.dumps({'status':result['status'],'rows':result['validation']['rows'],'raw_rebuild_performed':False,'output':str(a.output_dir)},indent=2))
