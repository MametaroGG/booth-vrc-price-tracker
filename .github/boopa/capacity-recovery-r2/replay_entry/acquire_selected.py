"""Explicit selected identity, no historical environment injection."""
import time
def acquire_selected(identity,saved_commit,previous_price_source_commit,token,transport,*,clock=time.time,monotonic=time.monotonic):
 previous=identity.oid(previous_price_source_commit);identity.oid(saved_commit)
 r=identity.Reader(token,transport,clock,monotonic)
 saved=r.identity(saved_commit,'saved');prior=r.identity(previous,'prior')
 before,bp,_=r.get('/git/ref/heads/main','latest-before')
 def head(v):
  identity.need(v.get('ref')=='refs/heads/main' and type(v.get('object')) is dict and v['object'].get('type')=='commit','main ref response');return identity.oid(v['object'].get('sha'))
 current=head(before)
 # Deliberately obtain current commit/root inside the two-ref observation window.
 r.cache.pop(current,None);latest=r.identity(current,'latest')
 after,ap,_=r.get('/git/ref/heads/main','latest-after');identity.need(head(after)==current,'main moved; do not retry')
 identities={'saved':saved,'prior':prior,'latest':latest};refs={}
 for key,obj in identities.items():
  name=key+'-identity.json';r.files[name]=identity.enc(obj);refs[key]={'path':name,'sha256':identity.sha(r.files[name])}
 recent={k:v for k,v in r.responses.items() if k.startswith('latest-')};dates=[v['provider_utc'] for v in recent.values()]
 observation={'schema':'boopa-latest-source-observation-r1','identity_proof':refs['latest'],'ref_before':bp,'ref_after':ap,'main_stable_across_two_reads':True,'observed_from_utc':r.responses['latest-before']['observed_from_utc'],'observed_through_utc':r.responses['latest-after']['observed_through_utc'],'provider_observation_upper_utc':max(dates),'responses':recent,'provider_authenticated':False,'runtime_execution_attested':False}
 r.files['LATEST-OBSERVATION.json']=identity.enc(observation)
 return {'schema':'boopa-source-identity-acquisition-r1','identity_proofs':refs,'latest_observation':{'path':'LATEST-OBSERVATION.json','sha256':identity.sha(r.files['LATEST-OBSERVATION.json'])},'requests':r.calls,'provider_authenticated':False,'runtime_execution_attested':False,'files':r.files}
