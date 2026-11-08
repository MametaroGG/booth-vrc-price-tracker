"""Pure pinned observation read/validation only. No network or environment access."""
import datetime,email.utils,hashlib,json,math,re,os,stat
from pathlib import Path
BASE='https://api.github.com/repos/MametaroGG/booth-vrc-price-tracker'
LIMIT=2*1024*1024
UTC=datetime.timezone.utc
def need(v,m):
 if not v:raise ValueError('Git identity acquisition: '+m)
def sha(b):return hashlib.sha256(b).hexdigest()
def enc(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def oid(v):need(type(v) is str and re.fullmatch('[0-9a-f]{40}',v),'canonical Git OID');return v
def pin(v):need(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'canonical digest');return v
def iso(t):return datetime.datetime.fromtimestamp(t,UTC).isoformat().replace('+00:00','Z')
def strict(raw):
 need(type(raw) is bytes and 0<len(raw)<=LIMIT,'bounded JSON')
 def pairs(rows):
  d={}
  for k,v in rows:need(k not in d,'duplicate JSON key');d[k]=v
  return d
 def bad(v):raise ValueError('Git identity acquisition: nonfinite JSON')
 def number(v):
  f=float(v);need(math.isfinite(f),'finite JSON number');return f
 return json.loads(raw,object_pairs_hook=pairs,parse_constant=bad,parse_float=number)
def tree_identity(body,expected):
 need(type(body) is dict and body.get('sha')==oid(expected) and body.get('truncated') is False and type(body.get('tree')) is list,'complete root response')
 records=[];names=set();sub={}
 for row in body['tree']:
  need(type(row) is dict,'tree entry');name=row.get('path');mode=row.get('mode');kind=row.get('type')
  need(type(name) is str and name not in ('','.','..') and '/' not in name and '\\' not in name and all(ord(x)>=32 and ord(x)!=127 for x in name) and name not in names,'direct unique tree path');names.add(name)
  need((kind,mode) in {('tree','040000'),('blob','100644'),('blob','100755')},'supported source root type/mode');h=oid(row.get('sha'))
  n=name.encode();records.append((n+(b'/' if kind=='tree' else b''),(b'40000' if kind=='tree' else mode.encode())+b' '+n+b'\0'+bytes.fromhex(h)))
  if name in ('data','meta'):need(kind=='tree','source subtree');sub[name]=h
 raw=b''.join(v for _,v in sorted(records));need(hashlib.sha1(b'tree '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==expected,'Git root rehash')
 need(set(sub)=={'data','meta'},'required source subtrees');return sub

def validate_observation_bytes(observation_raw,expected_sha256,files):
 """Validate pinned evidence and return only its bound UTC/JST date ceiling.
 Files are caller-supplied exact evidence bytes; this is NOT authentication.
 """
 pin(expected_sha256);need(sha(observation_raw)==expected_sha256,'observation raw pin');o=strict(observation_raw)
 fields={'schema','identity_proof','ref_before','ref_after','main_stable_across_two_reads','observed_from_utc','observed_through_utc','provider_observation_upper_utc','responses','provider_authenticated','runtime_execution_attested'}
 need(set(o)==fields and o['schema']=='boopa-latest-source-observation-r1' and o['main_stable_across_two_reads'] is True and o['provider_authenticated'] is False and o['runtime_execution_attested'] is False,'closed observation scope')
 def bound(entry):
  need(type(entry) is dict and set(entry)=={'path','sha256'} and type(entry['path']) is str and re.fullmatch('[a-z-]+[.]json',entry['path']),'evidence filename')
  pin(entry['sha256']);b=files[entry['path']];need(sha(b)==entry['sha256'],'evidence byte pin');return strict(b)
 ident=bound(o['identity_proof']);need(set(ident)=={'schema','commit','root_tree','metadata_tree','data_tree','commit_response','root_response'} and ident['schema']=='boopa-git-source-identity-r1','identity schema')
 for k in ('commit','root_tree','metadata_tree','data_tree'):oid(ident[k])
 cm=bound(ident['commit_response']);rt=bound(ident['root_response']);need(cm['sha']==ident['commit'] and cm['tree']['sha']==ident['root_tree'],'identity commit/root')
 sub=tree_identity(rt,ident['root_tree']);need(sub=={'meta':ident['metadata_tree'],'data':ident['data_tree']},'identity subtrees')
 refs=[bound(o['ref_before']),bound(o['ref_after'])]
 for v in refs:need(v.get('ref')=='refs/heads/main' and v.get('object',{}).get('type')=='commit' and v['object']['sha']==ident['commit'],'stable refs')
 urls={'latest-before':BASE+'/git/ref/heads/main','latest-after':BASE+'/git/ref/heads/main','latest-commit':BASE+'/git/commits/'+ident['commit'],'latest-root':BASE+'/git/trees/'+ident['root_tree']}
 expected={'latest-before':refs[0],'latest-after':refs[1],'latest-commit':cm,'latest-root':rt};expected_raw={'latest-before':files[o['ref_before']['path']],'latest-after':files[o['ref_after']['path']],'latest-commit':files[ident['commit_response']['path']],'latest-root':files[ident['root_response']['path']]};need(set(o['responses'])==set(urls),'closed observation responses');uppers=[];windows=[]
 def stamp(v):
  need(type(v) is str and v.endswith('Z'),'UTC timestamp');dt=datetime.datetime.fromisoformat(v.replace('Z','+00:00'));return dt.timestamp()
 for k,url in urls.items():
  r=o['responses'][k];need(set(r)=={'url','response_raw','response_sha256','response_utf8_bytes','http_date','provider_utc','observed_from_utc','observed_through_utc'},'closed response evidence');need(r['url']==url and type(r['response_raw']) is str,'response endpoint')
  rb=r['response_raw'].encode();need(type(r['response_utf8_bytes']) is int and len(rb)==r['response_utf8_bytes'] and sha(rb)==r['response_sha256'] and rb==expected_raw[k] and strict(rb)==expected[k],'response identity bytes')
  dt=email.utils.parsedate_to_datetime(r['http_date']);need(dt is not None and dt.tzinfo is not None and dt.utcoffset()==datetime.timedelta(0),'provider UTC Date');ts=dt.timestamp();a=stamp(r['observed_from_utc']);b=stamp(r['observed_through_utc']);need(a<=b and a-300<=ts<=b+300 and r['provider_utc']==iso(ts),'provider/local date relation');uppers.append(ts);windows.append((k,a,b))
 start=stamp(o['observed_from_utc']);end=stamp(o['observed_through_utc']);need(start==stamp(o['responses']['latest-before']['observed_from_utc']) and end==stamp(o['responses']['latest-after']['observed_through_utc']) and all(start<=a<=b<=end for _,a,b in windows),'bounded latest observation window')
 need(o['provider_observation_upper_utc']==iso(max(uppers)),'maximum provider Date')
 return {'observation_sha256':expected_sha256,'commit':ident['commit'],'metadata_tree':ident['metadata_tree'],'provider_observation_upper_utc':o['provider_observation_upper_utc'],'upper_jst_day':datetime.datetime.fromtimestamp(max(uppers),datetime.timezone(datetime.timedelta(hours=9))).date().isoformat(),'provider_authenticated':False}

def read_regular(path):
 path=Path(path);need(path.is_absolute(),'absolute evidence path')
 parts=path.parts;fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:
  for part in parts[1:-1]:
   need(part not in ('','.','..'),'evidence parent');child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=child
  f=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
  try:
   a=os.fstat(f);need(stat.S_ISREG(a.st_mode) and a.st_nlink==1 and 0<a.st_size<=LIMIT,'bounded evidence regular file')
   with os.fdopen(os.dup(f),'rb') as stream:b=stream.read(LIMIT+1)
   z=os.fstat(f);keys=('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns');need(len(b)==a.st_size and all(getattr(a,k)==getattr(z,k) for k in keys),'evidence changed');return b
  finally:os.close(f)
 finally:os.close(fd)

def validate_observation(path,pin_value,expected_commit,expected_meta):
 path=Path(path);raw=read_regular(path);pin(pin_value);need(sha(raw)==pin_value,'observation pin');o=strict(raw);files={}
 def load(entry):
  name=entry['path'];need(type(name) is str and re.fullmatch('[a-z-]+[.]json',name),'evidence basename');b=read_regular(path.parent/name);need(sha(b)==entry['sha256'],'evidence external pin');files[name]=b;return strict(b)
 ident=load(o['identity_proof']);load(ident['commit_response']);load(ident['root_response']);load(o['ref_before']);load(o['ref_after'])
 result=validate_observation_bytes(raw,pin_value,files);need(result['commit']==oid(expected_commit) and result['metadata_tree']==oid(expected_meta),'expected observation cutoff')
 result['upper_jst_date']=result.pop('upper_jst_day');return result
