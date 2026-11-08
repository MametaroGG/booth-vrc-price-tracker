"""Explicit, hash-bound optional reviewed supplement; no inference or remote reads."""
import hashlib,json,re,struct,zlib
from pathlib import Path
from datetime import date
REQUIRED={'relationship-supplement.js','relation-supplement/manifest.json','relation-supplement/items.json'}
LOGO_PATH='relation-supplement/assets/modular-avatar-logo.png'
SCHEMA='boopadb-relation-supplement-v1'
def valid_inventory(files):return isinstance(files,dict) and set(files) in (REQUIRED,REQUIRED|{LOGO_PATH})
def sha(b):return hashlib.sha256(b).hexdigest()
def ident(v):return isinstance(v,str) and re.fullmatch('[1-9][0-9]{0,15}',v) is not None
def hexsha(v):return isinstance(v,str) and re.fullmatch('[a-f0-9]{64}',v) is not None

def valid_date(value):
 if not isinstance(value,str) or not re.fullmatch('[0-9]{4}-[0-9]{2}-[0-9]{2}',value):return False
 try:date.fromisoformat(value);return True
 except ValueError:return False


def validate_png(data):
 if len(data)>1024*1024 or data[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Logo must be bounded static PNG')
 offset=8;chunks=[]
 while offset<len(data):
  if len(chunks)>=1024 or offset+12>len(data):raise ValueError('Malformed logo PNG')
  size=struct.unpack('>I',data[offset:offset+4])[0];kind=data[offset+4:offset+8];end=offset+12+size
  if end>len(data):raise ValueError('Truncated logo PNG')
  content=data[offset+8:offset+8+size];crc=struct.unpack('>I',data[offset+8+size:end])[0]
  if zlib.crc32(kind+content)&0xffffffff!=crc:raise ValueError('Logo PNG CRC mismatch')
  if not chunks:
   if kind!=b'IHDR' or size!=13:raise ValueError('Logo PNG missing IHDR')
   w,h,depth,color,compression,filtering,interlace=struct.unpack('>IIBBBBB',content)
   if not 0<w<=4096 or not 0<h<=4096 or w*h>4_000_000 or (depth,color,compression,filtering,interlace)!=(8,6,0,0,0):raise ValueError('Logo PNG dimensions/format unsupported')
  elif kind==b'IHDR':raise ValueError('Duplicate logo PNG IHDR')
  if kind in (b'acTL',b'fcTL',b'fdAT'):raise ValueError('Animated logo PNG forbidden')
  chunks.append(kind);offset=end
  if kind==b'IEND':
   if size or offset!=len(data):raise ValueError('Logo PNG trailing content')
   break
 if not chunks or chunks[-1]!=b'IEND' or b'IDAT' not in chunks:raise ValueError('Incomplete logo PNG')

def check_logo(root,approval,relations,verified_output=None):
 def read(name):return verified_output.read_bytes(name) if verified_output else (root/name).read_bytes()
 files=approval['files'];ui=root/'relationship-ui-draft.js'
 if LOGO_PATH not in files:
  if (verified_output.exists('relationship-ui-draft.js') if verified_output else ui.exists()) and LOGO_PATH in read('relationship-ui-draft.js').decode('utf-8'):raise ValueError('Logo-referencing renderer requires approved logo asset')
  return
 validate_png(read(LOGO_PATH))
 if (not verified_output and not ui.is_file()) or sha(read('relationship-ui-draft.js'))!=relations.get('files',{}).get('relationship-ui-draft.js'):raise ValueError('Logo requires approved shared renderer')
 refs=re.findall(r'src="('+re.escape(LOGO_PATH)+r'(?:\?[^"]*)?)"',read('relationship-ui-draft.js').decode('utf-8'))
 if refs!=[LOGO_PATH+'?v='+files[LOGO_PATH][:16]]:raise ValueError('Logo reference differs from approved asset hash')

def validate(root,approval,relations,verified_output=None):
 root=Path(root)
 if verified_output is not None:verified_output.assert_root(root)
 def read(name):return verified_output.read_bytes(name) if verified_output else (root/name).read_bytes()
 if not isinstance(approval,dict) or approval.get('schema')!=1 or approval.get('status') not in ('approved','approved-bundle') or approval.get('activate') is not True:
  raise ValueError('Explicit active supplement approval required')
 if not isinstance(relations,dict) or relations.get('status')!='approved-bundle' or relations.get('activate') is not True or approval.get('sourceVersion')!=relations.get('version'):
  raise ValueError('Supplement requires matching approved relationship source')
 files=approval.get('files')
 if not hexsha(approval.get('version')) or not valid_inventory(files):raise ValueError('Supplement approval inventory/version invalid')
 if verified_output is not None:verified_output.bind_expected({**files,'relationship-ui-draft.js':relations.get('files',{}).get('relationship-ui-draft.js')})
 for name,digest in files.items():
  p=root/name
  if verified_output is None and (any(x.is_symlink() for x in (p,*p.parents)) or root.resolve() not in p.resolve().parents):raise ValueError('Supplement integrity failure: '+name)
  if not hexsha(digest) or sha(read(name))!=digest:raise ValueError('Supplement integrity failure: '+name)
 check_logo(root,approval,relations,verified_output=verified_output)
 m=json.loads(read('relation-supplement/manifest.json'));d=json.loads(read('relation-supplement/items.json'))
 for obj in (m,d):
  if not isinstance(obj,dict) or obj.get('schema')!=SCHEMA or obj.get('version')!=approval['version'] or obj.get('sourceVersion')!=approval['sourceVersion']:raise ValueError('Supplement mixed schema/version/source')
 ids=m.get('itemIds');items=d.get('items')
 canonical=json.dumps({'schema':SCHEMA,'sourceVersion':d['sourceVersion'],'items':items},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
 if sha(canonical)!=approval['version']:raise ValueError('Supplement content-derived version mismatch')
 item_bytes=read('relation-supplement/items.json')
 if m.get('files')!={'items.json':{'bytes':len(item_bytes),'sha256':sha(item_bytes)}}:raise ValueError('Supplement internal inventory mismatch')
 if not isinstance(ids,list) or len(ids)>1000 or not all(ident(i) for i in ids) or len(set(ids))!=len(ids) or not isinstance(items,dict) or set(items)!=set(ids):raise ValueError('Supplement item allowlist mismatch')
 for self,row in items.items():
  if not isinstance(row,dict) or set(row)!={'tools','references'} or not isinstance(row['tools'],list) or not isinstance(row['references'],list) or len(row['tools'])>20 or len(row['references'])>30:raise ValueError('Invalid supplement row')
  seen=set()
  for t in row['tools']:
   if not isinstance(t,dict) or t.get('kind')!='external_tool' or t.get('toolKey')!='modular_avatar' or t.get('name')!='Modular Avatar' or t.get('url')!='https://modular-avatar.nadena.dev/ja' or t.get('status')!='reviewed_required' or not hexsha(t.get('evidenceSha256')) or t['toolKey'] in seen:raise ValueError('Unreviewed/unsafe supplemental tool')
   if not valid_date(t.get('observedAt')):raise ValueError('Invalid tool observation date')
   seen.add(t['toolKey'])
  for ref in row['references']:
   if not isinstance(ref,dict) or ref.get('kind')!='booth_reference' or not ident(ref.get('id')) or ref['id']==self or ref['id'] in seen or not isinstance(ref.get('name'),str) or not 1<=len(ref['name'])<=300 or ref.get('status')!='reviewed_reference' or ref.get('sourceAge') not in ('historical_capture_unknown','seller_reviewed_at') or not hexsha(ref.get('evidenceSha256')):raise ValueError('Unreviewed/unsafe supplemental reference')
   if ref['sourceAge']=='seller_reviewed_at':
    if not valid_date(ref.get('observedAt')):raise ValueError('Invalid reference observation date')
   seen.add(ref['id'])
 return m

def check_import(html,approval):
 expected='relationship-supplement.js?v='+approval['files']['relationship-supplement.js'][:16]
 imports=re.findall(r'<script src="(relationship-supplement\.js(?:\?[^"]*)?)"></script>',html)
 if imports!=[expected]:raise ValueError('Supplement import differs from approved content hash')

def configure(candidate,bundle,approval_file,relations,verified_output=None):
 candidate=Path(candidate);index=candidate/'index.html';html=index.read_text()
 if bool(bundle)!=bool(approval_file):raise ValueError('Supplement bundle and approval required together')
 if not bundle:
  index.write_text(re.sub(r'<script src="relationship-supplement\.js(?:\?v=[0-9a-f]{16,64})?"></script>\n?','',html));return 'disabled'
 raw=Path(approval_file).read_bytes();approval=json.loads(raw)
 if not valid_inventory(approval.get('files')):raise ValueError('Supplement approval inventory mismatch')
 for name,digest in approval['files'].items():
  p=Path(bundle)/name
  if any(x.is_symlink() for x in (p,*p.parents)) or Path(bundle).resolve() not in p.resolve().parents:raise ValueError('Unsafe supplement path')
  b=p.read_bytes()
  if sha(b)!=digest:raise ValueError('Supplement source hash mismatch')
  target=candidate/name
  if target.exists():raise FileExistsError('Refusing supplement overwrite')
  target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b)
 validate(candidate,approval,relations,verified_output=verified_output);check_import(html,approval)
 return {'schema':1,'status':'approved-bundle','activate':True,'version':approval['version'],'sourceVersion':approval['sourceVersion'],'files':approval['files'],'approval_sha256':sha(raw),'scope':approval.get('scope','unspecified')}
