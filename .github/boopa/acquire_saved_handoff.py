"""GET-only Actions acquisition. Import has no environment/network side effects.
Live entry is explicit; synthetic transport never establishes provider authority.
"""
import base64, hashlib, http.client, json, re, time
from urllib.parse import urlsplit, parse_qs
import verify_saved_handoff as selector
API='https://api.github.com/repos/'+selector.REPO
VERSION='2022-11-28'
MAX_BODY=65536
ENV={'server_url':'GITHUB_SERVER_URL','actions':'GITHUB_ACTIONS','repository':'GITHUB_REPOSITORY','repository_id':'GITHUB_REPOSITORY_ID','run_id':'GITHUB_RUN_ID','run_attempt':'GITHUB_RUN_ATTEMPT','workflow_ref':'GITHUB_WORKFLOW_REF','workflow_sha':'GITHUB_WORKFLOW_SHA'}
def require(v,m):
    if not v: raise ValueError('Actions acquisition: '+m)
def raw(v):return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def capture(env,needs):
    require(type(needs) is dict and set(needs)=={'result','saved_commit','artifact_id','artifact_digest'},'closed scrape outputs')
    c={k:env.get(v) for k,v in ENV.items()}
    require(all(type(v) is str and 0<len(v)<=512 for v in c.values()),'runner variables')
    require(c['server_url']=='https://github.com' and c['actions']=='true' and c['repository']==selector.REPO,'runner origin')
    require(c['repository_id']==str(selector.REPO_ID),'repository ID');c['repository_id']=selector.REPO_ID
    require(all(selector.ident(c[k]) for k in ('run_id','run_attempt')),'run identity')
    require(c['workflow_ref']==selector.REPO+'/'+selector.PATH+'@refs/heads/main' and selector.digest(c['workflow_sha'],40),'workflow identity')
    require(needs['result']=='success' and selector.ident(needs['artifact_id']) and selector.digest(needs['saved_commit'],40),'scrape output identity')
    require(type(needs['artifact_digest']) is str and re.fullmatch('sha256:[0-9a-f]{64}',needs['artifact_digest']),'artifact digest')
    c.update(schema='boopa-same-workflow-context-r2',scrape_job_result=needs['result'],**{k:needs[k] for k in ('saved_commit','artifact_id','artifact_digest')})
    return c

def storage_url(url):
    require(type(url) is str and len(url)<=8192 and all(32<ord(c)<127 for c in url),'redirect URL bounds')
    u=urlsplit(url)
    require(u.scheme=='https' and u.username is None and u.password is None and u.port is None and not u.fragment,'redirect origin')
    require(re.fullmatch(r'[a-z0-9]{3,24}\.blob\.core\.windows\.net',u.netloc or '') is not None,'unsupported artifact storage host')
    require(re.fullmatch(r'/[A-Za-z0-9_-]+/[A-Za-z0-9/_\.\-]+',u.path or '') is not None and all(p not in ('','.','..') for p in u.path.split('/')[1:]),'storage path')
    q=parse_qs(u.query,keep_blank_values=True,strict_parsing=True)
    require(all(len(v)==1 for v in q.values()) and q.get('sig',[''])[0] and q.get('se',[''])[0] and q.get('sp')==['r'],'read-only signed storage URL')
    return url

class HTTPSGet:
    """No automatic redirects, auth lookup, cookies, proxy, retries or URL logging."""
    def __call__(self,url,headers,limit):
        u=urlsplit(url);conn=None
        try:
            conn=http.client.HTTPSConnection(u.hostname,timeout=10)
            conn.request('GET',u.path+('?' + u.query if u.query else ''),headers=headers)
            res=conn.getresponse();pairs=res.getheaders();out={}
            for k,v in pairs:
                k=k.lower();require(k not in out,'duplicate response header');out[k]=v
            require(out.get('content-encoding','identity')=='identity','encoded response')
            if 'content-length' in out:require(out['content-length'].isdigit() and int(out['content-length'])<=limit,'response length')
            body=res.read(limit+1);require(len(body)<=limit,'response bound')
            if 'content-length' in out:require(len(body)==int(out['content-length']),'truncated response')
            return res.status,out,body
        except Exception:
            raise ValueError('Actions acquisition: GET failed or response invalid') from None
        finally:
            if conn is not None:conn.close()

