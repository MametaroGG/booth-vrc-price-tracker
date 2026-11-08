"""Offline integration boundary for pinned current-price evidence.

No CLI historical-time override. Test-only private clock parameters allow frozen
fixture regression. Generator must call gate.for_item BEFORE deriving payloads.
"""
import hashlib,importlib.util,json
from datetime import datetime,timezone
from pathlib import Path
from current_price_projection import CurrentPriceProjection,dt,digest
HERE=Path(__file__).resolve().parent

def _now(clock):
 now=(clock or (lambda:datetime.now(timezone.utc)))()
 if not isinstance(now,datetime) or now.tzinfo is None:raise ValueError('aware clock required')
 return now.astimezone(timezone.utc)

def load_projection(package_path,expected_sha256,evidence_paths,*,_clock=None):
 package_path=Path(package_path)
 if package_path.is_symlink() or not package_path.is_file():raise ValueError('regular package required')
 artifacts={}
 for path in map(Path,evidence_paths):
  if path.is_symlink() or not path.is_file():raise ValueError('regular evidence required')
  blob=path.read_bytes();artifacts[hashlib.sha256(blob).hexdigest()]=blob
 gate=CurrentPriceProjection(json.loads(package_path.read_text()),expected_sha256,_now(_clock).isoformat(),artifacts)
 # Fail at load, not after a costly build, for already expired/future proofs.
 for proof in gate.records.values():
  if not dt(proof['snapshot']['observed_at'])<=gate.as_of<dt(proof['expires_at']):raise ValueError('projection stale/future')
 return gate

def finalize_projection(candidate,gate,*,_clock=None, presentation_proof=None, presentation_sha256=None):
 """After display transforms, before final validation and file hashes.

Does not repair unprojected JSON: build_full must already derive every data
surface using this gate. Reject unconsumed proofs and mismatched config.
"""
 candidate=Path(candidate);now=_now(_clock)
 if not candidate.is_dir() or candidate.is_symlink():raise ValueError('candidate directory required')
 if set(gate.applied)!=set(gate.records):raise ValueError('unapplied projection proof')
 for entry in gate.applied.values():
  if not dt(entry['selection_observed_at'])<=now<dt(entry['expires_at']):raise ValueError('projection expired during generation')
 config_path=candidate/'current-price-projection.json'
 if config_path.is_symlink() or not config_path.is_file():raise ValueError('generator projection payload required')
 config=json.loads(config_path.read_text())
 if config!={'schema':1,'entries':gate.applied}:raise ValueError('generator projection payload mismatch')
 if presentation_proof is not None:apply_presentation(candidate,presentation_proof,presentation_sha256)
 elif presentation_sha256 is not None:raise ValueError('presentation proof and digest required together')
 spec=importlib.util.spec_from_file_location('apply_current_price_projection',HERE/'scripts/apply_current_price_projection.py')
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 module.main(candidate)
 return {'package_sha256':gate.package_sha256,'as_of':gate.as_of.isoformat(),'finalized_at':now.isoformat(),'item_ids':sorted(gate.applied),'scope':'verified-current-selection-not-history-migration',**({'presentation_sha256':presentation_sha256} if presentation_proof is not None else {})}


def apply_presentation(candidate,proof,expected_sha256):
 """After discount guard, before projection. Caller supplies bound evidence.

 Never infer verified current availability from historical raw series. Missing
 evidence-builder source must not be replaced with an invented empty proof.
 """
 if not isinstance(proof,dict) or proof.get('schema')!=1 or not isinstance(proof.get('entries'),dict):raise ValueError('explicit presentation evidence required')
 if not isinstance(expected_sha256,str) or digest(proof)!=expected_sha256:raise ValueError('presentation evidence hash mismatch')
 for name in ('apply_price_presentation','apply_sale_card_labels'):
  spec=importlib.util.spec_from_file_location(name,HERE/'scripts'/(name+'.py'))
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  if name=='apply_price_presentation':module.main(candidate,proof)
  else:module.main(candidate)
