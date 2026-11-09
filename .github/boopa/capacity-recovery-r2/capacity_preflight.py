"""Opt-in disposable SDK cleanup for a reviewed GitHub-hosted Linux job only."""
import argparse,json,os,platform,re,shutil,signal,stat,time
from pathlib import Path
REQUIRED=20*1024**3
TARGETS=('/usr/local/lib/android','/usr/share/dotnet')
def need(ok,msg):
 if not ok:raise ValueError('capacity preflight: '+msg)
def resolved(value):
 p=Path(value);need(p.is_absolute() and p.resolve(strict=True)==p and p.is_dir(),'resolved directory');return p
def context(env):
 need(platform.system()=='Linux' and env.get('GITHUB_ACTIONS')=='true' and env.get('RUNNER_ENVIRONMENT')=='github-hosted' and env.get('RUNNER_OS')=='Linux','hosted Linux context')
 need(env.get('GITHUB_REPOSITORY')=='MametaroGG/booth-vrc-price-tracker','repository')
 need(env.get('ImageOS') in ('ubuntu22','ubuntu24','ubuntu26') and re.fullmatch(r'\d{8}\.\d+(?:\.\d+)?',env.get('ImageVersion','')),'hosted image')
 return resolved(env['RUNNER_TEMP']),resolved(env['GITHUB_WORKSPACE'])
def mountpoints(raw):
 def decode(s):return re.sub(r'\\([0-7]{3})',lambda m:chr(int(m[1],8)),s)
 out=[]
 for line in raw.splitlines():
  parts=line.split();need(len(parts)>6 and '-' in parts,'mountinfo');out.append(Path(decode(parts[4])))
 return out
def overlaps(a,b):return a==b or a in b.parents or b in a.parents
def inspect(path,protected,mounts,device,*,limit=1000000,seconds=180):
 p=Path(path);need(p.is_absolute(),'absolute SDK');need(not any(overlaps(p,x) for x in protected),'protected overlap')
 for a in (p,*p.parents):need(not a.is_symlink(),'symlink ancestor')
 if not p.exists():return None
 need(not any(x==p or p in x.parents for x in mounts),'SDK mountpoint')
 root=p.lstat();need(stat.S_ISDIR(root.st_mode) and root.st_dev==device,'SDK directory/device')
 start=time.monotonic();count=0
 def walk(fd,depth):
  nonlocal count
  need(depth<=64 and time.monotonic()-start<seconds,'scan budget')
  for name in os.listdir(fd):
   count+=1;need(count<=limit and time.monotonic()-start<seconds,'scan budget')
   s=os.stat(name,dir_fd=fd,follow_symlinks=False);need(s.st_dev==device,'nested device')
   need(stat.S_ISREG(s.st_mode) or stat.S_ISLNK(s.st_mode) or stat.S_ISDIR(s.st_mode),'special entry')
   if stat.S_ISDIR(s.st_mode):
    child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
    try:
     actual=os.fstat(child);need((actual.st_dev,actual.st_ino)==(s.st_dev,s.st_ino),'directory changed');walk(child,depth+1)
    finally:os.close(child)
 fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:
  need((os.fstat(fd).st_dev,os.fstat(fd).st_ino)==(root.st_dev,root.st_ino),'root changed');walk(fd,0)
 finally:os.close(fd)
 return (root.st_dev,root.st_ino)
def remove_validated(path,identity):
 need(str(path) in TARGETS,'fixed allowlist only');need(shutil.rmtree.avoids_symlink_attacks,'fd safe rmtree required')
 parent=os.open(Path(path).parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:
  s=os.stat(Path(path).name,dir_fd=parent,follow_symlinks=False);need(stat.S_ISDIR(s.st_mode) and (s.st_dev,s.st_ino)==identity,'SDK replaced');shutil.rmtree(Path(path).name,dir_fd=parent)
 finally:os.close(parent)
def run(env,cleanup=False,*,free=lambda p:shutil.disk_usage(p).free,mountread=lambda:Path('/proc/self/mountinfo').read_text(),scan=inspect,remove=remove_validated,euid=os.geteuid):
 temp,workspace=context(env)
 def available():
  v=free(temp);need(type(v) is int and v>=0,'free byte count');print(json.dumps({'free_bytes':v,'required_bytes':REQUIRED}),flush=True);return v
 before=available()
 if before>=REQUIRED:return {'ready':True,'removed':[],'before':before,'after':before}
 if not cleanup:return {'ready':False,'removed':[],'before':before,'after':before}
 need(euid()==0,'cleanup must be explicitly invoked by root');need(shutil.rmtree.avoids_symlink_attacks,'fd safe rmtree required')
 protected=(temp,workspace);device=temp.stat().st_dev
 approved={p:scan(p,protected,mountpoints(mountread()),device) for p in TARGETS};removed=[];after=before
 for p,identity in approved.items():
  if identity is None:continue
  need(scan(p,protected,mountpoints(mountread()),device)==identity,'SDK changed after preflight');remove(p,identity);removed.append(p);after=available()
  if after>=REQUIRED:break
 return {'ready':after>=REQUIRED,'removed':removed,'before':before,'after':after}
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--cleanup-preinstalled-sdks',action='store_true');v=a.parse_args()
 signal.signal(signal.SIGALRM,lambda *_:(_ for _ in ()).throw(TimeoutError('capacity preflight deadline')));signal.alarm(300)
 try:
  result=run(os.environ,v.cleanup_preinstalled_sdks);print(json.dumps(result));raise SystemExit(0 if result['ready'] else 1)
 finally:signal.alarm(0)
