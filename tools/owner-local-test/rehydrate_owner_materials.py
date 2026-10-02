#!/usr/bin/env python3
"""Rehydrate hash-pinned owner materials; never execute extracted upstream content."""
import argparse,base64,hashlib,json,os,re,tarfile,tempfile,urllib.request,urllib.parse,zipfile
from pathlib import Path,PurePosixPath
from concurrent.futures import ThreadPoolExecutor,as_completed

def digest(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  while b:=f.read(1024*1024):h.update(b)
 return h.hexdigest()
def safe(s):
 if not isinstance(s,str) or not s or '\\' in s or '\x00' in s or s.startswith('/') or ':' in s or any(x in ('','..','.') for x in s.split('/')):raise ValueError('Unsafe path')
 return s
def checked_file(base,path):
 safe(path);p=base/path
 if not p.resolve().is_relative_to(base.resolve()) or any(x.is_symlink() for x in [p,*list(p.parents)[:len(PurePosixPath(path).parts)]]):raise ValueError('Symlink/escape')
 return p
def write(base,path,data,rec):
 if len(data)!=rec['bytes'] or hashlib.sha256(data).hexdigest()!=rec['sha256']:raise ValueError('Material hash/size mismatch: '+path)
 p=checked_file(base,path)
 if p.exists():raise ValueError('Duplicate material target: '+path)
 p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
 def __init__(self,hosts):super().__init__();self.hosts=set(hosts)
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  u=urllib.parse.urlsplit(newurl)
  if u.scheme!='https' or u.username or u.password or u.hostname not in self.hosts or u.hostname not in {'download.qt.io','files.pythonhosted.org','static.crates.io','mirrors.20i.com','www.mirrorservice.org'} or u.port not in (None,443):raise ValueError('Unapproved redirect host/protocol')
  return super().redirect_request(req,fp,code,msg,headers,newurl)
def obtain(arc,cache):
 safe(arc['filename']);p=checked_file(cache,arc['filename'])
 if p.exists():
  if p.stat().st_size!=arc['bytes'] or digest(p)!=arc['sha256']:raise ValueError('Existing archive hash mismatch')
  return p
 request_url=arc.get('download_url',arc['url']);u=urllib.parse.urlsplit(request_url)
 if u.scheme!='https' or u.hostname not in {'download.qt.io','files.pythonhosted.org','static.crates.io','mirrors.20i.com','www.mirrorservice.org'} or u.username or u.password or u.query or u.fragment:raise ValueError('Unapproved archive URL')
 opener=urllib.request.build_opener(HTTPSRedirect(arc.get('redirect_hosts',[u.hostname])));h=hashlib.sha256();size=0
 temp=p.with_suffix(p.suffix+'.part')
 if temp.exists():raise ValueError('Existing partial download')
 try:
  with opener.open(request_url,timeout=180) as response,temp.open('xb') as out:
   while chunk:=response.read(1024*1024):
    size+=len(chunk)
    if size>arc['bytes']:raise ValueError('Archive exceeds exact size')
    h.update(chunk);out.write(chunk)
  if size!=arc['bytes'] or h.hexdigest()!=arc['sha256']:raise ValueError('Archive hash/size mismatch')
  temp.rename(p)
 finally:
  if temp.exists():temp.unlink()
 return p

def archive_selections(files,archives):
 ids={a['id'] for a in archives}
 if len(ids)!=len(archives) or len({a['filename'].casefold() for a in archives})!=len(archives):raise ValueError('Duplicate archive descriptor')
 selected={}
 for rec in files.values():
  if rec['source_kind']!='archive':continue
  aid=rec.get('archive_id')
  if aid not in ids:raise ValueError('Unknown archive reference')
  selected.setdefault(aid,{}).setdefault(safe(rec['archive_member']),[]).append(rec)
 return selected

def prefetch_archives(archives,cache,obtain_fn=obtain):
 # Fixed bounded download-only concurrency. Extraction stays sequential below.
 if len({a['id'] for a in archives})!=len(archives):raise ValueError('Duplicate prefetch archive')
 results={}
 with ThreadPoolExecutor(max_workers=8) as pool:
  futures={pool.submit(obtain_fn,arc,cache):arc['id'] for arc in archives}
  for future in as_completed(futures):results[futures[future]]=future.result()
 return results

def extract_selected(archive,selection,output):
 seen=set();found=set()
 with tarfile.open(archive,'r|*') as stream:
  for member in stream:
   name=member.name.rstrip('/')
   safe(name)
   if name in seen:raise ValueError('Duplicate archive member: '+name)
   seen.add(name)
   if name not in selection:continue
   if not member.isfile() or member.issym() or member.islnk():raise ValueError('Selected archive member is not a regular file')
   recs=selection[name]
   if any(member.size!=r['bytes'] for r in recs):raise ValueError('Selected member size mismatch')
   data=stream.extractfile(member).read(member.size+1)
   for rec in recs:write(output,rec['path'],data,rec)
   found.add(name)
 if found!=set(selection):raise ValueError('Missing selected archive member')

def deterministic_zip(content,output,files):
 items=[]
 if len(files)>20000 or sum(r['bytes'] for r in files.values())>500_000_000:raise ValueError('Materials exceed bounded ZIP profile')
 for rec in sorted(files.values(),key=lambda x:x['path']):
  p=checked_file(content,rec['path'])
  if p.stat().st_size!=rec['bytes'] or digest(p)!=rec['sha256']:raise ValueError('Final content verification failed')
  items.append({k:rec[k] for k in ('path','bytes','sha256')})
 manifest=json.dumps({'schema_version':1,'files':items},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
 with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED,allowZip64=False) as z:
  for name,data in [('CONTENT-MANIFEST.json',manifest)]+[(r['path'],(content/r['path']).read_bytes()) for r in items]:
   zi=zipfile.ZipInfo(name,(1980,1,1,0,0,0));zi.create_system=3;zi.external_attr=(0o100644<<16);zi.compress_type=zipfile.ZIP_STORED;z.writestr(zi,data)
 with zipfile.ZipFile(output) as z:
  if len(z.namelist())!=len(set(z.namelist())):raise ValueError('Duplicate zip path')
  for r in items:
   if hashlib.sha256(z.read(r['path'])).hexdigest()!=r['sha256']:raise ValueError('Final zip content mismatch')
 return items

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True,type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--cache',type=Path);a=p.parse_args();index=json.loads(a.manifest.read_text(encoding='utf-8'));base=a.manifest.parent.resolve()
 if not re.fullmatch('[0-9a-f]{64}',str(index.get('expected_package_sha256',''))):raise ValueError('Mandatory final package SHA256 missing/invalid')
 if index.get('schema_version')!=1 or not re.fullmatch('[0-9a-f]{40}',index.get('source_commit','')):raise ValueError('Invalid root manifest')
 if a.output.is_symlink() or a.output.exists() and any(a.output.iterdir()):raise ValueError('Output must be new/empty, not a symlink')
 a.output.mkdir(parents=True,exist_ok=True);out=a.output.resolve();content=out/'content';content.mkdir();files={};chunks={};names=set();archives=list(index.get('archives',[]))
 for shard in index['shards']:
  path=checked_file(base,shard['path']);raw=path.read_bytes()
  if len(raw)>100000 or len(raw)!=shard['bytes'] or hashlib.sha256(raw).hexdigest()!=shard['sha256']:raise ValueError('Shard hash/size mismatch')
  for r in json.loads(raw):
   if r.get('kind')=='archive':
    archives.append({k:v for k,v in r.items() if k!='kind'});continue
   path=safe(r['path'])
   if r['kind']=='file':
    if path in files or path.casefold() in names:raise ValueError('Duplicate/case-colliding path')
    if not re.fullmatch('[0-9a-f]{64}',r.get('sha256','')) or not 0<=r['bytes']<=20_000_000:raise ValueError('Invalid file record')
    files[path]=r;names.add(path.casefold())
   elif r['kind']=='chunk':chunks.setdefault(path,[]).append(r)
   else:raise ValueError('Unknown record kind')
 for path,rec in files.items():
  if rec['source_kind']=='inline':
   data=bytearray();parts=sorted(chunks.pop(path,[]),key=lambda x:x['offset'])
   for part in parts:
    if part['offset']!=len(data):raise ValueError('Inline overlap/gap/duplicate')
    data.extend(base64.b64decode(part['data'],validate=True))
    if len(data)>rec['bytes']:raise ValueError('Inline content exceeds size')
   write(content,path,data,rec)
  elif rec['source_kind']!='archive':raise ValueError('Unknown source kind')
 if chunks:raise ValueError('Orphan inline chunk')
 with tempfile.TemporaryDirectory(prefix='owner-materials-cache-') as temp:
  cache=a.cache.resolve() if a.cache else Path(temp);cache.mkdir(parents=True,exist_ok=True)
  selected=archive_selections(files,archives)
  active=[arc for arc in archives if arc['id'] in selected]
  retrieved=prefetch_archives(active,cache)
  for arc in active:extract_selected(retrieved[arc['id']],selected[arc['id']],content)
 package=out/'owner-source-and-notices.zip';listing=deterministic_zip(content,package,files)
 expected=index.get('expected_package_sha256')
 if digest(package)!=expected:raise ValueError('Deterministic package hash mismatch')
 review={k:index[k] for k in ['schema_version','source_commit','review_id','owner_test_materials_approved','source_replacement_review_approved','unresolved_materials']}
 review['additional_materials']=[{'path':package.name,'sha256':digest(package)}]
 (out/'materials-review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'files':len(listing),'package_sha256':digest(package),'bytes':package.stat().st_size,'review_approved':review['owner_test_materials_approved']}))
if __name__=='__main__':main()
