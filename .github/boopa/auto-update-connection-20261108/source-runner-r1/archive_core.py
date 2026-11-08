"""Offline immutable archive audit and isolated selected-source materialization.
No network or publication. No tarfile.extract/extractall is used.

Reconstruct every Git tree, inspect every metadata JSON, and publish local
outputs only after exact root/meta/framing checks pass.
"""
import argparse, gzip, hashlib, json, math, os, re, stat, tarfile, tempfile
from datetime import date
from pathlib import Path, PurePosixPath

COMMIT = '6126cf5baa0d04869b5e2a6b8fc0f0345df58756'
ROOT = '5cb10361859324844d3cd9d02257b2823aed57f1'
META = 'c81f29d9f31ec731016a7a5a7ee94626b9386360'
ADMIN = {'meta_state.json', 'recheck_state.json', 'request_budget.json'}
LIMIT_BYTES = 12 * 1024**3
LIMIT_FILE = 128 * 1024**2
LIMIT_META = 8 * 1024**2
LIMIT_MEMBERS = 600000
LIMIT_TAIL = 1024**2

def need(ok, message):
    if not ok: raise ValueError(message)

def sha(raw): return hashlib.sha256(raw).hexdigest()
def git(kind, raw): return hashlib.sha1(kind.encode()+b' '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
def encode(value): return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)+'\n').encode()
def strict(raw):
    def pairs(rows):
        out = {}
        for k,v in rows:
            need(k not in out, 'duplicate JSON key')
            out[k]=v
        return out
    def nonfinite(v): raise ValueError('nonfinite JSON')
    def finite_float(value):
        parsed=float(value);need(math.isfinite(parsed), 'overflow/nonfinite JSON number');return parsed
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite, parse_float=finite_float)

