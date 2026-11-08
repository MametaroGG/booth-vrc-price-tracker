"""Offline verifier for a same-workflow saved-input handoff (new r2 contract).

It verifies exact relations/bytes, never authenticates caller-provided runner/API
records. The workflow adapter must supply those records through trusted Actions
contexts and authenticated reads before an actual automatic run is enabled.
"""
import hashlib, io, json, re, stat, zipfile
REPO='MametaroGG/booth-vrc-price-tracker'
REPO_ID=1134883798
PATH='.github/workflows/daily_scrape.yml'
LIMIT=65536
MAX_ID=9007199254740991
METRICS={'searchPages','searchFailures','itemSuccess','itemFailures','unavailable','retries','duplicatesAvoided','chargedHttpAttempts','dailyChargedRequests'}
CONTEXT={'schema','server_url','actions','repository','repository_id','run_id','run_attempt','workflow_ref','workflow_sha','scrape_job_result','artifact_id','artifact_digest','saved_commit'}
SAVED={'schema','repository','run_id','scraper_outcome','save_outcome','run_attempt','tracker_commit','collection_receipt_sha256'}
COLLECTION={'status','failed','metrics','continueCollection','started_at_ms','stopped_at_ms','deadline_ms','blocked_until_ms','reservation_completed','pending_retry_count','schema','repository','run_id','run_attempt','source_commit','reservation_id','scope','whole_catalog_complete'}
def need(x,m):
    if not x:raise ValueError('saved handoff: '+m)
def sha(b):return hashlib.sha256(b).hexdigest()
def digest(s,n=64):return type(s) is str and re.fullmatch('[0-9a-f]{'+str(n)+'}',s) is not None
def ident(s):return type(s) is str and re.fullmatch('[1-9][0-9]*',s) is not None and len(s)<=16 and int(s)<=MAX_ID
def count(v):return type(v) is int and 0<=v<=MAX_ID
def strict(b):
    need(type(b) is bytes and 0<len(b)<=LIMIT,'bounded exact JSON bytes required')
    def pairs(rows):
        d={}
        for k,v in rows:
            need(k not in d,'duplicate JSON key');d[k]=v
        return d
    def bad(_):raise ValueError('saved handoff: nonfinite JSON')
    return json.loads(b,object_pairs_hook=pairs,parse_constant=bad)
