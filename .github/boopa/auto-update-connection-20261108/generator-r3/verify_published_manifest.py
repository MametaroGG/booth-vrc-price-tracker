#!/usr/bin/env python3
"""Bounded read-only HTTPS check after Pages publication; never deploys or retries push."""
import argparse
import hashlib
import json
import re
import time
from urllib.parse import urlparse
from urllib.request import Request,urlopen


def verify(url,expected_sha,wait_seconds=120):
    parsed=urlparse(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Explicit credential-free HTTPS manifest URL required')
    if not re.fullmatch('[0-9a-f]{64}',expected_sha) or not 0<=wait_seconds<=600:
        raise ValueError('Expected SHA256 and bounded 0..600 second window required')
    deadline=time.monotonic()+wait_seconds;last='not checked'
    while True:
        try:
            request=Request(url,headers={'Cache-Control':'no-cache','User-Agent':'BoopaDB-manifest-verifier/1'})
            with urlopen(request,timeout=15) as response:
                if urlparse(response.geturl()).scheme!='https':raise ValueError('HTTPS downgrade refused')
                data=response.read(8*1024*1024+1)
            if len(data)>8*1024*1024:raise ValueError('Manifest response too large')
            actual=hashlib.sha256(data).hexdigest()
            if actual==expected_sha:
                return {'verified':True,'url':url,'sha256':actual,'bytes':len(data)}
            last='hash mismatch: '+actual
        except Exception as exc:last=str(exc)
        remaining=deadline-time.monotonic()
        if remaining<=0:return {'verified':False,'url':url,'expected_sha256':expected_sha,'last_observation':last}
        time.sleep(min(10,remaining))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',required=True);p.add_argument('--expected-sha256',required=True);p.add_argument('--wait-seconds',type=int,default=120)
    a=p.parse_args();result=verify(a.url,a.expected_sha256,a.wait_seconds);print(json.dumps(result,indent=2));raise SystemExit(0 if result['verified'] else 1)
