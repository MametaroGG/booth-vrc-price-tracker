#!/usr/bin/env python3
"""Read-only full-input semantic audit for the new saved-snapshot candidate.

This is new execution evidence, never a replacement claim for missing old QA.
It does not authorize publication or certify source acquisition/browser results.
"""
import argparse
from collections import Counter
from datetime import date, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parents[1]/'rebuild-saved6126-20261108/current-generator-r1'
sys.path.insert(0, str(HERE.parent/'generator-r3'))
from verified_source import VerifiedSource, strict_json, open_directory, verify_artifact_directory
from visibility_policy import read_retained_exclusions

def require(value, message):
    if not value: raise ValueError(message)

def digest(raw): return hashlib.sha256(raw).hexdigest()

def encode(value): return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()

def average_check_status(sample_record, hidden):
    if sample_record is not None:return {'status':'PASS','id':'5826600'}
    return {'status':'NOT-APPLICABLE','reason':'sample-hidden' if '5826600' in hidden else 'sample-absent-or-no-history'}

def audit(source_root, completion_sha, candidate, prior, prior_sha, require_runtime_guard=False, quarantine_proof=None, latest_negative_proof=None, run_bindings_path=None, run_bindings_sha256=None):
    from saved_snapshot_policy import RunBindings
    require(run_bindings_path is not None and run_bindings_sha256 is not None,'Explicit r2 bindings required')
    bindings=RunBindings(run_bindings_path,run_bindings_sha256)
    require(prior_sha==bindings['retained_snapshot_sha256'],'Prior snapshot differs from run')
    site=Path(candidate);prior=Path(prior)
    snapshot_raw=(site/'snapshot-manifest.json').read_bytes();snapshot=strict_json(snapshot_raw)
    snapshot_sha=digest(snapshot_raw)
    require(snapshot_sha != prior_sha, 'New generation cannot inherit the prior snapshot identity')
    inventory={**snapshot['files'],'snapshot-manifest.json':snapshot_sha}
    fd=open_directory(site)
    try:verify_artifact_directory(fd,inventory)
    finally:os.close(fd)
    retained=read_retained_exclusions(prior,prior_sha)
    prior_manifest=strict_json((prior/'snapshot-manifest.json').read_bytes())
    require(set(snapshot['files'])==set(prior_manifest['files']),'Unexpected public file namespace: no raw/source exports allowed')
    lists=strict_json((site/'lists_full.json').read_bytes())
    hidden=set(lists['visibility']['hidden_ids'])
    rows={}
    for n in range(24):
        for row in strict_json((site/f'search_index_{n}.json').read_bytes()):
            require(isinstance(row,list) and len(row)==14 and row[0] not in rows, 'Search row shape or duplicate')
            rows[row[0]]=row
    before_source={};counts=Counter();metadata={};negative=set();markers={};backend=set()
    expected_stats={'total':0,'sale_now':0,'free_now':0,'changed':0,'min_date':None,'max_date':''}
    expected_members={'on_sale':set(),'free':set(),'active':set(),'newest':set(),'drops':set()}
    metrics={};sample=None;sample_record=None;variation_starts={}
    with VerifiedSource(source_root,completion_sha,run_bindings=bindings) as source:
        require(source.saved_snapshot_composition is not None,'Saved snapshot source contract required')
        from saved_snapshot_policy import Quarantine, LatestNegativeOverlay
        provenance=source.saved_snapshot_composition
        require(snapshot.get('saved_snapshot_composition')==dict(provenance),'Saved provenance differs')
        require(quarantine_proof is not None and latest_negative_proof is not None,'Pinned separate policy inputs required')
        quarantine=Quarantine(quarantine_proof,provenance['quarantine_proof_sha256'],retained,run_bindings=bindings)
        overlay=LatestNegativeOverlay(latest_negative_proof,provenance['latest_negative_overlay_sha256'],retained,run_bindings=bindings)
        require(snapshot.get('latest_negative_overlay')==overlay.binding(),'Latest overlay binding differs')
        require(snapshot.get('saved_conflict_quarantine')=={'proof_sha256':quarantine.pin,'ids':sorted(quarantine.entries),'availability_confirmed':False},'Quarantine binding differs')
        require(snapshot['input_manifest_sha256']==completion_sha,'Candidate/source commitment differs')
        require(snapshot.get('fixture') is source.manifest['fixture'],'Fixture/real scope differs')
        for key in ('collection_completion_verified','whole_catalog_complete','price_source_is_latest','deployed'):
            require(snapshot.get(key) is False,'False historical/publication flag changed: '+key)
        # Independently inspect each actual metadata record, including nonbackend IDs.
        for path in source.paths('tracker_meta'):
            raw=source.read_bytes(path);local=path.relative_to(source.root/'tracker_meta')
            if len(local.parts)!=2 or path.suffix!='.json':continue
            record=strict_json(raw);ident=path.stem
            require(ident not in metadata and record.get('id')==ident,'Metadata ID mismatch')
            is_negative=record.get('unavailable') is True and type(record.get('status')) is int and record['status'] in (404,410)
            if is_negative:
                negative.add(ident)
                require(date.fromisoformat(record['fetched_at']).isoformat()==record['fetched_at'],'Canonical marker date required')
                markers[ident]={'sha256':digest(raw),'status':record['status'],'fetched_at':record['fetched_at']}
            metadata[ident]={'name':record.get('name'), 'negative':is_negative,'likes':record.get('likes'),'likes_history':record.get('likes_history') or [],'image':record.get('image_resized') or record.get('image') or None,'shop':(record.get('shop') or {}).get('name') or None}
        require(hidden==retained['ids']|negative|overlay.ids,'Effective union is not exact floor plus source negatives plus latest overlay')
        for path in source.paths('data',products_only=True):
            raw_price=source.read_bytes(path);record=strict_json(raw_price);ident=record.get('id')
            require(ident==path.stem and ident not in backend,'Backend ID mismatch')
            backend.add(ident)
            variations=record.get('variations') or {}
            if ident in markers or ident in overlay.ids:
                require(type(record.get('variations')) is dict,'Negative source variation object required')
                total=after=0
                marker=markers.get(ident)
                for series in record['variations'].values():
                    require(type(series) is list,'Negative source series array required')
                    for observation in series:
                        require(type(observation) is dict,'Negative source observation object required')
                        stamp=observation.get('date');price=observation.get('price')
                        require(type(stamp) is str and date.fromisoformat(stamp).isoformat()==stamp,'Negative source canonical date required')
                        require(type(price) in (int,float) and math.isfinite(price) and price>=0,'Negative source finite nonnegative price required')
                        total+=1
                        if marker is not None and stamp>marker['fetched_at']:after+=1
                        if ident in overlay.ids:require(stamp<=overlay.entries[ident]['fetched_at'],'Saved observation newer than latest negative')
                if after:quarantine.check(record,raw_price,marker,total,after)
            variation_starts[ident]=sorted((min(p['date'] for p in v),k) for k,v in variations.items() if isinstance(v,list) and v)
            histories=[v for v in variations.values() if isinstance(v,list) and v]
            representative=max(histories,key=len) if histories else []
            ordered=sorted(representative,key=lambda p:p['date'])
            if ordered:
                first,last=ordered[0]['date'],ordered[-1]['date']
                expected_stats['min_date']=first if expected_stats['min_date'] is None else min(expected_stats['min_date'],first)
                expected_stats['max_date']=max(expected_stats['max_date'],last)
            if ident in hidden:
                require(ident not in rows,'Hidden item in search output')
                continue
            require(ident in rows,'Visible backend omitted from search')
            row=rows[ident];expected_stats['total']+=1
            require(row[1]==(metadata.get(ident,{}).get('name') or record.get('name','')),'Search name not from exact current metadata/fixed source')
            if not ordered:
                require(row[2:7]==[None,None,None,0,0],'Empty history price row differs')
                continue
            prices=[p['price'] for p in ordered]
            cur,base,low=prices[-1],max(prices),min(prices)
            sale=bool(ordered[-1].get('is_sale'))
            lowest=all(sorted(v,key=lambda p:p['date'])[-1]['price']==min(p['price'] for p in v) for v in histories)
            require(row[2:7]==[cur,base,low,int(sale),int(lowest)],'Fixed-source representative price/lowest semantics differ')
            changes=[ordered[i]['date'] for i in range(1,len(ordered)) if prices[i]!=prices[i-1]]
            expected_stats['sale_now']+=int(sale)
            expected_stats['free_now']+=int(cur==0 and base>=100)
            expected_stats['changed']+=int(bool(changes))
            last_change=None
            for i in range(len(ordered)-1,0,-1):
                    if prices[i]!=prices[i-1]:last_change=(ordered[i]['date'],prices[i-1],prices[i],bool(ordered[i].get('is_sale')));break
            metrics[ident]=(cur,base,low,sale,lowest,ordered[0]['date'],changes,last_change,ordered[-1]['date'],last_change[3] if last_change else False)
            if ident=='5826600':
                sample_record=record
                # Full recorded observations, before graph thinning. Independent
                # outlier classification mirrors the stated rule, not varutil.
                means={}
                for key,series in variations.items():
                    if not isinstance(series,list) or not series:continue
                    sorted_rows=sorted(series,key=lambda p:p['date']);positive=sorted((i for i,p in enumerate(sorted_rows) if p['price']>0),key=lambda i:sorted_rows[i]['price']);outliers=set()
                    for split in range(5,len(positive)):
                        if sorted_rows[positive[split]]['price']/sorted_rows[positive[split-1]]['price']>=20 and len({sorted_rows[i]['date'] for i in positive[:split]})>=5:
                            outliers.update(positive[split:]);break
                    if any(p['price']<1000000 for p in sorted_rows):outliers.update(i for i,p in enumerate(sorted_rows) if p['price']>=1000000)
                    ordinary=[p['price'] for i,p in enumerate(sorted_rows) if i not in outliers] or [p['price'] for p in sorted_rows]
                    means[key]={'sum':sum(ordinary),'count':len(ordinary)}
                sample={'id':ident,'variants_full_observation_statistics':means,'source_sha256':source.hashes[path.relative_to(source.root).as_posix()]}
        require(quarantine.finish()==snapshot['saved_conflict_quarantine'],'Actual quarantine consumption differs')
        require(set(rows)==backend-hidden,'Public search population is not exact visible backend')
        require(set(metadata)>=backend,'Backend lacks current metadata')
        day=date.fromisoformat(expected_stats['max_date']);w21=(day-timedelta(days=21)).isoformat();w30=(day-timedelta(days=30)).isoformat()
        list_fields={key:{} for key in expected_members}
        order={key:[] for key in expected_members}
        for ident,(cur,base,low,sale,lowest,first,changes,drop,last,sale_event) in metrics.items():
            if sale and cur<base and base>=500:expected_members['on_sale'].add(ident)
            if cur==0 and base>=100:expected_members['free'].add(ident)
            if any(d>=w21 for d in changes):expected_members['active'].add(ident)
            if first>=w30:expected_members['newest'].add(ident)
            if drop and drop[0]>=w21 and drop[2]<drop[1]:expected_members['drops'].add(ident)
            common={'cur':cur,'base':base,'lowest':low,'at_lowest':lowest}
            list_fields['on_sale'][ident]={**common,'pct':round((base-cur)/base*100) if base else 0,'date':last}
            list_fields['free'][ident]={**common,'cur':0,'pct':100,'at_lowest':True,'on_sale':sale,'date':last}
            list_fields['active'][ident]={**common,'on_sale':sale,'changes_recent':sum(d>=w21 for d in changes),'changes_total':len(changes),'first_date':first,'last_change':changes[-1] if changes else first}
            list_fields['newest'][ident]={**common,'on_sale':sale,'first_date':first}
            if drop:list_fields['drops'][ident]={'from':drop[1],'to':drop[2],'date':drop[0],'lowest':low,'at_lowest':drop[2]<=low,'on_sale':sale,'sale_event':sale_event}
        sorters={'on_sale':lambda i:(-list_fields['on_sale'][i]['pct'],-(metrics[i][1]-metrics[i][0])), 'free':lambda i:-metrics[i][1], 'active':lambda i:(-list_fields['active'][i]['changes_recent'],-len(metrics[i][6])), 'newest':lambda i:metrics[i][5], 'drops':lambda i:(metrics[i][7][0],metrics[i][7][1]-metrics[i][7][2])}
        for key,expected in expected_members.items():
            actual=[x['id'] for x in lists[key]]
            require(set(actual)==expected and len(actual)==len(expected),'List membership differs: '+key)
            for row in lists[key]:
                for field,value in list_fields[key][row['id']].items():
                    require(type(row.get(field)) is type(value) and row[field]==value,'List price/date/stat field differs: '+key+'/'+field)
            ordered_ids=sorted((ident for ident in metrics if ident in expected),key=sorters[key],reverse=key in ('newest','drops'))
            require(actual==ordered_ids,'List sort order differs: '+key)
        # The remaining curated lists are independently rederived rather than
        # accepted merely because their members are visible elsewhere.
        popular=[];rising=[];updates=[]
        for ident,(cur,base,low,sale,lowest,first,changes,drop,last,sale_event) in metrics.items():
            meta=metadata.get(ident,{})
            likes=meta.get('likes') or 0
            common={'cur':cur,'base':base,'lowest':low,'at_lowest':lowest,'on_sale':sale,'first_date':first}
            if likes>0 and base and base<=100000:popular.append((ident,common))
            if first>=w30 and likes>0:
                hist=sorted((h for h in meta.get('likes_history',[]) if h.get('date') and isinstance(h.get('count'),(int,float))),key=lambda h:h['date'])
                calculated=None
                if len(hist)>=2:
                    newest=hist[-1];target=(date.fromisoformat(newest['date'])-timedelta(days=7)).isoformat();oldest=hist[0]
                    for point in hist:
                        if point['date']<=target:oldest=point
                        else:break
                    span=(date.fromisoformat(newest['date'])-date.fromisoformat(oldest['date'])).days
                    if span>=2:calculated=(newest['count']-oldest['count'],(newest['count']-oldest['count'])/span)
                if calculated is None:calculated=(likes,likes/max(1,(day-date.fromisoformat(first)).days+1))
                gain,per_day=calculated
                if per_day>0:rising.append((ident,{**common,'gain':gain,'per_day':round(per_day,1)}))
            starts=variation_starts[ident]
            if (not base or base<=100000) and starts and starts[0][0]<w30:
                additions=sorted(((d,k) for d,k in starts if d>=w30),reverse=True)
                if additions:updates.append((ident,{**common,'added':[{'name':k,'date':d} for d,k in additions[:3]],'added_n':len(additions),'date':additions[0][0],'first_date':starts[0][0]}))
        popular.sort(key=lambda pair:-(metadata[pair[0]].get('likes') or 0));popular=popular[:300]
        rising.sort(key=lambda pair:(-pair[1]['per_day'],-(metadata[pair[0]].get('likes') or 0)))
        updates.sort(key=lambda pair:(pair[1]['date'],metadata[pair[0]].get('likes') or 0),reverse=True)
        seen_updates=set();deduplicated=[]
        for ident,fields in updates:
            key=(metadata[ident].get('shop'),fields['added'][0]['name'],fields['date'])
            if key not in seen_updates:seen_updates.add(key);deduplicated.append((ident,fields))
        updates=deduplicated[:120]
        for key,expected in [('popular',popular),('rising',rising),('updates',updates)]:
            require([r['id'] for r in lists[key]]==[i for i,_ in expected],'Curated list membership/order differs: '+key)
            for actual,(_,fields) in zip(lists[key],expected):
                for field,value in fields.items():require(type(actual.get(field)) is type(value) and actual[field]==value,'Curated list field differs: '+key+'/'+field)
        for key,values in lists.items():
            if not isinstance(values,list):continue
            for value in values:
                if not isinstance(value,dict) or 'id' not in value:continue
                ident=value['id'];require(ident in metrics,'Unexpected list product')
                meta=metadata[ident]
                require(value.get('name')==rows[ident][1] and value.get('image')==meta['image'] and value.get('shop')==meta['shop'],'List metadata differs from exact cutoff')
                if meta['likes'] is not None:require(value.get('likes')==meta['likes'],'List likes differ from exact cutoff')
        for key,value in expected_stats.items():require(lists['stats'][key]==value,'Aggregate statistic differs: '+key)
        require(lists['max_date']==expected_stats['max_date']==source.manifest['expected_date'],'Source date differs')
        daily=lists['stats']['price_changes']['daily']
        require(daily['status']=='unavailable' and daily['reason']=='missing-coverage' and daily['unique_products'] is None,'Historical data made a daily-completion claim')
        require(lists['stats']['price_changes']['cumulative']['unique_products']==expected_stats['changed'],'Cumulative statistic differs')
        counts.update(backend=len(backend),metadata_products=len(metadata),current_negative=len(negative),retained_floor=len(retained['ids']),effective_hidden=len(hidden),visible=len(rows),metadata_only_success=sum(1 for x in set(metadata)-backend if not metadata[x]['negative']),retained_now_not_negative=len(retained['ids']-negative))
        source.finish()
    # The previously approved relation assets are a narrow byte-identical
    # exception; IDs/relations are not new raw product-body exports.
    inherited={}
    for bundle in ('relation-bundle','relation-search-bundle','relation-supplement-bundle'):
        for path in (ASSETS/bundle).rglob('*'):
            if not path.is_file():continue
            name=path.relative_to(ASSETS/bundle).as_posix();sha=digest(path.read_bytes())
            require(snapshot['files'].get(name)==sha==prior_manifest['files'].get(name),'Inherited relation asset changed')
            inherited[name]=sha
    def no_hidden_body(obj):
        if isinstance(obj,dict):
            require(not ('id' in obj and str(obj['id']) in hidden),'Generated hidden product body')
            for key,value in obj.items():
                if key!='visibility':no_hidden_body(value)
        elif isinstance(obj,list):
            for value in obj:no_hidden_body(value)
    no_hidden_body(lists)
    for path in site.glob('shop_items_*.json'):
        obj=strict_json(path.read_bytes())
        require(all(str(row[0]) not in hidden for entries in obj.values() for row in entries),'Hidden item in shop index')
    # Verify actual emitted visibility program before executing its bounded
    # policy test. The VM has no network, filesystem or browser capabilities.
    prototype=(HERE.parent/'generator-r2/build_prototype.py').read_text()
    composition=snapshot.get('publication_composition')
    require(not require_runtime_guard or composition is not None,'Final publication runtime guard required')
    runtime_guard=None
    if composition is not None:
        require(composition.get('schema')=='boopa-new-runtime-composition-v1','Unsupported runtime composition')
        revision=composition['composition_id'];descriptor=composition['descriptor']
        require(digest(encode(descriptor))==revision and descriptor['prior_guard_snapshot_sha256']==prior_sha,'Runtime revision descriptor binding differs')
        require(descriptor['schema']=='boopa-saved-snapshot-runtime-assembly-r1','Runtime assembly version differs')
        require(descriptor['operator_sha256']==digest((HERE/'apply_runtime_guard_r2.py').read_bytes()),'Runtime assembler bytes changed')
        require(descriptor['source_input_manifest_sha256']==completion_sha,'Runtime/source input binding differs')
        require(lists.get('publication_revision')==revision,'Data/runtime revision differs')
        pin_names={'lists_full.json','shop_digest.json'}|{f'search_index_{i}.json' for i in range(24)}
        asset_pins={name:digest((site/name).read_bytes()) for name in sorted(pin_names)}
        require(composition['asset_pins']==asset_pins,'Runtime asset map differs')
        core=snapshot['catalog_core'];catalog_value=[revision,core['format'],core['rows'],core['part_rows'],[snapshot['files'][f'search-core/core_{i}.json'] for i in range(24)],[snapshot['files'][f'search-core/images_{i}.json'] for i in range(512)],[snapshot['files'][f'search_index_{i}.json'] for i in range(24)]]
        catalog_pin=digest(json.dumps(catalog_value,ensure_ascii=False,separators=(',',':')).encode())
        require(composition['catalog_pin']==catalog_pin,'Runtime catalog digest differs')
        prior_html=(prior/'index.html').read_text();previous_runtime=re.search(r'// PUBLICATION_RUNTIME_START:.*?// PUBLICATION_RUNTIME_END',prior_html,re.S).group(0)
        require(descriptor['prior_guard_bytes_sha256']==digest(previous_runtime.encode()),'Prior runtime template pin differs')
        runtime_guard=re.sub(r'const publicationAssetPins = Object.freeze\(\{.*?\}\);',lambda _: 'const publicationAssetPins = Object.freeze('+encode(asset_pins).decode()+');',previous_runtime,count=1)
        runtime_guard=re.sub(r"const publicationCatalogPin = '[0-9a-f]{64}';",lambda _: "const publicationCatalogPin = '"+catalog_pin+"';",runtime_guard,count=1)
        require(digest(runtime_guard.encode())==composition['runtime_guard_emitted_sha256'],'Emitted runtime hash differs')
        require((site/'catalog-cache.js').read_bytes()==(prior/'catalog-cache.js').read_bytes(),'Preserved guarded catalog reader differs')
        engine=(prior/'image-search-engine.js').read_text()
        require(engine.count('window.addEventListener("boopa:visibility",()=>{ lvRefreshCatalog(); });')==1,'Prior guarded image refresh listener differs')
        require((site/'image-search-engine.js').read_bytes()==engine.encode(),'Image runtime refresh delta differs')
        require(composition['image_engine_sha256']==digest(engine.encode()) and composition['image_visibility_refresh_added'] is True,'Image engine pin differs')
        require(snapshot['visibility_overlay']['final_image_search_engine_sha256']==snapshot['files']['image-search-engine.js']==digest(engine.encode()),'Final image metadata pin differs')
    average_result=None
    average_status=average_check_status(None,hidden)
    if sample_record is not None:
        html=(site/'index.html').read_text()
        start='function thinPointsJS(rows){';end='const DATA_BASE = '
        helpers=html[html.index(start):html.index(end)]
        expected_helpers=prototype[prototype.index(start):prototype.index(end)]
        require(helpers==expected_helpers,'Emitted average/variation helpers differ')
        start='function statsHTML(ser){';end='const DAYMS = '
        stats_helper=html[html.index(start):html.index(end)]
        require(stats_helper==prototype[prototype.index(start):prototype.index(end)],'Emitted average display helper differs')
        runner=r"""const fs=require('node:fs'),vm=require('node:vm');const x=JSON.parse(fs.readFileSync(0,'utf8'));const c={input:x.record,expected:x.expected,output:null,historyObservationLabel:()=> 'observation',esc:String,LANG:'ja',yen:n=>String(n),tr:k=>k};vm.createContext(c);vm.runInContext(x.helpers+'\n'+x.stats+'\nconst variants=thinVarsJS(input); output=Object.fromEntries(Object.entries(variants).map(([key,v])=>{if(JSON.stringify(v.average_source)!==JSON.stringify(expected[key]))throw Error(\"average source mismatch\");const rounded=Math.round(v.average_source.sum/v.average_source.count);const rendered=statsHTML(v);if(!rendered.includes(\"pp_avg</div><div class=\\\"v\\\">\"+rounded+\"</div>\"))throw Error(\"average display mismatch\");const missing={...v};delete missing.average_source;if(!statsHTML(missing).includes(\"pp_avg</div><div class=\\\"v\\\">—</div>\"))throw Error(\"sample-only average invented\");return [key,{sum:v.average_source.sum,count:v.average_source.count,rounded,display_verified:true}];}));',c);console.log(JSON.stringify(c.output));"""
        result=subprocess.run(['node','-e',runner],input=json.dumps({'record':sample_record,'expected':sample['variants_full_observation_statistics'],'helpers':helpers,'stats':stats_helper}),capture_output=True,text=True,timeout=20,check=True)
        average_result=json.loads(result.stdout)
        average_status=average_check_status(sample_record,hidden)
    canonical=re.search(r'VISIBILITY_JS = r"""\n(.*?)\n"""',prototype,re.S).group(1)
    if runtime_guard is not None:canonical=canonical.replace('  const out = {...(data || {})};\n','  const out = {...(data || {})};\n  out.stats = publicationStats; out.visibility = publicationVisibility; out.publication_revision = publicationRevision;\n')
    if runtime_guard is not None:canonical=canonical.replace(".ritem,.hthumb,.capcard');",".ritem,.hthumb,.capcard,.image-result');")
    runtime_pages=[];bootstrap_records=0
    for path in sorted(site.glob('*.html')):
        html=path.read_text();match=re.search(r'// VISIBILITY_POLICY_START:.*?// VISIBILITY_POLICY_END',html,re.S)
        if not match:continue
        require(match[0]==canonical,'Visibility runtime differs from reviewed generator')
        if runtime_guard is not None:
            match_guard=re.findall(r'// PUBLICATION_RUNTIME_START:.*?// PUBLICATION_RUNTIME_END',html,re.S)
            require(match_guard==[runtime_guard],'Final publication guard differs: '+path.name)
        p=re.search(r'(?:^|\n)(?:<script>)?const P\s*=\s*',html)
        require(p is not None,'Missing page bootstrap')
        payload,_=json.JSONDecoder().raw_decode(html[p.end():])
        require(set(payload['visibility']['hidden_ids'])==hidden,'Page bootstrap exclusion union differs')
        expected_page_stats={'max_date':lists['stats']['max_date']} if path.name=='image-search.html' and runtime_guard is None else lists['stats']
        require(payload.get('stats')==expected_page_stats,'Page bootstrap statistics differ: '+path.name)
        if runtime_guard is not None:require(payload.get('publication_revision')==revision,'Page revision differs')
        if runtime_guard is not None and path.name in ('index.html','item.html','image-search.html'):
            require(html.count('image-search-engine.js?v='+composition['image_engine_sha256'])==1,'Image runtime import binding differs')
        no_hidden_body(payload);bootstrap_records+=sum(len(v) for v in payload.values() if isinstance(v,list));runtime_pages.append(path.name)
    require(len(runtime_pages)==15,'Expected 15 visibility-bearing runtime pages')
    hidden_probe=next(iter(sorted(hidden)));visible_probe=next(iter(sorted(rows)))
    script='''const vm=require('node:vm');const p=JSON.parse(process.argv[1]);const code=process.argv[2];const c={P:{visibility:{schema:1,hidden_ids:[p.hidden]},stats:{max_date:'2026-11-05',total:123,sale_now:7}},window:{dispatchEvent(){}},CustomEvent:function(){},document:{querySelectorAll(){return []}},Date:class extends Date{static now(){return Date.parse('2026-11-07T00:00:00Z')}}};vm.createContext(c);vm.runInContext(code,c);const v=c.window.BoopaVisibility;if(!v.isHidden(p.hidden))throw Error('lost floor');v.acceptMeta(p.hidden,{id:p.hidden,name:'success'});if(!v.isHidden(p.hidden))throw Error('restoration');v.acceptMeta(p.visible,{id:p.visible,unavailable:true,status:404,fetched_at:'2026-11-06'});if(!v.isHidden(p.visible)||c.P.stats.total!==123||c.P.stats.sale_now!==7)throw Error('runtime union or frozen stats');if(v.filter([{id:p.hidden},{id:p.visible},{id:'999999999999'}]).length!==1)throw Error('runtime filter');console.log('PASS');'''
    # The old policy-only test remains separate from the guarded runtime test;
    # its variables are supplied rather than weakening the emitted code.
    policy_test_code=("const publicationStats=P.stats, publicationVisibility=P.visibility, publicationRevision='synthetic';\n" if runtime_guard is not None else '')+canonical
    run=subprocess.run(['node','-e',script,json.dumps({'hidden':hidden_probe,'visible':visible_probe}),policy_test_code],capture_output=True,text=True,timeout=20,check=True)
    require(run.stdout.strip()=='PASS','Runtime policy probe did not pass')
    fd=open_directory(site)
    try:verify_artifact_directory(fd,inventory)
    finally:os.close(fd)
    require(read_retained_exclusions(prior,prior_sha)==retained,'Prior candidate changed')
    return {'schema':'boopa-new-saved-semantic-audit-r1','status':'passed-declared-semantic-scope','fixture':snapshot['fixture'],'candidate_snapshot_sha256':snapshot_sha,'completion_sha256':completion_sha,'script_sha256':digest(Path(__file__).read_bytes()),'counts':dict(counts),'statistics':expected_stats,'checks':['exact_final_output_closure','source_per_read_hashes_and_final_inventory','exact_source_negative_plus_prior_floor_plus_latest_overlay_union','no_retained_success_reclassified_as_current_negative','exact_quarantine_actual_price_metadata_counts_and_consumption','latest_negative_vs_saved_history_consistency','all_backend_search_prices_against_fixed_source','representative_variation_and_lowest_semantics','five_complete_list_populations_prices_dates_and_order','three_curated_list_populations_fields_and_order','all_list_metadata_against_exact_cutoff','aggregate_statistics_from_source','daily_unavailable_no_completion_claim','all_15_initial_page_unions','all_15_actual_runtime_programs','runtime_addition_no_restoration_and_frozen_stats','generated_list_shop_bootstrap_exclusion','89_inherited_relation_assets_exact_prior_bytes','prior_pin_unchanged'],'runtime_guard_bound':runtime_guard is not None,'runtime_pages':runtime_pages,'inherited_asset_count':len(inherited),'sample_5826600_check':average_status,'sample_5826600_source_averages':sample,'sample_5826600_emitted_js_and_display_averages':average_result,'full_legacy_17_supplement_reproduced':False,'browser_qa_accepted':False,'authenticated_transport_verified':False,'publication_eligible':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--completion-sha256',required=True);p.add_argument('--candidate',required=True);p.add_argument('--prior',required=True);p.add_argument('--prior-sha256',required=True);p.add_argument('--output',required=True);p.add_argument('--require-runtime-guard',action='store_true');p.add_argument('--quarantine-proof',required=True);p.add_argument('--latest-negative-proof',required=True);p.add_argument('--run-bindings',required=True);p.add_argument('--run-bindings-sha256',required=True);a=p.parse_args()
    result=audit(a.source,a.completion_sha256,a.candidate,a.prior,a.prior_sha256,a.require_runtime_guard,a.quarantine_proof,a.latest_negative_proof,a.run_bindings,a.run_bindings_sha256)
    with open(a.output,'x') as f:json.dump(result,f,sort_keys=True,indent=2);f.write('\n')
    print(json.dumps({'status':result['status'],'candidate_snapshot_sha256':result['candidate_snapshot_sha256'],'counts':result['counts']},sort_keys=True))
