"""Exact-tree Git mechanics. No CLI, credentials, network setup or release authority.
Production entry remains disabled pending the real latest-negative/QA binding.
The internal mechanics are exercised only against a new local bare fixture.
"""
import hashlib,json,os,re,stat,subprocess,tempfile,configparser
from pathlib import Path

def need(v,message):
    if not v:raise ValueError(message)
def digest(raw):return hashlib.sha256(raw).hexdigest()
def oid(value):need(type(value) is str and re.fullmatch('[0-9a-f]{40}',value),'Invalid Git OID');return value
def safe_env(index=None):
    env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','GIT_TERMINAL_PROMPT':'0','GIT_NO_REPLACE_OBJECTS':'1'}
    if index is not None:
        need(Path(index).is_absolute(),'Index path must be absolute');env['GIT_INDEX_FILE']=str(index)
    return env

def inspect_repo(repo):
    root=Path(repo);need(root.is_absolute() and root.resolve()==root and root.is_dir(),'Explicit resolved repository required')
    gd=root/'.git' if (root/'.git').exists() else root
    if gd==root and not (root/'HEAD').exists():return root,None # local fixture init only
    need(gd.is_dir() and not gd.is_symlink(),'Linked/symlink worktree prohibited')
    for n in ('commondir','config.worktree','objects/info/alternates','objects/info/http-alternates','info/grafts'):
        need(not (gd/n).exists(),'Alternate repository state prohibited')
    need(not (gd/'refs/replace').exists(),'Replace refs prohibited')
    packed=gd/'packed-refs'
    if packed.exists():need(b'refs/replace/' not in packed.read_bytes(),'Packed replace refs prohibited')
    for n in ('config','objects','refs'):
        need(not (gd/n).is_symlink(),'Symlink repository state prohibited')
    cp=configparser.RawConfigParser(strict=True);cp.read(gd/'config')
    allowed={'core':{'repositoryformatversion','filemode','bare','logallrefupdates'},'user':{'name','email'},'remote "origin"':{'url','fetch'}}
    for section in cp.sections():
        need(section in allowed and set(cp[section])<=allowed[section],'Unsupported local Git configuration')
        if section=='remote "origin"':need(cp[section].get('url')=='https://github.com/MametaroGG/boopadb.git' and cp[section].get('fetch','') in ('','+refs/heads/*:refs/remotes/origin/*'),'Unsupported origin')
    return root,gd

def git_command(repo,args):
    root,gd=inspect_repo(repo)
    prefix=['/usr/bin/git','--no-replace-objects','-c','core.hooksPath=/dev/null','-c','credential.helper=','-c','http.sslVerify=true','-c','http.followRedirects=false']
    return prefix+(['--git-dir='+str(gd),'--work-tree='+str(root)] if gd else ['-C',str(root)])+list(args)
def git_bytes(repo,*args,input=None,env=None):
    need(env is None or set(env)=={'GIT_INDEX_FILE'},'Only explicit temporary index override permitted')
    return subprocess.check_output(git_command(repo,args),input=input,env=safe_env(None if env is None else env['GIT_INDEX_FILE']),stderr=subprocess.PIPE,timeout=120)
def git(repo,*args,input=None,env=None):return git_bytes(repo,*args,input=input,env=env).decode().strip()
def json_strict(raw):
    def pairs(items):
        result={}
        for k,v in items:need(k not in result,'Duplicate JSON key');result[k]=v
        return result
    return json.loads(raw,object_pairs_hook=pairs)
def safe_name(name):
    need(type(name) is str and name and not name.startswith('/') and '\\' not in name and all(x not in ('','.','..') for x in name.split('/')) and all(ord(c)>=32 for c in name),'Unsafe public path')
