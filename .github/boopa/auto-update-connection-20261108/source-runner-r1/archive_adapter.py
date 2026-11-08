"""Dynamic fixed-Git archive read adapter. Import performs no network I/O.
Provider/current-main/publication authentication belongs to the acquisition caller.
"""
import gzip, hashlib, http.client, importlib.util, json, os, re, stat, tempfile, time
from datetime import date
from pathlib import Path

CORE = Path(__file__).with_name('archive_core.py')
CORE_SHA = 'daf2d7402f6c5bdb43465de4336629f50a8ebde0a8c007fdc3a2be23933323b0'
MAX_ARCHIVE = 1024**3
MAX_IDENTITY = 2*1024**2
REPO = 'MametaroGG/booth-vrc-price-tracker'

def need(ok,msg):
    if not ok: raise ValueError('Archive adapter: '+msg)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encode(v):return (json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
def oid(x,n=40):return type(x) is str and re.fullmatch('[0-9a-f]{'+str(n)+'}',x) is not None
def hash_file(path):
    with open(path,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def core():
    need(hash_file(CORE)==CORE_SHA,'frozen archive core changed')
    spec=importlib.util.spec_from_file_location('runner_archive_core',CORE)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

def pinned_json(path,pin):
    need(oid(pin,64),'external JSON pin required')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:
        st=os.fstat(f.fileno());need(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_size<=MAX_IDENTITY,'bounded single-link JSON required')
        raw=f.read(MAX_IDENTITY+1);need(sha(raw)==pin,'JSON pin mismatch')
        return core().strict(raw)

def verify_identity(path,pin):
    """Rehash immutable Git membership evidence, NOT its provider authenticity."""
    path=Path(path);p=pinned_json(path,pin)
    need(type(p) is dict and set(p)=={'schema','commit','root_tree','metadata_tree','data_tree','commit_response','root_response'},'closed source identity proof')
    need(p['schema']=='boopa-git-source-identity-r1' and all(oid(p[k]) for k in ('commit','root_tree','metadata_tree','data_tree')),'source identity values')
    responses=[]
    for name in ('commit_response','root_response'):
        r=p[name];need(type(r) is dict and set(r)=={'path','sha256'},'closed response pin')
        need(type(r['path']) is str and r['path'],'response path')
        target=Path(r['path']);target=target if target.is_absolute() else path.parent/target
        responses.append(pinned_json(target,r['sha256']))
    c,t=responses
    need(type(c) is dict and c.get('sha')==p['commit'] and c.get('tree',{}).get('sha')==p['root_tree'],'commit to root mismatch')
    need(type(t) is dict and t.get('sha')==p['root_tree'] and t.get('truncated') is False and type(t.get('tree')) is list,'complete root tree required')
    rows={}
    for r in t['tree']:
        need(type(r) is dict and {'path','mode','type','sha'}<=set(r),'Git root entry shape')
        n=r['path'];m=r['mode'];o=r['sha'];typ=r['type']
        need(type(n) is str and n and n not in ('.','..') and '/' not in n and '\\' not in n and '\0' not in n and n not in rows,'root leaf name')
        need(m in ('040000','100644','100755','120000','160000') and oid(o),'root mode/OID')
        need(typ=={'040000':'tree','100644':'blob','100755':'blob','120000':'blob','160000':'commit'}[m],'root type/mode')
        rows[n]=(m.lstrip('0'),o)
    body=b''.join(m.encode()+b' '+n.encode()+b'\0'+bytes.fromhex(o) for n,(m,o) in sorted(rows.items(),key=lambda item:(item[0]+('/' if item[1][0]=='40000' else '')).encode()))
    need(core().git('tree',body)==p['root_tree'],'root tree Git hash mismatch')
    need(rows.get('meta')==('40000',p['metadata_tree']) and rows.get('data')==('40000',p['data_tree']),'root namespaces differ')
    return p

class OfficialResponse:
    def __init__(self,commit):
        self.conn=http.client.HTTPSConnection('codeload.github.com',timeout=30)
        try:
            self.conn.request('GET','/'+REPO+'/tar.gz/'+commit,headers={'Accept-Encoding':'identity','User-Agent':'boopa-source-runner-r1'})
            self.response=self.conn.getresponse();self.status=self.response.status
            pairs=self.response.getheaders();self.headers={}
            for k,v in pairs:
                k=k.lower();need(k not in self.headers,'duplicate download header');self.headers[k]=v
        except BaseException:
            self.conn.close();raise
    def read(self,n):return self.response.read(n)
    def close(self):self.conn.close()

def download_official(commit,output,opener=None,clock=time.monotonic):
    """One official GET; no redirects, retries, token/env lookup or alternate route."""
    need(oid(commit),'fixed commit required');output=Path(output)
    need(not output.exists() and not output.is_symlink(),'new download destination required')
    response=None;start=clock()
    try:
        response=(opener or OfficialResponse)(commit)
        need(response.status==200,'download status differs; stop without retry')
        h=response.headers;need(type(h) is dict and h.get('content-encoding','identity')=='identity','encoded download')
        length=h.get('content-length')
        if length is not None:need(type(length) is str and length.isascii() and length.isdigit() and 0<int(length)<=MAX_ARCHIVE,'download content-length')
        with tempfile.NamedTemporaryFile(prefix='.archive-unaccepted-',dir=output.parent,delete=False) as f:
            temporary=Path(f.name);digest=hashlib.sha256();size=0
            try:
                while True:
                    need(clock()-start<=600,'download elapsed limit')
                    chunk=response.read(min(1024**2,MAX_ARCHIVE-size+1))
                    need(type(chunk) is bytes,'download chunk type')
                    if not chunk:break
                    size+=len(chunk);need(size<=MAX_ARCHIVE,'compressed archive limit');f.write(chunk);digest.update(chunk)
                need(size>0 and (length is None or size==int(length)),'empty/truncated download')
                f.flush();os.fsync(f.fileno());need(not output.exists() and not output.is_symlink(),'download destination appeared')
                # A hard link atomically installs without replacing an existing destination.
                os.link(temporary,output);temporary.unlink()
            except BaseException:
                temporary.unlink(missing_ok=True);raise
        return {'schema':'boopa-official-archive-download-r1','source_commit':commit,'url':'https://codeload.github.com/'+REPO+'/tar.gz/'+commit,'bytes':size,'sha256':digest.hexdigest(),'attempts':1,'authenticated_provider_context':False,'publication_acceptance':False}
    finally:
        if response is not None:response.close()

def materialize(archive,archive_sha256,output,commit,root_tree,metadata_tree,as_of,metadata_only=False,inventory_only=False):
    need(all(oid(x) for x in (commit,root_tree,metadata_tree)) and oid(archive_sha256,64),'immutable source identity required')
    need(type(metadata_only) is bool and type(inventory_only) is bool and not(metadata_only and inventory_only),'materialization mode')
    if type(as_of) is str:as_of=date.fromisoformat(as_of)
    need(type(as_of) is date,'canonical as-of date required')
    c=core();output=Path(output);need(not output.exists() and not output.is_symlink(),'new materialization destination required')
    fd=os.open(archive,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f,tempfile.TemporaryDirectory(prefix='.source-unaccepted-',dir=output.parent) as tmp:
        st=os.fstat(f.fileno());need(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and 0<st.st_size<=MAX_ARCHIVE,'bounded single-link archive required')
        need(c.file_digest(f)==archive_sha256,'archive pin mismatch');f.seek(0);stage=Path(tmp)
        selected=None if metadata_only or inventory_only else stage/'selected'
        if selected is not None:selected.mkdir(mode=0o700)
        sinv=None if metadata_only else (stage/'selected-inventory.jsonl').open('xb')
        try:
            with gzip.GzipFile(fileobj=f,mode='rb') as gz,(stage/'metadata-inventory.jsonl').open('xb') as inv:
                result,ids,markers=c.read_archive(c.Stream(gz),commit,root_tree,metadata_tree,inv,as_of,selected,sinv)
        finally:
            if sinv is not None:sinv.close()
        f.seek(0);need(c.file_digest(f)==archive_sha256 and c.stable_stat(os.fstat(f.fileno()))==c.stable_stat(st),'archive changed during scan')
        backend=result.pop('_backend_ids')
        objects={'metadata-product-ids.private.json':ids,'current-negative-markers.private.json':markers}
        if not metadata_only:objects['backend-product-ids.private.json']=backend
        for name,value in objects.items():(stage/name).write_bytes(c.encode(value))
        pins={p.name:{'bytes':p.stat().st_size,'sha256':hash_file(p)} for p in stage.iterdir() if p.is_file()}
        result.update(schema='boopa-current-metadata-negative-scan-r1' if metadata_only else 'boopa-rebuilt-saved-source-archive-v1',status='git-bound-complete-metadata-negative-scan-floor-comparison-pending' if metadata_only else 'git-bound-source-materialized-semantic-preparation-pending',source_commit=commit,archive_sha256=archive_sha256,archive_bytes=st.st_size,as_of_date=as_of.isoformat(),outputs=pins,scanner_sha256=hash_file(Path(__file__)),core_sha256=CORE_SHA,source_prices_semantically_scanned=False,source_prices_substituted=False,publication_acceptance=False,raw_data_metadata_materialized=selected is not None,inventory_only=inventory_only,collection_completion_verified=False,whole_catalog_complete=False,price_source_is_latest=False,source_semantic_preparation_complete=False)
        name='METADATA-NEGATIVE-SCAN.json' if metadata_only else 'SOURCE-ARCHIVE-RECEIPT.json'
        (stage/name).write_bytes(c.encode(result));need(hash_file(CORE)==CORE_SHA,'core changed during scan')
        need(not output.exists() and not output.is_symlink(),'materialization destination appeared');stage.rename(output)
        return result
