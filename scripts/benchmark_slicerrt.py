"""Opt-in, pinned external-data benchmark. Never overwrite source inputs.

Run from the repository root with ``python -m scripts.benchmark_slicerrt fetch``
then ``python -m scripts.benchmark_slicerrt run``. No network is used by run.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import re
import tempfile
from urllib.parse import quote
from urllib.request import urlopen

import pydicom
from src.case_verification import CaseVerificationRequest, verify_patient_case, ensure_case_output_separation
from src.storage import StorageManager, session_scope
from src.readonly import assert_output_path


MANIFEST = Path(__file__).resolve().parents[1] / 'benchmarks/slicerrt_manifest.json'


def load_manifest(path=MANIFEST):
    manifest=json.loads(Path(path).read_text())
    if manifest['repository']!='https://github.com/SlicerRt/SlicerRtData' or not re.fullmatch(r'[0-9a-f]{40}',manifest['commit']):
        raise ValueError('Unrecognized benchmark source')
    for item in manifest['files']:
        path=PurePosixPath(item['path'])
        if path.is_absolute() or '..' in path.parts or '\\' in item['path'] or not 0<item['size']<=32*1024*1024 or not re.fullmatch(r'[0-9a-f]{40}',item['sha']):
            raise ValueError('Unsafe benchmark entry')
    if len({item['path'] for item in manifest['files']})!=len(manifest['files']):
        raise ValueError('Duplicate benchmark path')
    for case in manifest['cases']:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+',case['id']) or case['id'] in ('.','..'):
            raise ValueError('Unsafe benchmark case')
        sub=PurePosixPath(case['intake_subdir'])
        if sub.is_absolute() or '..' in sub.parts or '\\' in case['intake_subdir']:
            raise ValueError('Unsafe benchmark subdirectory')
    return manifest


def checked_path(root, relative):
    root=Path(root).absolute()
    candidate=root/relative
    if candidate.resolve()!=candidate or root not in candidate.parents:
        raise ValueError('Benchmark paths must not traverse symlinks or escape the cache')
    return candidate


def validate_blob(data, item):
    git_hash=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    if len(data)!=item['size'] or git_hash!=item['sha']:
        raise ValueError('Benchmark source size/hash mismatch')
    return hashlib.sha256(data).hexdigest()


def fetch_one(root, commit, item):
    destination=checked_path(root,item['path'])
    if destination.exists():
        return validate_blob(destination.read_bytes(),item)
    url='https://raw.githubusercontent.com/SlicerRt/SlicerRtData/'+commit+'/'+quote(item['path'],safe='/')
    with urlopen(url,timeout=60) as response:
        data=response.read(item['size']+1)
    sha=validate_blob(data,item)
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Atomic exclusive publication: an existing source is never replaced.
    with tempfile.NamedTemporaryFile(dir=destination.parent,prefix='.download-') as staged:
        staged.write(data);staged.flush();os.fsync(staged.fileno())
        os.link(staged.name,destination)
    return sha


def fetch(manifest,root):
    with ThreadPoolExecutor(max_workers=6) as pool:
        hashes=list(pool.map(lambda item:fetch_one(root,manifest['commit'],item),manifest['files']))
    return dict(files=len(hashes),bytes=sum(item['size'] for item in manifest['files']),source_commit=manifest['commit'])


def inventory(manifest,root):
    root=Path(root)
    actual={path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file() or path.is_symlink()}
    if actual!={item['path'] for item in manifest['files']}:
        raise ValueError('Benchmark cache has missing or unpinned extra inputs')
    return {item['path']:validate_blob(checked_path(root,item['path']).read_bytes(),item) for item in manifest['files']}


def run(manifest,root,output):
    root=Path(root).absolute();output=assert_output_path(output)
    ensure_case_output_separation(root,output)
    before=inventory(manifest,root)  # refuse incomplete or modified downloads
    manager=StorageManager(str(output/'sessions'))
    cases=[]
    for number,case in enumerate(manifest['cases'],1):
        case_root=checked_path(root,case['id'])/case['intake_subdir']
        with session_scope(manager):
            result=verify_patient_case(CaseVerificationRequest(root=str(case_root),case_id=f'external-{number:03d}'))
        cases.append({'dataset':case['id'],'status':result['status'],'counts':result['counts'],
                      'findings':result['findings_summary'],
                      'report':str(Path('sessions')/result['session_id']/'artifacts'/Path(result['artifacts'][0]).name),
                      'verification_hash':result['verification_hash'],
                      'expected_findings_present':set(case.get('expected_findings',[]))<=set(f['code'] for f in result['findings'])})
    comparison=None;topology=None
    if manifest.get('comparison_profile')=='eclipse-prostate-1':
        from scripts.slicerrt_reference import compare_prostate,probe_keyhole_topology
        comparison=compare_prostate(root,manager)
        topology=probe_keyhole_topology(root)
    after=inventory(manifest,root)
    if before!=after:raise ValueError('Source inventory changed during benchmark')
    result={'source_repository':manifest['repository'],'source_commit':manifest['commit'],
            'generated_at_utc':datetime.now(timezone.utc).isoformat(),'clinical_release':False,
            'source_files_unchanged':True,'source_sha256':before,'cases':cases,
            'benchmark_expectations_passed':all(c['expected_findings_present'] for c in cases) and
                (topology is None or (topology['probe_executed'] and (not topology['unsupported_polygon_rois'] or topology['sampler_rejected']))),
            'dose_comparison':comparison,'keyhole_topology_probe':topology,
            'implementation_sha256':{name:hashlib.sha256((MANIFEST.parent.parent/name).read_bytes()).hexdigest() for name in
                ('scripts/benchmark_slicerrt.py','scripts/slicerrt_reference.py','src/case_verification.py','src/tools.py','openrad/tools/contours.py')},
            'software':{name:version(name) for name in ('pydicom','numpy','pymedphys','dicompyler-core')},
            'limitations':['External software compatibility exercise; dataset contents are not certified ground truth.',
                           'Intake readiness does not validate dose accuracy, anatomy or a computational model.']}
    output.mkdir(parents=True,exist_ok=True)
    (output/'assessment.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    lines=['# SlicerRT external-data assessment','','Source commit: '+manifest['commit'],
           '','Research compatibility evidence only; no model or clinical approval.','',
           '| Dataset | Intake state | Findings |','|---|---|---|']
    for case in cases:
        lines.append('| '+case['dataset']+' | ['+case['status']+']('+case['report']+') | '+', '.join(f"{f['severity']}: {f['code']} ({f['count']})" for f in case['findings'])+' |')
    if comparison:
        lines.extend(['','## Eclipse phantom comparison','',
                      'Observed differences; no clinical acceptance tolerance established. TPS export and dicompyler-core are numerical comparators, not measured truth.','',
                      '| Structure | OpenRad − TPS volume (cc) | Mean dose (Gy) | D95 (Gy) | D50 (Gy) | D2 (Gy) |',
                      '|---|---:|---:|---:|---:|---:|'])
        for row in comparison['structures']:
            delta=row['openrad_minus_tps']
            lines.append('| '+row['structure']+' | '+' | '.join(f'{delta[k]:+.4f}' for k in ('volume_cc','mean_dose_Gy','D95_Gy','D50_Gy','D2_Gy'))+' |')
        lines.extend(['','![OpenRad and exported TPS DVHs](dvh-comparison.png)','']+['- '+x for x in comparison['limitations']])
    if topology:
        lines.extend(['','## Keyhole topology','',topology['scope'],
                      f"Unsupported simple polygons detected: {len(topology['unsupported_polygon_rois'])}; selected probe rejected: {topology['sampler_rejected']}. {topology.get('reason','Probe not executed')}",
                      'Dataset names do not establish topology or expected rejection. Full topology accuracy still needs independent reference masks/volumes.'])
    lines.extend(['','## Follow-up actions','',
                  'Inspect each generated case report. Resolve missing references, naming and unsupported geometry before calculating a DVH.',
                  'Compare supported DVHs with an independent implementation under recorded sampling settings. Do not treat source doses as measured truth.',
                  '',f"All {len(before)} pinned source files passed before/after content-hash checks."])
    (output/'assessment.md').write_text('\n'.join(lines)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['fetch','run'])
    parser.add_argument('--cache',default='data/raw/slicerrt')
    parser.add_argument('--output',default='data/processed/slicerrt-benchmark')
    args=parser.parse_args();manifest=load_manifest()
    root=Path(args.cache).absolute()/manifest['commit']
    result=fetch(manifest,root) if args.action=='fetch' else run(manifest,root,Path(args.output))
    print(json.dumps(result if args.action=='fetch' else {c['dataset']:c['status'] for c in result['cases']},indent=2))
    if args.action=='run' and not result['benchmark_expectations_passed']:raise SystemExit(2)


if __name__=='__main__':main()