def classify(path, raw, as_of):
    parts=PurePosixPath(path).parts
    r=strict(raw)
    need(isinstance(r,dict), 'metadata object required: '+path)
    if len(parts)==2:
        need(parts[1] in ADMIN, 'unknown root metadata file')
        need('id' not in r and 'variations' not in r, 'root metadata contains product keys')
        return None, None
    need(len(parts)==3 and re.fullmatch(r'[1-9][0-9]*\.json',parts[2]) is not None,'invalid metadata path')
    ident=parts[2][:-5]
    need(parts[1]==ident[:3], 'metadata shard mismatch')
    if 'id' in r: need(r['id']==ident and isinstance(r['id'],str),'metadata id mismatch')
    flag=r.get('unavailable',False)
    need(type(flag) is bool,'invalid unavailable flag')
    marker=None
    if flag:
        status=r.get('status');need(type(status) is int and 100<=status<=599,'invalid HTTP status')
        if status in (404,410):
            need(r.get('id')==ident,'marker id required')
            d=r.get('fetched_at');need(isinstance(d,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',d) is not None,'invalid marker date')
            need(date.fromisoformat(d).isoformat()==d and date.fromisoformat(d)<=as_of,'future/noncanonical marker date')
            need(not r.get('name'),'negative marker has positive body')
            marker={'id':ident,'status':status,'fetched_at':d}
    else: need(r.get('status') not in (404,410),'conflicting flag/status')
    if r.get('name'): need(r.get('id')==ident,'positive metadata id required')
    return ident,marker

class Stream:
    def __init__(self, raw): self.raw=raw;self.count=0
    def read(self,n):
        need(0<=n<=LIMIT_META,'invalid read bound')
        data=self.raw.read(n);self.count+=len(data)
        need(self.count<=LIMIT_BYTES,'decompressed byte limit')
        return data
    def exact(self,n):
        data=self.read(n);need(len(data)==n,'short TAR block/payload');return data

def read_archive(stream, commit, expected_root, expected_meta, inventory, as_of, selected_root=None, selected_inventory=None):
    prefix='booth-vrc-price-tracker-'+commit
    trees={};seen=set();markers=[];product_ids=set();backend_ids=set();admin={};files=payload=members=0;pax=False
    selected_files=selected_bytes=0
    while True:
        block=stream.exact(512)
        if block==b'\0'*512:
            need(stream.exact(512)==b'\0'*512,'missing second TAR end block')
            tail=0
            while True:
                chunk=stream.read(min(65536,LIMIT_TAIL-tail+1))
                if not chunk: break
                tail+=len(chunk);need(tail<=LIMIT_TAIL and not any(chunk),'invalid/overbudget TAR tail')
            break
        ti=tarfile.TarInfo.frombuf(block,'utf-8','strict')
        members+=1;need(members<=LIMIT_MEMBERS,'member count limit')
        need(0<=ti.size<=LIMIT_FILE,'member payload limit')
        if ti.type==b'g':
            need(not pax and members==1 and ti.name=='pax_global_header' and ti.size<=1024,'unexpected PAX header')
            body=stream.exact(ti.size);pad=stream.exact((-ti.size)%512)
            need(not any(pad),'nonzero PAX padding')
            item=b'comment='+commit.encode()+b'\n';expected=str(len(item)+3).encode()+b' '+item
            need(body==expected,'unexpected PAX contents')
            pax=True;continue
        need(ti.type in (tarfile.REGTYPE,tarfile.AREGTYPE,tarfile.DIRTYPE),'links/special/extension records refused')
        name=ti.name.rstrip('/') if ti.isdir() else ti.name
        p=PurePosixPath(name)
        need(name and p.as_posix()==name and not p.is_absolute() and '\\' not in name and '\0' not in name and all(x not in ('','.', '..') for x in p.parts),'unsafe member path')
        need(p.parts[0]==prefix,'unexpected archive prefix')
        rel='/'.join(p.parts[1:]);need(rel not in seen,'duplicate archive member');seen.add(rel)
        if not rel:
            need(ti.isdir() and ti.size==0,'archive root must be directory');trees['']={};continue
        parent,_,leaf=rel.rpartition('/');need(parent in trees,'parent directory absent or file collision')
        if ti.isdir():
            need(ti.size==0 and rel not in trees,'invalid directory');trees[rel]={};continue
        need(leaf not in trees[parent],'duplicate tree entry')
        ismeta=rel.startswith('meta/')
        selected=ismeta or rel.startswith('data/')
        if selected:need(mode_from_tar(ti.mode)=='100644','executable source record')
        if rel.startswith('data/'):
            parts=PurePosixPath(rel).parts
            if len(parts)==2:
                need(parts[1] in {'.gitkeep','request_budget.json','collection_receipt.json','crawl_state.json'},'unknown data administration file')
                if parts[1]=='.gitkeep':need(ti.size==0,'nonempty .gitkeep')
            else:
                need(len(parts)==3 and re.fullmatch(r'[1-9][0-9]*\.json',parts[2]) is not None and parts[1]==parts[2][:-5][:3],'invalid backend product path')
                ident=parts[2][:-5];need(ident not in backend_ids,'duplicate backend ID');backend_ids.add(ident)
        if ismeta: need(ti.size<=LIMIT_META,'metadata size limit')
        h=hashlib.sha1(b'blob '+str(ti.size).encode()+b'\0');h256=hashlib.sha256();chunks=[];remain=ti.size
        out=None
        if selected and selected_root is not None:
            target=selected_root/rel;target.parent.mkdir(parents=True,exist_ok=True);out=target.open('xb')
        try:
            while remain:
                chunk=stream.exact(min(1024**2,remain));h.update(chunk);h256.update(chunk)
                if ismeta:chunks.append(chunk)
                if out is not None:out.write(chunk)
                remain-=len(chunk)
        finally:
            if out is not None:out.close()
        need(not any(stream.exact((-ti.size)%512)),'nonzero member padding')
        mode=mode_from_tar(ti.mode);oid=h.hexdigest();trees[parent][leaf]=(mode,oid)
        if selected:
            selected_files+=1;selected_bytes+=ti.size
            if selected_inventory is not None:selected_inventory.write(encode({'path':rel,'bytes':ti.size,'mode':mode,'git_blob':oid,'sha256':h256.hexdigest()}))
        files+=1;payload+=ti.size
        if ismeta:
            need(mode=='100644','executable metadata file')
            raw=b''.join(chunks);ident,marker=classify(rel,raw,as_of)
            row={'path':rel,'bytes':ti.size,'mode':mode,'git_blob':oid,'sha256':h256.hexdigest(),'id':ident,'negative':marker is not None}
            inventory.write(encode(row))
            if ident is not None:
                need(ident not in product_ids,'duplicate metadata product');product_ids.add(ident)
            else:admin[rel]=row
            if marker is not None:markers.append(marker|{'path':rel,'git_blob':oid,'sha256':h256.hexdigest(),'bytes':ti.size})
    need(pax,'Git archive commit comment required')
    oids={}
    for folder in sorted(trees,key=lambda x:(x.count('/'),len(x)),reverse=True):
        entries=trees[folder];need(entries or folder=='','empty non-Git directory')
        body=b''.join(mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(oid) for name,(mode,oid) in sorted(entries.items(),key=lambda kv:(kv[0]+('/' if kv[1][0]=='40000' else '')).encode()))
        oids[folder]=git('tree',body)
        if folder:
            parent,_,leaf=folder.rpartition('/');need(leaf not in trees[parent],'directory/file collision');trees[parent][leaf]=('40000',oids[folder])
    need(oids.get('')==expected_root,'archive Git root mismatch')
    need(oids.get('meta')==expected_meta,'archive metadata Git tree mismatch')
    need(set(admin)=={'meta/'+p for p in ADMIN},'metadata admin closure mismatch')
    return {'archive_files':files,'archive_payload_bytes':payload,'tar_headers':members,'decompressed_bytes':stream.count,'trailing_zero_bytes':tail,'git_tree_count':len(oids),'git_root':oids[''],'metadata_tree':oids['meta'],'metadata_product_count':len(product_ids),'metadata_file_count':len(product_ids)+len(admin),'negative_count':len(markers),'metadata_admin':admin,'selected_files':selected_files,'selected_bytes':selected_bytes,'backend_product_count':len(backend_ids),'backend_ids_sha256':sha(encode(sorted(backend_ids))),'_backend_ids':sorted(backend_ids)},sorted(product_ids),sorted(markers,key=lambda r:r['id'])

def mode_from_tar(mode):return '100755' if mode & 0o111 else '100644'

def file_digest(f):
    h=hashlib.sha256()
    for c in iter(lambda:f.read(1024**2),b''):h.update(c)
    return h.hexdigest()

def stable_stat(st):
    return (st.st_dev,st.st_ino,st.st_mode,st.st_nlink,st.st_size,st.st_mtime_ns,st.st_ctime_ns)

def run(archive, expected_sha, output, as_of):
    need(re.fullmatch('[0-9a-f]{64}',expected_sha) is not None,'external archive pin required')
    need(not output.exists() and not output.is_symlink(),'new output required')
    fd=os.open(archive,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f, tempfile.TemporaryDirectory(prefix='.negative-unaccepted-',dir=output.parent) as tmp:
        st=os.fstat(f.fileno());need(stat.S_ISREG(st.st_mode) and st.st_nlink==1,'single-link regular archive required')
        need(file_digest(f)==expected_sha,'archive pin mismatch');f.seek(0)
        stage=Path(tmp);selected=stage/'selected';selected.mkdir(mode=0o700)
        with gzip.GzipFile(fileobj=f,mode='rb') as gz,(stage/'metadata-inventory.jsonl').open('xb') as inv,(stage/'selected-inventory.jsonl').open('xb') as selected_inv:
            result,ids,markers=read_archive(Stream(gz),COMMIT,ROOT,META,inv,as_of,selected,selected_inv)
        f.seek(0);need(file_digest(f)==expected_sha and stable_stat(os.fstat(f.fileno()))==stable_stat(st),'archive changed during scan')
        for name,value in [('metadata-product-ids.private.json',ids),('current-negative-markers.private.json',markers),('backend-product-ids.private.json',result.pop('_backend_ids'))]: (stage/name).write_bytes(encode(value))
        output_pins={p.name:{'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())} for p in stage.iterdir() if p.is_file()}
        result.update(schema='boopa-rebuilt-saved-source-archive-v1',status='git-bound-source-materialized-semantic-preparation-pending',source_commit=COMMIT,archive_sha256=expected_sha,archive_bytes=st.st_size,as_of_date=as_of.isoformat(),outputs=output_pins,scanner_sha256=sha(Path(__file__).read_bytes()),source_prices_semantically_scanned=False,source_prices_substituted=False,publication_acceptance=False,raw_data_metadata_materialized=True,collection_completion_verified=False,whole_catalog_complete=False,price_source_is_latest=False,source_semantic_preparation_complete=False)
        (stage/'SOURCE-ARCHIVE-RECEIPT.json').write_bytes(encode(result))
        need(not output.exists(),'output appeared');stage.rename(output)
        return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--archive-sha256',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--as-of',type=date.fromisoformat,required=True);a=p.parse_args()
    print(json.dumps(run(a.archive,a.archive_sha256,a.output,a.as_of),sort_keys=True))
