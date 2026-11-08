#!/usr/bin/env python3
"""Generate versioned, lossless search core + lazy thumbnails. Legacy index is untouched."""
import argparse,hashlib,json,pathlib,collections,os

def encode(value):return json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8')
def build(source,output):
 blobs=[(source/f'search_index_{i}.json').read_bytes() for i in range(24)]
 revision=hashlib.sha256(b'boopadb-lean-core-v2\0'+b''.join(blobs)).hexdigest()[:20]
 prefix=f'catalog-v2/{revision}/';target=output/prefix;target.mkdir(parents=True,exist_ok=True)
 categories=[];shops=[];cats={};shopids={};thumbnails=collections.defaultdict(list);row_ids=set();parts=[]
 def intern(value,values,lookup):
  if value not in lookup:lookup[value]=len(values);values.append(value)
  return lookup[value]
 def write(name,payload):
  data=encode({'schema':2,'revision':revision,**payload});path=target/name;path.write_bytes(data)
  return {'path':prefix+name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
 for blob in blobs:
  rows=json.loads(blob);packed=[]
  for row in rows:
   if len(row)!=14:raise ValueError('14-column source required')
   id,name,cur,base,lowest,sale,atlow,category,likes,image,date,perday,shop,tags=row
   if not isinstance(id,str) or not id.isdecimal() or str(int(id))!=id or id in row_ids:raise ValueError('Invalid/duplicate id')
   if sale not in (0,1) or atlow not in (0,1):raise ValueError('Invalid flags')
   if not all(isinstance(v,str) for v in (name,category,image,shop,tags)):raise ValueError('Invalid strings')
   row_ids.add(id);ci=intern(category,categories,cats);si=intern(shop,shops,shopids)
   value=[int(id),name,cur,base,lowest,sale+2*atlow,ci,likes,date-20200000 if date else None,perday,si,tags]
   restored=[str(value[0]),name,cur,base,lowest,value[5]&1,value[5]>>1,categories[ci],likes,image,value[8]+20200000 if value[8] is not None else 0,perday,shops[si],tags]
   if restored!=row:raise ValueError('Non-lossless encoding')
   packed.append(value);thumbnails[id[:3]].append([id,image])
  parts.append(packed)
 dictionary=write('dictionary.json',{'categories':categories,'shops':shops})
 cores=[{**write(f'core-{i}.json',{'part':i,'rows':rows}),'rows':len(rows)} for i,rows in enumerate(parts)]
 thumbs={key:{**write(f'thumb-{key}.json',{'prefix':key,'images':rows}),'rows':len(rows)} for key,rows in sorted(thumbnails.items())}
 manifest={'schema':2,'revision':revision,'items':len(row_ids),'dictionary':dictionary,'cores':cores,'thumbnails':thumbs}
 data=encode(manifest);tmp=output/'search-catalog.json.tmp';tmp.write_bytes(data);tmp.replace(output/'search-catalog.json')
 result={'revision':revision,'items':len(row_ids),'core_raw_bytes':len(data)+dictionary['bytes']+sum(x['bytes'] for x in cores),'thumbnail_files':len(thumbs),'thumbnail_raw_bytes':sum(x['bytes'] for x in thumbs.values())}
 print(json.dumps(result));return result
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--source-root',type=pathlib.Path,default=pathlib.Path('.'));parser.add_argument('--output-root',type=pathlib.Path,default=pathlib.Path('.'));args=parser.parse_args();build(args.source_root,args.output_root)