def stable_stat(s):return tuple(getattr(s,k) for k in ('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns'))
def read_regular(root,name):
    safe_name(name);fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in name.split('/')[:-1]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=child
        f=os.open(name.split('/')[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        try:
            before=os.fstat(f);need(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_size<=128*1024*1024,'Unsafe public file')
            with os.fdopen(os.dup(f),'rb') as stream:raw=stream.read(128*1024*1024+1)
            after=os.fstat(f);need(stable_stat(before)==stable_stat(after) and len(raw)==before.st_size,'Public file changed');return raw
        finally:os.close(f)
    finally:os.close(fd)
def snapshot(root,pin):
    raw=read_regular(root,'snapshot-manifest.json');need(digest(raw)==pin,'Snapshot pin differs');m=json_strict(raw)
    need(m.get('fixture') is False,'Fixture prohibited')
    entries=m['files'];need(type(entries) is dict and 'snapshot-manifest.json' not in entries,'Invalid manifest inventory')
    expected={**entries,'snapshot-manifest.json':pin};found=set()
    for parent,dirs,files in os.walk(root,followlinks=False):
        for n in dirs:need(not (Path(parent)/n).is_symlink(),'Symlink directory')
        for n in files:found.add((Path(parent)/n).relative_to(root).as_posix())
    need(found==set(expected),'Public closure differs')
    result={}
    for name,h in expected.items():
        b=read_regular(root,name);need(digest(b)==h,'Public bytes differ');result[name]=b
    return result

def tree_entries(repo,commit):
    raw=git_bytes(repo,'ls-tree','-r','-z',oid(commit))
    result={}
    for item in raw.split(b'\0'):
        if not item:continue
        meta,path=item.split(b'\t',1);mode,kind,h=meta.decode().split();name=path.decode();safe_name(name)
        need(kind=='blob' and mode in ('100644','100755'),'Non-regular baseline tree');result[name]=(mode,oid(h))
    return result

def prepare(repo,expected_parent,prior,prior_pin,candidate,candidate_pin,site_count=724,management_count=19):
    """Local objects only. Counts overridable solely for synthetic unit tests."""
    old=snapshot(prior,prior_pin);new=snapshot(candidate,candidate_pin)
    need(set(old)==set(new) and len(old)==site_count,'Public namespace differs')
    need(all(not n.startswith(('.github/','.git/')) and n not in ('.git','.github') for n in new),'Management path cannot be selected as public site')
    baseline=tree_entries(repo,expected_parent);need(set(old)<=set(baseline) and len(baseline)-len(old)==management_count,'Management closure differs')
    for name,raw in old.items():
        actual=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        need(baseline[name]==('100644',actual),'Prior public bytes not baseline')
    with tempfile.TemporaryDirectory() as td:
        env={'GIT_INDEX_FILE':str(Path(td)/'index')}
        git(repo,'read-tree',expected_parent,env=env)
        for name,raw in new.items():
            blob=git(repo,'hash-object','-w','--stdin',input=raw)
            git(repo,'update-index','-z','--index-info',input=('100644 '+oid(blob)+'\t'+name+'\0').encode(),env=env)
        tree=git(repo,'write-tree',env=env)
    after=tree_entries(repo,tree);need(set(after)==set(baseline),'Tree path closure differs')
    need(all(after[n]==entry for n,entry in baseline.items() if n not in old),'Management changed')
    return tree

def validate_commit(repo,commit,expected,tree):
    parts=git(repo,'rev-list','--parents','-n','1',oid(commit)).split()
    need(parts==[commit,oid(expected)],'Commit must have sole expected parent')
    need(git(repo,'rev-parse',commit+'^{tree}')==oid(tree),'Commit tree mismatch')
def remote_head(repo,remote):
    result=git(repo,'ls-remote','--exit-code',remote,'refs/heads/main').split()
    need(len(result)==2 and result[1]=='refs/heads/main','Ambiguous remote head');return oid(result[0])
def reconcile(repo,remote,expected,commit):
    current=remote_head(repo,remote)
    return {'status':'exact-commit-observed' if current==commit else 'unchanged' if current==expected else 'conflict','remote_head':current,'provider_authenticated':False,'publication_accepted':False}
def push_once(repo,remote,commit,expected,tree,journal):
    """Internal transport, no retries. Remote is production-validated by future entry.
    Lease only adds atomic expected-ref protection; sole-parent rejects rewrites.
    """
    validate_commit(repo,commit,expected,tree);need(remote_head(repo,remote)==expected,'Pre-push conflict')
    payload={'status':'push-pending','commit':commit,'expected_parent':expected,'tree':tree}
    with Path(journal).open('x') as f:json.dump(payload,f);f.flush();os.fsync(f.fileno())
    try:git(repo,'push','--porcelain','--force-with-lease=refs/heads/main:'+expected,remote,commit+':refs/heads/main')
    except (subprocess.TimeoutExpired,subprocess.CalledProcessError):
        # May be committed or rejected. Always observe; never blindly retry.
        return reconcile(repo,remote,expected,commit)
    return reconcile(repo,remote,expected,commit)
def publish(*args,**kwargs):
    raise ValueError('UNBOUND: current semantic/runtime/latest-negative release adapter and authenticated runner remain unaccepted; no production entry enabled')