def acquire(env,needs,workflow_sha256,transport,*,clock=time.monotonic):
    """Inject transport for tests. Env token read only here, after context validation."""
    c=capture(env,needs);require(selector.digest(workflow_sha256),'external workflow pin')
    token=env.get('GITHUB_TOKEN');require(type(token) is str and re.fullmatch(r'[A-Za-z0-9_\.\-]{1,4096}',token),'runtime token required')
    start=clock();calls=0;evidence=[]
    def get(url,auth=True,status=200):
        nonlocal calls
        require(calls<6 and clock()-start<90,'request budget');calls+=1
        if auth:require(url.startswith(API+'/') and not any(x in url for x in ('#','\\','\r','\n')),'fixed API boundary')
        else:storage_url(url)
        headers={'Accept':'application/vnd.github+json','Accept-Encoding':'identity','User-Agent':'boopa-saved-read-r1'}
        if auth:headers.update(Authorization='Bearer '+token,**{'X-GitHub-Api-Version':VERSION})
        try:code,h,b=transport(url,headers,MAX_BODY)
        except Exception:raise ValueError('Actions acquisition: transport failure') from None
        require(type(code) is int and code==status,'unexpected status; no retry')
        require(type(h) is dict and type(b) is bytes and len(b)<=MAX_BODY,'bounded transport response')
        require(h.get('content-encoding','identity')=='identity','encoded response')
        # Signed URL and headers/token are intentionally absent from returned evidence.
        evidence.append({'kind':'github-api' if auth else 'credential-free-artifact-storage','status':code,'bytes':len(b),'sha256':selector.sha(b)})
        return h,b
    _,a=get(API+'/actions/artifacts/'+c['artifact_id'])
    artifact=selector.strict(a)
    base=API+'/actions/artifacts/'+c['artifact_id']
    require(type(artifact) is dict and artifact.get('url')==base and artifact.get('archive_download_url')==base+'/zip','artifact endpoint relation')
    h,_=get(base+'/zip',status=302)
    location=h.get('location');storage_url(location)
    _,wrapper=get(location,False)
    require('sha256:'+selector.sha(wrapper)==c['artifact_digest'],'wrapper pin before further reads')
    _,commit=get(API+'/git/commits/'+c['saved_commit'])
    def contents(path,ref):
        _,data=get(API+'/contents/'+path+'?ref='+ref)
        v=selector.strict(data)
        require(type(v) is dict and v.get('type')=='file' and v.get('path')==path and v.get('encoding')=='base64','contents file shape')
        require(type(v.get('content')) is str and type(v.get('size')) is int and 0<v['size']<=MAX_BODY,'contents bounds')
        try:b=base64.b64decode(v['content'].replace('\n',''),validate=True)
        except Exception:raise ValueError('Actions acquisition: base64') from None
        require(len(b)==v['size'] and hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==v.get('sha'),'contents Git blob')
        return b
    collection=contents('data/collection_receipt.json',c['saved_commit'])
    workflow=contents(selector.PATH,c['workflow_sha'])
    result=selector.verify(raw(c),a,wrapper,collection,commit,workflow,workflow_sha256)
    return {'selection':result,'acquisition':{'schema':'boopa-actions-read-acquisition-r1','requests':calls,'observations':evidence,'runtime_execution_attested':False,'scope':'GET transport and explicit runner capture; synthetic invocation is not real Actions execution.'},'inputs':{'context.json':raw(c),'artifact.json':a,'receipt.zip':wrapper,'collection_receipt.json':collection,'saved-commit.json':commit,'workflow.yml':workflow}}

def acquire_current_actions(needs,workflow_sha256):
    """Explicit runtime entry. Never called on import or by local tests."""
    import os
    return acquire(os.environ,needs,workflow_sha256,HTTPSGet())
