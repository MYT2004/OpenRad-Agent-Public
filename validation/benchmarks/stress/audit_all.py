"""Read-only full-corpus intake. Per-case faults are evidence, never source repairs."""
import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from src.case_verification import verify_patient_case, CaseVerificationRequest
from src.storage import StorageManager, session_scope
from src.agent_dynamic import run_dynamic_agent
from validation.paths import new_run_directory
from validation.benchmarks.stress.datasets import MANIFEST, hashes


def inventory(root):
    result={}
    for path in sorted(root.rglob('*')):
        if path.is_file():
            with path.open('rb') as stream:
                h=hashlib.sha256()
                for chunk in iter(lambda:stream.read(1048576),b''):h.update(chunk)
            result[str(path.relative_to(root))]=h.hexdigest()
    return result


def main():
    manifest=json.loads(MANIFEST.read_text());root=Path('data/raw/slicerrt-full')/manifest['commit']
    out=new_run_directory('full-corpus');out.mkdir(parents=True);manager=StorageManager(str(out/'sessions'))
    sources=[('public-'+str(i+1),root/name) for i,name in enumerate(manifest['datasets'])]
    base=Path('/Users/REDACTED_USER/Documents/OpenRad-Agent_OSI_2026/data/raw')
    sources += [('local-'+str(i+1),base/name) for i,name in enumerate(['HNSCC-01-0019','HNSCC-01-0176','HNSCC-01-0199'])]
    # Verify every downloaded byte against the Git source before processing.
    for item in manifest['files']:
        with (root/item['path']).open('rb') as stream:count,git,sha=hashes(stream,item['size'])
        if count!=item['size'] or git!=item['sha']:raise ValueError('Source hash mismatch')
    reports=[];start=time.monotonic()
    for label,source in sources:
        before=inventory(source)
        with session_scope(manager):
            try:
                result=verify_patient_case(CaseVerificationRequest(root=str(source),case_id=label,check_pixels=True))
                (out/(label+'.json')).write_text(json.dumps(result,indent=2))
                brief={'case':label,'status':result['status'],'files':len(before),'counts':result.get('counts'),
                    'findings':dict(Counter(f['code'] for f in result.get('findings',[]))),
                    'severity':dict(Counter(f['severity'] for f in result.get('findings',[])))}
            except Exception as exc:
                brief={'case':label,'status':'EXECUTION_ERROR','files':len(before),'error_type':type(exc).__name__}
            # Exercise the actual copilot intake path on every collection, no hosted data.
            copilot=run_dynamic_agent('Verify selected_case',case_directory=str(source))
            brief['copilot_status']=json.loads(copilot.trajectory[0]['observation'])['status'] if copilot.trajectory else 'NO_TOOL'
        after=inventory(source)
        brief['source_unchanged']=before==after
        if before!=after:raise RuntimeError('Raw data changed')
        reports.append(brief)
        print(json.dumps(brief),flush=True)
        (out/'assessment.json').write_text(json.dumps({'source_commit':manifest['commit'],'results':reports,'seconds':round(time.monotonic()-start,1)},indent=2))
    print('Evidence: '+str(out),flush=True)

if __name__=='__main__':main()
