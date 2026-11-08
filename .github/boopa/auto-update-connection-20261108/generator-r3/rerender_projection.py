"""Offline projection rerender context. Trust comes from fixed static pins, not source HTML."""
import copy,hashlib,importlib.util,json,tempfile
from pathlib import Path
from current_price_projection import CurrentPriceProjection,digest
from projection_integration import _now,apply_presentation
from static_assets import STATIC_HASHES
HERE=Path(__file__).resolve().parent
MODIFIED_STATIC=frozenset(('image-search.html','image-search-engine.js'))

def _read(root,name):
 root=Path(root);path=root/name
 if root.is_symlink() or path.is_symlink() or not path.is_file() or root.resolve() not in path.resolve().parents:raise ValueError('regular contained file required: '+name)
 if any(p.is_symlink() for p in path.parents if p!=root.parent and root.resolve() in (p.resolve(),*p.resolve().parents)):raise ValueError('symlink component rejected')
 return path.read_bytes()

def _originals():
 data={name:_read(HERE/'pinned-static',name) for name in STATIC_HASHES}
 for name,blob in data.items():
  if hashlib.sha256(blob).hexdigest()!=STATIC_HASHES[name]:raise ValueError('pinned original static mismatch: '+name)
 return data

def _module(name):
 spec=importlib.util.spec_from_file_location(name,HERE/'scripts'/(name+'.py'))
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def prepare_context(source,gate,raw_records,presentation_proof,presentation_sha256,expected_manifest_sha,_clock=None):
 """Return (derived static hashes, newly validated gate); never modify source.

 Only schema-1 package records are supported by this consumer. Parent must also
 perform its full candidate manifest verification before publishing/copying.
 """
 source=Path(source);manifest_blob=_read(source,'snapshot-manifest.json')
 if not isinstance(expected_manifest_sha,str) or hashlib.sha256(manifest_blob).hexdigest()!=expected_manifest_sha:raise ValueError('source manifest pin mismatch')
 manifest=json.loads(manifest_blob)
 if _clock is not None and manifest.get('fixture') is not True:raise ValueError('historical clock requires fixture source')
 if not isinstance(raw_records,dict):raise ValueError('explicit raw record mapping required')
 if not isinstance(presentation_proof,dict) or digest(presentation_proof)!=presentation_sha256:raise ValueError('presentation evidence hash mismatch')
 if manifest.get('presentation_proof_sha256')!=presentation_sha256:raise ValueError('source presentation digest mismatch')
 projection=manifest.get('current_price_projection',{})
 if projection.get('package_sha256')!=gate.package_sha256:raise ValueError('source projection package mismatch')
 package={'schema':1,'records':copy.deepcopy(gate.records)}
 fresh=CurrentPriceProjection(package,gate.package_sha256,_now(_clock).isoformat(),gate.evidence_artifacts)
 for item in sorted(fresh.records):
  raw=raw_records.get(item)
  if not isinstance(raw,dict) or str(raw.get('id'))!=item:raise ValueError('missing/mismatched raw mapping: '+item)
  fresh.for_item(copy.deepcopy(raw))
 if set(fresh.applied)!=set(fresh.records):raise ValueError('unapplied proof')
 config_blob=_read(source,'current-price-projection.json')
 if manifest.get('files',{}).get('current-price-projection.json')!=hashlib.sha256(config_blob).hexdigest():raise ValueError('source projection file hash mismatch')
 if json.loads(config_blob)!={'schema':1,'entries':fresh.applied}:raise ValueError('source projection config mismatch')
 originals=_originals()
 with tempfile.TemporaryDirectory(prefix='rerender-projection-') as directory:
  temp=Path(directory)
  for name,blob in originals.items():
   path=temp/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(blob)
  (temp/'current-price-projection.json').write_bytes(config_blob)
  source_lists=json.loads(_read(source,'lists_full.json'))
  if 'visibility' in source_lists:
   from visibility_overlay import apply_image_visibility
   (temp/'lists_full.json').write_text(json.dumps({'visibility':source_lists['visibility'],'stats':source_lists.get('stats',{})}))
   apply_image_visibility(temp)
  _module('guard_discount_display').main(temp)
  apply_presentation(temp,presentation_proof,presentation_sha256)
  _module('apply_current_price_projection').main(temp)
  expected={name:hashlib.sha256((temp/name).read_bytes()).hexdigest() for name in STATIC_HASHES}
  if any(expected[name]!=STATIC_HASHES[name] for name in STATIC_HASHES if name not in MODIFIED_STATIC):raise ValueError('unexpected static transformation')
 return expected,fresh

def reset_static(candidate):
 """Restore only potentially transformed statics from verified original bytes."""
 candidate=Path(candidate)
 if candidate.is_symlink() or not candidate.is_dir():raise ValueError('regular candidate directory required')
 originals=_originals() # Verify EVERY pin before any candidate write.
 for name in MODIFIED_STATIC:
  _read(candidate,name) # Reject missing/symlink destination before either write.
 for name in MODIFIED_STATIC:(candidate/name).write_bytes(originals[name])
