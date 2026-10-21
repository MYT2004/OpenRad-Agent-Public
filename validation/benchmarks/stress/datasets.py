"""Explicit complete SlicerRT data fetch with streaming hashes and no overwrites."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import quote
import hashlib
import json
import os
import tempfile
import time
from validation.benchmarks.slicerrt.runner import checked_path

MANIFEST=Path(__file__).with_name('full_slicerrt_manifest.json')


def hashes(stream,size,output=None):
    git=hashlib.sha1(b'blob '+str(size).encode()+b'\0');sha=hashlib.sha256();count=0
    for chunk in iter(lambda:stream.read(1024*1024),b''):
        count+=len(chunk)
        if count>size:raise ValueError('Oversized source')
        git.update(chunk);sha.update(chunk)
        if output:output.write(chunk)
    return count,git.hexdigest(),sha.hexdigest()


def fetch_one(root,commit,item,reuse):
    dest=checked_path(root,item['path'])
    if dest.exists():
        with dest.open('rb') as source:count,git,sha=hashes(source,item['size'])
        if count!=item['size'] or git!=item['sha']:raise ValueError('Existing source differs; refusing replacement')
        return sha
    dest.parent.mkdir(parents=True,exist_ok=True)
    local=checked_path(reuse,item['path'])
    for attempt in range(3):
        try:
            with tempfile.NamedTemporaryFile(dir=dest.parent,prefix='.download-') as stage:
                source=local.open('rb') if local.is_file() else urlopen('https://raw.githubusercontent.com/SlicerRt/SlicerRtData/'+commit+'/'+quote(item['path'],safe='/'),timeout=60)
                with source:count,git,sha=hashes(source,item['size'],stage)
                if count!=item['size'] or git!=item['sha']:raise ValueError('Downloaded source differs')
                stage.flush();os.fsync(stage.fileno());os.link(stage.name,dest)
            return sha
        except (OSError,ValueError):
            if attempt==2:raise
            time.sleep(attempt+1)


def main():
    manifest=json.loads(MANIFEST.read_text());commit=manifest['commit']
    root=Path('data/raw/slicerrt-full').absolute()/commit
    reuse=Path('data/raw/slicerrt').absolute()/commit
    failures=[];done=0;start=time.monotonic()
    with ThreadPoolExecutor(max_workers=12) as pool:
        work={pool.submit(fetch_one,root,commit,item,reuse):index for index,item in enumerate(manifest['files'])}
        for future in as_completed(work):
            try:future.result()
            except Exception:failures.append(work[future])
            done+=1
            if done%250==0:print(json.dumps({'completed':done,'total':len(work),'failures':len(failures)}),flush=True)
    print(json.dumps({'files':done,'failed_entry_indices':failures,'seconds':round(time.monotonic()-start,1),'source_commit':commit}),flush=True)
    if failures:raise SystemExit(2)


if __name__=='__main__':main()
