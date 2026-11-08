#!/usr/bin/env python3
"""New exact-input assembler preserving the prior candidate's runtime guard.

Never changes the base or prior candidate, publishes, or inherits old QA success.
The old emitted guard is a pinned code input, not a provenance/authority receipt.
"""
import argparse,hashlib,json,os,re,secrets,ctypes,errno,stat
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'generator-r3'))
from verified_source import open_directory,exact_read,verify_artifact_directory,strict_json

def sha(raw):return hashlib.sha256(raw).hexdigest()
def enc(obj):return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def need(value,msg):
    if not value:raise ValueError(msg)
def replace(text,old,new,count=1):
    need(text.count(old)==count,'Runtime preimage occurrence mismatch: '+old[:60])
    return text.replace(old,new)

def read_candidate(path,pin):
    fd=open_directory(path)
    try:
        raw=exact_read(fd,'snapshot-manifest.json',128*1024**2)
        need(sha(raw)==pin,'Candidate manifest pin mismatch')
        manifest=strict_json(raw);inventory={**manifest['files'],'snapshot-manifest.json':pin}
        verify_artifact_directory(fd,inventory)
        blobs={name:exact_read(fd,name,128*1024**2) for name in inventory}
        need(all(sha(blobs[name])==digest for name,digest in inventory.items()),'Candidate changed during immutable capture')
        verify_artifact_directory(fd,inventory)
        return manifest,blobs
    finally:os.close(fd)

def same_parent(fd,path):
    fresh=open_directory(path)
    try:
        a,b=os.fstat(fd),os.fstat(fresh)
        need((a.st_dev,a.st_ino)==(b.st_dev,b.st_ino),'Output parent identity changed')
    finally:os.close(fresh)

def rename_at_new(parent_fd,source,target):
    libc=ctypes.CDLL(None,use_errno=True);rename=getattr(libc,'renameat2',None)
    if rename is None:raise OSError(errno.ENOTSUP,'Atomic no-replace rename unavailable')
    rename.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];rename.restype=ctypes.c_int
    if rename(parent_fd,os.fsencode(source),parent_fd,os.fsencode(target),1):
        code=ctypes.get_errno();raise OSError(code,'No-replace promotion failed')