def eligible(c,ctx):
    need(type(c) is dict and set(c)==COLLECTION|({'reason'} if c.get('status')=='paused' else set()),'closed collection fields')
    need(c['schema']=='boopa-collection-receipt-v1' and c['repository']==REPO,'collection schema/repo')
    need(c['run_id']==ctx['run_id'] and c['run_attempt']==ctx['run_attempt'] and c['reservation_id']==ctx['run_id']+'-'+ctx['run_attempt'],'collection run/attempt')
    need(digest(c['source_commit'],40),'collection checkout commit')
    need(c['scope']=='bounded-filtered-search-observation' and c['whole_catalog_complete'] is False,'bounded scope')
    need(c['failed'] is False and c['reservation_completed'] is True and type(c['continueCollection']) is bool,'successful reservation')
    need(all(count(c[k]) for k in ('started_at_ms','stopped_at_ms','deadline_ms','blocked_until_ms','pending_retry_count')),'collection counter types')
    need(c['stopped_at_ms']>=c['started_at_ms'] and c['deadline_ms']>c['started_at_ms'] and c['blocked_until_ms']<=c['stopped_at_ms'],'collection times')
    m=c['metrics'];need(type(m) is dict and set(m)==METRICS and all(count(x) for x in m.values()),'closed metrics')
    need(m['chargedHttpAttempts']>0 and m['itemSuccess']>0 and m['itemFailures']==m['searchFailures']==0,'successful observations')
    if c['status']=='completed':need(c['pending_retry_count']==0,'completed pending retry')
    elif c['status']=='paused' and c['reason']=='deadline':need(c['stopped_at_ms']-c['started_at_ms']>=60000 and c['stopped_at_ms']>=c['deadline_ms']-2000,'actual deadline pause')
    elif c['status']=='paused' and c['reason']=='day-boundary':need((c['started_at_ms']+32400000)//86400000 != (c['stopped_at_ms']+32400000)//86400000,'actual JST boundary')
    else:raise ValueError('saved handoff: unsupported success/paused outcome')

def verify(context_raw,artifact_raw,wrapper,collection_raw,commit_raw,workflow_raw,expected_workflow_sha256):
    c=strict(context_raw);a=strict(artifact_raw);cm=strict(commit_raw)
    need(type(c) is dict and set(c)==CONTEXT and c['schema']=='boopa-same-workflow-context-r2','closed context')
    need(c['server_url']=='https://github.com' and c['actions']=='true','public GitHub Actions context')
    need(c['repository']==REPO and type(c['repository_id']) is int and c['repository_id']==REPO_ID,'repository identity')
    need(all(ident(c[k]) for k in ('run_id','run_attempt','artifact_id')),'canonical IDs')
    need(c['workflow_ref']==REPO+'/'+PATH+'@refs/heads/main' and digest(c['workflow_sha'],40),'workflow identity')
    need(c['scrape_job_result']=='success' and digest(c['saved_commit'],40),'producer job/save')
    need(digest(expected_workflow_sha256) and type(workflow_raw) is bytes and 0<len(workflow_raw)<=LIMIT and sha(workflow_raw)==expected_workflow_sha256,'reviewed workflow bytes')
    need(type(c['artifact_digest']) is str and c['artifact_digest'].startswith('sha256:') and digest(c['artifact_digest'][7:]),'action wrapper digest')
    need(type(a) is dict,'artifact object')
    need(type(a.get('id')) is int and a['id']==int(c['artifact_id']) and a.get('name')=='boopadb-collector-'+c['run_id']+'-'+c['run_attempt'],'artifact ID/name')
    need(a.get('expired') is False and a.get('digest')==c['artifact_digest'],'artifact expiration/digest')
    base='https://api.github.com/repos/'+REPO+'/actions/artifacts/'+c['artifact_id']
    need(a.get('url')==base and a.get('archive_download_url')==base+'/zip','exact artifact URLs')
    ar=a.get('workflow_run');need(type(ar) is dict and type(ar.get('id')) is int and ar['id']==int(c['run_id']) and type(ar.get('repository_id')) is int and ar['repository_id']==REPO_ID,'artifact producer relation')
    # head_sha is an event commit, never a substitute for workflow_sha or saved_commit.
    need(type(wrapper) is bytes and 0<len(wrapper)<=LIMIT and type(a.get('size_in_bytes')) is int and len(wrapper)==a['size_in_bytes'] and 'sha256:'+sha(wrapper)==c['artifact_digest'],'actual wrapper digest/size')
    with zipfile.ZipFile(io.BytesIO(wrapper)) as z:
        rows=z.infolist();need(len(rows)==1 and rows[0].filename=='saved-collection.json' and not rows[0].is_dir(),'receipt ZIP closure')
        r=rows[0];mode=r.external_attr>>16
        need(not r.flag_bits&1 and (stat.S_IFMT(mode) in (0,stat.S_IFREG)) and r.file_size<=LIMIT,'ordinary bounded unencrypted receipt')
        saved_raw=z.read(r)
    s=strict(saved_raw);need(type(s) is dict and set(s)==SAVED,'closed saved receipt')
    need(s['schema']=='boopa-saved-collection-v1' and s['repository']==REPO and s['run_id']==c['run_id'] and s['run_attempt']==c['run_attempt'],'saved producer identity')
    need(s['scraper_outcome']==s['save_outcome']=='success' and s['tracker_commit']==c['saved_commit'],'saved original outcomes/commit')
    need(s['collection_receipt_sha256']==sha(collection_raw),'saved exact collection receipt')
    col=strict(collection_raw);eligible(col,c)
    need(type(cm) is dict and cm.get('sha')==c['saved_commit'] and type(cm.get('tree')) is dict and digest(cm['tree'].get('sha'),40),'saved commit/root observation')
    evidence={name:{'bytes':len(raw),'sha256':sha(raw)} for name,raw in [('context.json',context_raw),('artifact.json',artifact_raw),('receipt.zip',wrapper),('collection_receipt.json',collection_raw),('saved-commit.json',commit_raw),('workflow.yml',workflow_raw),('saved-collection.json',saved_raw)]}
    return {'schema':'boopa-same-workflow-saved-selection-r2','repository':REPO,'saved_commit':c['saved_commit'],'saved_root':cm['tree']['sha'],'run_id':c['run_id'],'run_attempt':c['run_attempt'],'workflow_file_commit':c['workflow_sha'],'collector_checkout_commit':col['source_commit'],'artifact_id':c['artifact_id'],'artifact_wrapper_sha256':sha(wrapper),'saved_collection_sha256':sha(saved_raw),'collection_receipt_sha256':sha(collection_raw),'bounded_segment_eligible':True,'whole_catalog_complete':False,'collection_completion_verified':False,'price_source_is_latest':False,'workflow_run_completion_claimed':False,'authenticated_context_verified':False,'publication_authorized':False,'scope':'Exact same-workflow assertions and receipt bytes only; trusted runner/API acquisition remains a separate required adapter boundary.','evidence':evidence}
