"""Trusted, read-only exact image-free catalog recombination gate."""
import hashlib,json,re
from pathlib import Path

import importlib.util
_codec_spec=importlib.util.spec_from_file_location('trusted_compact_codec',Path(__file__).resolve().parent/'compact_codec.py')
compact_codec=importlib.util.module_from_spec(_codec_spec)
_codec_spec.loader.exec_module(compact_codec)

CORE_FILES={f'search-core/core_{i}.json' for i in range(24)}|{f'search-core/images_{i}.json' for i in range(512)}

def exact_value(left, right):
 # Python equality aliases bool/int and int/float; retain exact parsed source types.
 if type(left) is not type(right):return False
 if isinstance(left,list):return len(left)==len(right) and all(exact_value(a,b) for a,b in zip(left,right))
 if isinstance(left,dict):return left.keys()==right.keys() and all(exact_value(left[k],right[k]) for k in left)
 return left==right

def validate(root, manifest=None, required=False):
 root=Path(root).resolve();directory=root/'search-core'
 actual=set()
 if directory.is_symlink():raise ValueError('Core directory symlink forbidden')
 if directory.exists():
  for path in directory.rglob('*'):
   if path.is_symlink() or path.is_dir():raise ValueError('Unexpected core directory/symlink')
   actual.add(path.relative_to(root).as_posix())
 declared=manifest.get('catalog_core') if manifest else None
 if not actual and declared is None and not required:return None
 if actual!=CORE_FILES:raise ValueError('Core namespace must contain exact 536 files')
 if manifest:
  listed={name for name in manifest.get('files',{}) if name.startswith('search-core/')}
  if listed!=CORE_FILES:raise ValueError('Core manifest namespace must contain exact 536 files')
  if not isinstance(declared,dict):raise ValueError('Core declaration required')
  if type(declared.get('schema')) is not int or type(declared.get('rows')) is not int or type(declared.get('image_buckets')) is not int or not isinstance(declared.get('part_rows'),list) or any(type(n) is not int for n in declared['part_rows']):raise ValueError('Core declaration integer types required')
  for name in CORE_FILES:
   if hashlib.sha256((root/name).read_bytes()).hexdigest()!=manifest['files'][name]:raise ValueError('Core hash mismatch: '+name)
 def read(name):
  return json.loads((root/name).read_text(encoding='utf8'))
 buckets=[];image_ids=set()
 for i in range(512):
  bucket=read(f'search-core/images_{i}.json')
  if not isinstance(bucket,dict):raise ValueError('Image bucket must be ID map')
  for ident,value in bucket.items():
   if not re.fullmatch('[1-9][0-9]*',ident) or int(ident)%512!=i or ident in image_ids or not isinstance(value,str):raise ValueError('Invalid image bucket row')
   image_ids.add(ident)
  buckets.append(bucket)
 ids=set();part_rows=[];formats=set()
 for i in range(24):
  original=read(f'search_index_{i}.json');payload=read(f'search-core/core_{i}.json')
  part_format='image-free-v1' if isinstance(payload,list) else 'compact-core-v1'
  formats.add(part_format)
  if manifest and declared.get('format')!=part_format:raise ValueError('Core declared format mismatch')
  core=payload if part_format=='image-free-v1' else compact_codec.decode(payload)
  if not isinstance(original,list) or not isinstance(core,list) or len(original)!=len(core):raise ValueError('Core row count mismatch')
  part_rows.append(len(original))
  for before,after in zip(original,core):
   if not isinstance(before,list) or not isinstance(after,list) or len(before)!=14 or len(after)!=14 or after[9]!='':raise ValueError('Invalid core row schema')
   ident=before[0]
   if not isinstance(ident,str) or not re.fullmatch('[1-9][0-9]*',ident) or ident in ids:raise ValueError('Invalid/duplicate core ID')
   ids.add(ident)
   restored=after[:];restored[9]=buckets[int(ident)%512].get(ident)
   if not exact_value(restored,before):raise ValueError('Core/image recombination differs: '+ident)
 if ids!=image_ids:raise ValueError('Image IDs differ from full catalog')
 if len(formats)!=1:raise ValueError('Mixed core formats')
 expected={'schema':1,'format':next(iter(formats)),'rows':len(ids),'part_rows':part_rows,'image_buckets':512}
 if manifest and declared!=expected:raise ValueError('Core declaration count/schema mismatch')
 if manifest and 'validation' in manifest:
  validation=manifest['validation']
  if not isinstance(validation,dict) or type(validation.get('rows')) is not int or validation['rows']!=len(ids):raise ValueError('Core declaration differs from validation row count')
 return expected