def write_exact_new(parent_fd,temp_name,blobs):
    os.mkdir(temp_name,0o700,dir_fd=parent_fd)
    root_fd=os.open(temp_name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent_fd)
    try:
        for name,raw in blobs.items():
            parts=name.split('/')
            need(all(p and p not in ('.','..') for p in parts),'Unsafe candidate member')
            fd=os.dup(root_fd)
            try:
                for part in parts[:-1]:
                    try:os.mkdir(part,0o700,dir_fd=fd)
                    except FileExistsError:pass
                    child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                    os.close(fd);fd=child
                target=os.open(parts[-1],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
                try:
                    view=memoryview(raw)
                    while view:
                        written=os.write(target,view);need(written>0,'Incomplete candidate write');view=view[written:]
                finally:os.close(target)
            finally:os.close(fd)
        verify_artifact_directory(root_fd,{name:sha(raw) for name,raw in blobs.items()})
    finally:os.close(root_fd)

def assemble_directory(dest,blobs):
    # The parent descriptor remains open across creation, all member writes,
    # exact verification, and no-replace promotion. No writes use ancestor paths.
    parent_fd=open_directory(dest.parent)
    temp_name='.'+dest.name+'-unaccepted-'+secrets.token_hex(12)
    try:
        same_parent(parent_fd,dest.parent)
        write_exact_new(parent_fd,temp_name,blobs)
        same_parent(parent_fd,dest.parent)
        rename_at_new(parent_fd,temp_name,dest.name)
        same_parent(parent_fd,dest.parent)
        fd=os.open(dest.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent_fd)
        try:verify_artifact_directory(fd,{name:sha(raw) for name,raw in blobs.items()})
        finally:os.close(fd)
    finally:os.close(parent_fd)
    # Any interrupted tree stays explicitly unaccepted under its original held
    # directory. Never recursively delete a possibly attacker-replaced pathname.

def run(base,base_pin,prior,prior_pin,dest):
    base,prior,dest=map(lambda p:Path(p).absolute(),(base,prior,dest))
    need(not dest.exists() and not dest.is_symlink(),'New output required')
    need(all(dest!=p and dest not in p.parents and p not in dest.parents for p in (base,prior)),'Output must be disjoint')
    snapshot,blobs=read_candidate(base,base_pin);old,old_blobs=read_candidate(prior,prior_pin)
    need(set(snapshot['files'])==set(old['files']),'Unexpected public namespace')
    original=dict(blobs)
    old_index=old_blobs['index.html'].decode()
    matches=re.findall(r'// PUBLICATION_RUNTIME_START:.*?// PUBLICATION_RUNTIME_END',old_index,re.S)
    need(len(matches)==1,'Exact prior runtime required')
    prior_runtime=matches[0]
    old_pin_match=re.findall(r'const publicationAssetPins = Object.freeze\((\{.*?\})\);',prior_runtime)
    need(len(old_pin_match)==1,'Prior asset map required')
    old_pins=strict_json(old_pin_match[0]);names={'lists_full.json','shop_digest.json'}|{f'search_index_{i}.json' for i in range(24)}
    need(set(old_pins)==names and all(old['files'][n]==h for n,h in old_pins.items()),'Prior runtime asset pin disagreement')
    descriptor={'schema':'boopa-saved-snapshot-runtime-assembly-r1','base_snapshot_sha256':base_pin,'prior_guard_snapshot_sha256':prior_pin,'prior_guard_bytes_sha256':sha(prior_runtime.encode()),'operator_sha256':sha(Path(__file__).read_bytes()),'source_input_manifest_sha256':snapshot['input_manifest_sha256']}
    revision=sha(enc(descriptor))
    lists=strict_json(blobs['lists_full.json']);lists['publication_revision']=revision;blobs['lists_full.json']=enc(lists)
    asset_pins={name:sha(blobs[name]) for name in sorted(names)}
    core=snapshot['catalog_core']
    catalog_value=[revision,core['format'],core['rows'],core['part_rows'],[sha(blobs[f'search-core/core_{i}.json']) for i in range(24)],[sha(blobs[f'search-core/images_{i}.json']) for i in range(512)],[sha(blobs[f'search_index_{i}.json']) for i in range(24)]]
    catalog_pin=sha(json.dumps(catalog_value,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode())
    runtime=replace(prior_runtime,'const publicationAssetPins = Object.freeze('+old_pin_match[0]+');','const publicationAssetPins = Object.freeze('+enc(asset_pins).decode()+');')
    catalog_matches=re.findall(r"const publicationCatalogPin = '[0-9a-f]{64}';",runtime)
    need(len(catalog_matches)==1,'Prior catalog pin required')
    runtime=replace(runtime,catalog_matches[0],"const publicationCatalogPin = '"+catalog_pin+"';")
    # The previously emitted reader already closes the unverified fallback and
    # checks both artifact revision and hidden IDs before and after image reads.
    cache=old_blobs['catalog-cache.js'];need(b"createCatalogReader.publicationContractVersion='boopa-publication-reader-v1'" in cache,'Prior reader contract missing')
    blobs['catalog-cache.js']=cache;cache_version=sha(cache)[:16]
    engine=blobs['image-search-engine.js'].decode()
    engine=replace(engine,'function initImageLens(){\n','function initImageLens(){\nwindow.addEventListener("boopa:visibility",()=>{ lvRefreshCatalog(); });\n')
    need(engine.encode()==old_blobs['image-search-engine.js'],'Rebuilt image runtime differs from exact prior guarded engine')
    blobs['image-search-engine.js']=engine.encode();engine_version=sha(blobs['image-search-engine.js'])
    pages=[];replacements={}
    for name,raw in list(blobs.items()):
        if not name.endswith('.html'):continue
        text=raw.decode()
        if '// VISIBILITY_POLICY_START:' not in text:continue
        need('// PUBLICATION_RUNTIME_START:' not in text,'Base already has a publication runtime')
        match=re.search(r'(?:^|\n)(?:<script>)?const P\s*=\s*',text);need(match is not None,'Missing initial bootstrap')
        payload,end=json.JSONDecoder().raw_decode(text[match.end():]);need(text[match.end()+end:match.end()+end+1]==';','Unexpected bootstrap terminator')
        payload['stats']=lists['stats'];payload['visibility']=lists['visibility'];payload['publication_revision']=revision
        encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
        text=text[:match.end()]+encoded+text[match.end()+end:]
        anchor="// VISIBILITY_POLICY_START: immutable build exclusions; additive runtime confirmations only."
        text=replace(text,anchor,runtime+'\n'+anchor)
        text=replace(text,'  const out = {...(data || {})};\n','  const out = {...(data || {})};\n  out.stats = publicationStats; out.visibility = publicationVisibility; out.publication_revision = publicationRevision;\n')
        text=replace(text,".ritem,.hthumb,.capcard');",".ritem,.hthumb,.capcard,.image-result');")
        transforms=[
            ('function renderStats(st){\n','function renderStats(st){\n  st = publicationStats;\n'),
            ("const spCatalogReader=typeof createBoopaCatalogReader==='function'?", "const spCatalogReader=typeof createBoopaCatalogReader==='function'&&createBoopaCatalogReader.publicationContractVersion==='boopa-publication-reader-v1'?"),
            ("fetch('search_index_'+i+'.json?v=20251027-2',{signal:controller.signal,cache:'no-store'}).then(r=>{if(!r.ok)throw new Error('catalog');return r.json();})", "publicationReadJSON('search_index_'+i+'.json',{signal:controller.signal})"),
            ('fetch("shop_digest.json?v=20251025-6").then(r => r.ok ? r.json() : {})','publicationReadJSON("shop_digest.json")'),
            ('fetch("lists_full.json?v=20251025-6").then(r => { if (!r.ok) throw new Error("lists"); return r.json(); })','publicationReadJSON("lists_full.json")'),
            ('try { const r = await fetch("lists_full.json"); if (r.ok) return filterVisibleLists(await r.json()); } catch {}','try { return filterVisibleLists(await publicationReadJSON("lists_full.json")); } catch {}')]
        counts=[]
        for before,after in transforms:
            count=text.count(before);need(count in (0,1),'Ambiguous runtime fetch preimage');counts.append(count)
            if count:text=replace(text,before,after)
        text=re.sub(r'catalog-cache\.js\?v=[0-9a-f]+','catalog-cache.js?v='+cache_version,text)
        text=re.sub(r'image-search-engine\.js\?v=[0-9a-f]+','image-search-engine.js?v='+engine_version,text)
        blobs[name]=text.encode();pages.append(name);replacements[name]=counts
    need(len(pages)==15,'Expected all 15 runtime pages')
    # Counts are taken from real prior guarded page roles, not inferred from a
    # page title. Every newly produced guarded fetch line must match that role.
    signatures=['function renderStats(st){\n  st = publicationStats;',"createBoopaCatalogReader.publicationContractVersion==='boopa-publication-reader-v1'","publicationReadJSON('search_index_'+i+'.json'",'publicationReadJSON("shop_digest.json")','publicationReadJSON("lists_full.json").then','return filterVisibleLists(await publicationReadJSON("lists_full.json"))']
    for name in pages:
        text=blobs[name].decode();previous=old_blobs[name].decode()
        for signature in signatures:need(text.count(signature)==previous.count(signature),'Guarded fetch role differs from prior: '+name)
    snapshot['publication_composition']={'schema':'boopa-new-runtime-composition-v1','composition_id':revision,'composition_id_algorithm':'sha256-canonical-new-runtime-inputs-v1','descriptor':descriptor,'runtime_guard_template_sha256':sha(prior_runtime.encode()),'runtime_guard_emitted_sha256':sha(runtime.encode()),'asset_pins':asset_pins,'catalog_pin':catalog_pin,'runtime_pages':sorted(pages),'image_engine_sha256':engine_version,'image_visibility_refresh_added':True,'base_candidate_snapshot_sha256':base_pin,'prior_guard_snapshot_sha256':prior_pin,'independent_qa_accepted':False,'publication_authorized':False}
    snapshot['visibility_overlay']['final_image_search_engine_sha256']=engine_version
    snapshot['files']={name:sha(raw) for name,raw in sorted(blobs.items()) if name!='snapshot-manifest.json'}
    blobs['snapshot-manifest.json']=(json.dumps(snapshot,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode();final_pin=sha(blobs['snapshot-manifest.json'])
    # Capture is immutable, and originals are checked again before exposure.
    _,again=read_candidate(base,base_pin);need(again==original,'Base candidate changed')
    _,again=read_candidate(prior,prior_pin);need(again==old_blobs,'Prior candidate changed')
    assemble_directory(dest,blobs)
    return {'schema':'boopa-saved-snapshot-runtime-assembly-result-r1','status':'assembled-awaiting-independent-final-qa','candidate_snapshot_sha256':final_pin,'composition_id':revision,'candidate_files':len(blobs),'changed_files':sorted(name for name in blobs if blobs[name]!=original[name]),'guarded_runtime_pages':sorted(pages),'replacements':replacements,'source_base_snapshot_sha256':base_pin,'prior_guard_snapshot_sha256':prior_pin,'publication_eligible':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',required=True);p.add_argument('--base-sha256',required=True);p.add_argument('--prior',required=True);p.add_argument('--prior-sha256',required=True);p.add_argument('--dest',required=True);p.add_argument('--receipt',required=True);a=p.parse_args()
    result=run(a.base,a.base_sha256,a.prior,a.prior_sha256,a.dest)
    with open(a.receipt,'x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps(result,sort_keys=True))
