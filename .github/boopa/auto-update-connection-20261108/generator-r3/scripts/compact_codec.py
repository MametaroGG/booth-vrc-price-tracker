"""Lossless self-contained search core codec. No I/O during import."""
import json
def utf16_length(text):return len(text.encode('utf-16-le',errors='surrogatepass'))//2
KEYS={'schema','format','layout','categories','shops','tags','data'}
def encode(rows,layout='columns'):
 if layout not in ('columns','rows'): raise ValueError('layout')
 dictionaries=[[],[],[]]; indices=[{}, {}, {}]; encoded=[]
 def ref(value,k):
  if type(value) is not str: raise ValueError('dictionary fields must be strings')
  if value not in indices[k]: indices[k][value]=len(dictionaries[k]);dictionaries[k].append(value)
  return indices[k][value]
 for row in rows:
  if type(row) is not list or len(row)!=14: raise ValueError('row width')
  r=row.copy();r[7]=ref(row[7],0);r[12]=ref(row[12],1)
  if type(row[13]) is not str: raise ValueError('tag field')
  r[13]=[ref(t,2) for t in row[13].split(' ')];encoded.append(r)
 data=[[r[i] for r in encoded] for i in range(14)] if layout=='columns' else encoded
 return dict(schema=1,format='compact-core-v1',layout=layout,categories=dictionaries[0],shops=dictionaries[1],tags=dictionaries[2],data=data)
def decode(obj):
 if type(obj) is not dict or set(obj)!=KEYS or type(obj['schema']) is not int or obj['schema']!=1 or obj['format']!='compact-core-v1' or obj['layout'] not in ('columns','rows'): raise ValueError('schema')
 dictionaries=[obj[k] for k in ('categories','shops','tags')]
 for d in dictionaries:
  if type(d) is not list or len(d)>1000000 or any(type(s) is not str for s in d) or len(set(d))!=len(d): raise ValueError('dictionary')
  lengths=[utf16_length(s) for s in d]
  if any(n>65536 for n in lengths) or sum(lengths)>4194304:raise ValueError('dictionary expansion budget')
 data=obj['data']
 if type(data) is not list: raise ValueError('data')
 if obj['layout']=='columns':
  if len(data)!=14 or any(type(c) is not list for c in data) or len({len(c) for c in data})!=1: raise ValueError('columns')
  rows=[list(r) for r in zip(*data)]
 else:
  if any(type(r) is not list or len(r)!=14 for r in data): raise ValueError('rows')
  rows=[r.copy() for r in data]
 if len(rows)>100000:raise ValueError('row expansion budget')
 def resolve(i,k):
  if type(i) is not int or not 0<=i<len(dictionaries[k]): raise ValueError('reference')
  return dictionaries[k][i]
 decoded_tag_chars=0
 for r in rows:
  if r[9]!='':raise ValueError('image-free field')
  r[7]=resolve(r[7],0);r[12]=resolve(r[12],1)
  if type(r[13]) is not list or not r[13] or len(r[13])>4096: raise ValueError('tag references')
  tokens=[resolve(i,2) for i in r[13]]
  chars=sum(utf16_length(t) for t in tokens)+len(tokens)-1
  decoded_tag_chars+=chars
  if chars>65536 or decoded_tag_chars>33554432:raise ValueError('tag expansion budget')
  r[13]=' '.join(tokens)
 return rows
def exact(a,b):
 if type(a) is not type(b): return False
 if isinstance(a,list): return len(a)==len(b) and all(exact(x,y) for x,y in zip(a,b))
 if isinstance(a,dict): return a.keys()==b.keys() and all(exact(a[k],b[k]) for k in a)
 return a==b
def serialize(value):return (json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
