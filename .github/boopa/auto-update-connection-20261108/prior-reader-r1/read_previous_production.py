"""Read-only fixed-public-repository reader; local output only, no import I/O network."""
import hashlib,importlib.util,json,os,re,stat
from pathlib import Path
REPO='https://github.com/MametaroGG/boopadb.git'
PUB_FREEZE='a03b6516f862d075908f303b7b5e566f2a8f387743f301b8f203d0965a822d88'
BASE_FIELDS={'schema','price_source_commit','metadata_source_commit','source_receipt_sha256','selection_receipt_sha256','quarantine_proof_sha256','latest_negative_overlay_sha256','retained_snapshot_sha256','collection_completion_verified','whole_catalog_complete','price_source_is_latest'}
def need(v,m):
 if not v:raise ValueError('previous production: '+m)
def sha(b):return hashlib.sha256(b).hexdigest()
def enc(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def load_git():
 p=Path(__file__).resolve().parent.parent/'publisher-r3';b=(p/'FREEZE.json').read_bytes();need(sha(b)==PUB_FREEZE,'publisher freeze')
 for n,h in json.loads(b)['files'].items():need(Path(n).name==n and sha((p/n).read_bytes())==h,'publisher member pin')
 spec=importlib.util.spec_from_file_location('prior_reader_git',p/'git_publication.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def provenance(m):
 need(type(m) is dict and type(m.get('schema')) is int and m['schema']==1 and m.get('status')=='validated-candidate' and m.get('fixture') is False,'unsupported published manifest')
 s=m.get('saved_snapshot_composition');need(type(s) is dict,'saved provenance required')
 version=s.get('schema');need(version in ('boopa-saved-snapshot-composition-r1','boopa-saved-snapshot-composition-r2'),'unsupported source schema')
 need(set(s)==BASE_FIELDS|({'run_bindings_sha256'} if version.endswith('r2') else set()),'closed saved provenance')
 for k,v in s.items():
  if k.endswith('_commit'):need(type(v) is str and re.fullmatch('[0-9a-f]{40}',v),'source commit')
  if k.endswith('_sha256'):need(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'source digest')
 for k in ('collection_completion_verified','whole_catalog_complete','price_source_is_latest'):need(s[k] is False and m.get(k) is False,'bounded source flags')
 return s

def object_bytes(g,repo,kind,oid,cap):
 g.oid(oid);need(g.git(repo,'cat-file','-t',oid)==kind,'Git object type')
 size=g.git(repo,'cat-file','-s',oid);need(size.isascii() and size.isdecimal() and int(size)<=cap,'Git object size')
 b=g.git_bytes(repo,'cat-file',kind,oid);need(len(b)==int(size),'Git object truncated')
 need(hashlib.sha1(kind.encode()+b' '+str(len(b)).encode()+b'\0'+b).hexdigest()==oid,'Git object hash');return b

def inspect_local(repo,expected_parent,g=None):
 """Consume a locally fetched immutable commit, not an assertion of live main."""
 g=g or load_git();g.inspect_repo(repo);g.oid(expected_parent)
 commit=object_bytes(g,repo,'commit',expected_parent,65536)
 lines=commit.split(b'\n\n',1)[0].splitlines();trees=[x[5:].decode('ascii') for x in lines if x.startswith(b'tree ')]
 need(len(trees)==1,'commit root');root=g.oid(trees[0]);leaves={};seen_paths=set();treecount=0
 def walk(tree,prefix='',depth=0):
  nonlocal treecount
  treecount+=1;need(treecount<=64 and depth<=8,'tree budget')
  b=object_bytes(g,repo,'tree',tree,1024*1024);pos=0;order=[]
  while pos<len(b):
   stop=b.find(b'\0',pos);need(stop>=0 and stop+21<=len(b),'tree framing')
   mode,name=b[pos:stop].split(b' ',1);h=b[stop+1:stop+21].hex();pos=stop+21
   n=name.decode('utf-8');need('/' not in n,'direct tree name');g.safe_name(n)
   path=prefix+n;need(path not in seen_paths,'duplicate tree path');seen_paths.add(path)
   need(mode in (b'40000',b'100644',b'100755'),'no symlink/submodule')
   order.append(name+(b'/' if mode==b'40000' else b''))
   if mode==b'40000':walk(h,path+'/',depth+1)
   else:leaves[path]={'mode':mode.decode(),'git_blob':h}
  need(order==sorted(order),'canonical tree order')
 walk(root);need(len(leaves)==743 and 'snapshot-manifest.json' in leaves,'743 baseline blobs required')
 manifest_raw=object_bytes(g,repo,'blob',leaves['snapshot-manifest.json']['git_blob'],1024*1024)
 manifest=g.json_strict(manifest_raw);source=provenance(manifest)
 files=manifest.get('files');need(type(files) is dict and len(files)==723 and 'snapshot-manifest.json' not in files,'724 manifest closure')
 expected={**files,'snapshot-manifest.json':sha(manifest_raw)};need(set(expected)<=set(leaves),'manifest outside Git tree')
 blobs={};total=0
 for n,h in expected.items():
  g.safe_name(n);need(not n.startswith(('.git/','.github/')) and n not in ('.git','.github'),'management cannot be site')
  need(leaves[n]['mode']=='100644','public mode');b=manifest_raw if n=='snapshot-manifest.json' else object_bytes(g,repo,'blob',leaves[n]['git_blob'],128*1024*1024)
  total+=len(b);need(total<=256*1024*1024 and sha(b)==h,'bounded site bytes/hash');blobs[n]=b
 lists=g.json_strict(blobs['lists_full.json']);hidden=lists['visibility']['hidden_ids']
 need(type(hidden) is list and len(hidden)==len(set(hidden)) and all(type(x) is str and re.fullmatch('[1-9][0-9]*',x) for x in hidden),'unique canonical floor IDs')
 need(manifest['visibility']['effective_hidden_total']==len(hidden),'floor count')
 ids=sorted(hidden);management={n:entry for n,entry in leaves.items() if n not in expected};need(len(management)==19,'management count')
 result={'schema':'boopa-previous-production-input-r1','repository':'MametaroGG/boopadb','branch':'main','expected_public_parent_commit':expected_parent,'public_root_tree':root,'prior_snapshot_sha256':sha(manifest_raw),'prior_lists_sha256':sha(blobs['lists_full.json']),'retained_ids_sha256':sha(enc(ids)),'retained_ids_count':len(ids),'previous_price_source_commit':source['price_source_commit'],'previous_source_receipt_sha256':source['source_receipt_sha256'],'management_inventory_sha256':sha(enc(management)),'site_files':724,'site_bytes':total,'tree_count':treecount,'commit_object_sha256':sha(commit),'provider_authenticated':False,'deployment_verified':False}
 return result,blobs,management

def materialize(result,blobs,management,destination,g=None):
 """Exclusive local destination; no handoff until all bytes independently read back.
 Failure leaves partial directory, never an accepted handoff. Caller uses new path.
 """
 g=g or load_git();dest=Path(destination);parent=dest.parent
 need(dest.is_absolute() and parent.resolve()==parent,'resolved output parent')
 g.safe_name(dest.name);p=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:
  os.mkdir(dest.name,0o700,dir_fd=p);fd=os.open(dest.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=p)
  try:
   for n,b in blobs.items():
    parts=n.split('/');g.safe_name(n);d=os.dup(fd)
    try:
     for part in parts[:-1]:
      try:os.mkdir(part,0o700,dir_fd=d)
      except FileExistsError:pass
      nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=d);os.close(d);d=nxt
     f=os.open(parts[-1],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=d)
     with os.fdopen(f,'wb') as stream:stream.write(b);stream.flush();os.fsync(stream.fileno())
    finally:os.close(d)
   checked=g.snapshot(dest,result['prior_snapshot_sha256']);need(checked==blobs,'output readback')
   st=os.stat(dest.name,dir_fd=p,follow_symlinks=False);need((st.st_dev,st.st_ino)==(os.fstat(fd).st_dev,os.fstat(fd).st_ino),'output namespace changed')
   need((os.stat(parent).st_dev,os.stat(parent).st_ino)==(os.fstat(p).st_dev,os.fstat(p).st_ino),'output parent changed')
  finally:os.close(fd)
 finally:os.close(p)
 return {**result,'prior_candidate_path':str(dest)},management

def fetch_current(repo):
 """Explicit public GET-equivalent Git fetch; no token/credential discovery.
 Caller provides isolated initialized local repo. Not invoked by local tests.
 """
 g=load_git()
 def head():
  parts=g.git(repo,'ls-remote','--exit-code',REPO,'refs/heads/main').split();need(len(parts)==2 and parts[1]=='refs/heads/main','main observation');return g.oid(parts[0])
 before=head();g.git(repo,'fetch','--no-tags','--no-write-fetch-head','--depth=1',REPO,before)
 result=inspect_local(repo,before,g);need(head()==before,'public main moved during read');return result
