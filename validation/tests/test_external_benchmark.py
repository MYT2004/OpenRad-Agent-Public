"""Offline tests for external benchmark integrity; no patient downloads in CI."""
import hashlib
import json
from pathlib import Path
import pytest
from validation.benchmarks.slicerrt import runner as bench


def entry(data=b'fixture'):
    return {'path':'case/source.dcm','size':len(data),
            'sha':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()}


def test_manifest_is_pinned_and_contains_complete_selected_inventory():
    manifest=bench.load_manifest()
    assert len(manifest['files'])==314
    assert len(manifest['cases'])==5
    assert len(manifest['commit'])==40
    assert sum(p['size'] for p in manifest['files'])==170232024


def test_existing_input_is_verified_and_never_replaced(tmp_path,monkeypatch):
    item=entry();path=tmp_path/item['path'];path.parent.mkdir();path.write_bytes(b'fixture')
    monkeypatch.setattr(bench,'urlopen',lambda *a,**k:pytest.fail('Existing inputs must not be downloaded again'))
    assert bench.fetch_one(tmp_path,'a'*40,item)==hashlib.sha256(b'fixture').hexdigest()
    path.write_bytes(b'corrupt')
    with pytest.raises(ValueError):bench.fetch_one(tmp_path,'a'*40,item)
    assert path.read_bytes()==b'corrupt'


def test_download_hash_failure_never_publishes_input(tmp_path,monkeypatch):
    from io import BytesIO
    monkeypatch.setattr(bench,'urlopen',lambda *a,**k:BytesIO(b'changed'))
    with pytest.raises(ValueError):bench.fetch_one(tmp_path,'a'*40,entry())
    assert not (tmp_path/'case').exists()


def test_download_is_exclusively_published(tmp_path,monkeypatch):
    from io import BytesIO
    monkeypatch.setattr(bench,'urlopen',lambda *a,**k:BytesIO(b'fixture'))
    bench.fetch_one(tmp_path,'a'*40,entry())
    assert (tmp_path/'case/source.dcm').read_bytes()==b'fixture'
    assert not list(tmp_path.rglob('.download-*'))


def test_symlink_and_manifest_traversal_refused(tmp_path):
    target=tmp_path/'actual';target.mkdir();(tmp_path/'link').symlink_to(target,target_is_directory=True)
    with pytest.raises(ValueError):bench.checked_path(tmp_path,'link/source.dcm')
    manifest=bench.load_manifest();manifest['files'][0]['path']='../outside'
    path=tmp_path/'manifest.json';path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):bench.load_manifest(path)


def test_external_runner_real_pipeline_and_source_preservation(tmp_path):
    from src.demo import create_synthetic_case
    root=tmp_path/'inputs';create_synthetic_case(root/'case')
    files=[]
    for path in (root/'case').iterdir():
        data=path.read_bytes();item=entry(data);item['path']='case/'+path.name;files.append(item)
    manifest={'repository':'offline synthetic fixture','commit':'a'*40,'files':files,
              'cases':[{'id':'case','intake_subdir':'.'}]}
    result=bench.run(manifest,root,tmp_path/'reports')
    assert result['source_files_unchanged'] and not result['clinical_release']
    assert result['cases'][0]['status']=='READY_FOR_RESEARCH_ANALYSIS'
    assert 'Follow-up actions' in (tmp_path/'reports/assessment.md').read_text()
    with pytest.raises(FileExistsError):bench.run(manifest,root,tmp_path/'reports')
    with pytest.raises(ValueError):bench.run(manifest,root,root/'bad-output')
    (root/'unpinned.txt').write_text('untracked input')
    with pytest.raises(ValueError):bench.inventory(manifest,root)


def export_fixture():
    return '''Patient ID           : PHANTOM
Type                 : Cumulative Dose Volume Histogram
Plan: TEST
Prescribed dose [cGy]: 10000.0
Structure: Bladder
Volume [cm3]: 100.0
Mean Dose [%]: 50.0
Relative dose [%] Dose [cGy] Ratio of Total Structure Volume [%]
0 0 100
50 5000 50
100 10000 0
'''


def test_tps_reference_parser_explicit_units_and_linear_oracle():
    from validation.benchmarks.slicerrt.reference import parse_eclipse_export
    result=parse_eclipse_export(export_fixture())
    roi=result['structures']['Bladder']
    assert result['prescription_gy']==100 and result['plan']=='TEST'
    assert roi['mean_dose_Gy']==50 and roi['volume_cc']==100
    assert roi['D95_Gy']==5 and roi['D50_Gy']==50 and roi['D2_Gy']==98


@pytest.mark.parametrize('old,new',[
    ('Dose [cGy]','Dose [Gy]'),('100 10000 0','100 10000 1'),
    ('50 5000 50','50 5000 101'),('50 5000 50','50 5001 50'),
    ('50 5000 50','50 nan 50')])
def test_tps_reference_parser_rejects_ambiguous_or_corrupt_curves(old,new):
    from validation.benchmarks.slicerrt.reference import parse_eclipse_export
    with pytest.raises(ValueError):parse_eclipse_export(export_fixture().replace(old,new))


def test_tps_reference_selection_is_explicit_and_complete():
    from validation.benchmarks.slicerrt.reference import parse_eclipse_export
    with pytest.raises(ValueError):parse_eclipse_export(export_fixture(),['Rectum'])
    duplicate=export_fixture()+'Structure:'+export_fixture().split('Structure:',1)[-1]
    with pytest.raises(ValueError):parse_eclipse_export(duplicate,['Bladder'])


def test_cumulative_curve_resolves_narrow_dose_steps_and_inclusive_thresholds():
    import numpy as np
    from openrad.tools.dicom_tool import cumulative_dvh_curve
    curve=cumulative_dvh_curve(np.array([45.,45.,45.02,45.02]))
    axis=np.asarray(curve['dose_bins_Gy']);volume=curve['volume_percent']
    for dose,expected in [(44.99,100),(45.,100),(45.01,50),(45.02,50),(45.03,0)]:
        assert volume[int(np.flatnonzero(np.isclose(axis,dose,atol=1e-8,rtol=0))[0])]==expected
    assert curve['bin_width_Gy']==.01


def test_cumulative_curve_has_bounded_output_for_large_doses():
    import numpy as np
    from openrad.tools.dicom_tool import cumulative_dvh_curve
    curve=cumulative_dvh_curve(np.array([0.,1000.]))
    assert len(curve['dose_bins_Gy'])<=10001 and curve['bin_width_Gy']>.01
    assert curve['volume_percent'][0]==100 and curve['volume_percent'][-1]==0


def test_exported_curve_threshold_matches_the_threshold_actually_evaluated():
    import numpy as np
    from openrad.tools.dicom_tool import cumulative_dvh_curve
    curve=cumulative_dvh_curve(np.array([.29]))
    index=curve['dose_bins_Gy'].index(.29)
    assert curve['volume_percent'][index]==100


def test_default_run_directories_are_unique_and_centralized():
    first,second=bench.default_run_output(),bench.default_run_output()
    assert first!=second
    assert first.parent==bench.REPO_ROOT/'validation/runs/slicerrt'


def test_published_snapshot_preserves_hashes_audit_chains_and_report_links():
    from src.governance import verify_records
    root=bench.REPO_ROOT/'validation/evidence/slicerrt/2026-10-21-bc757c0'
    provenance=json.loads((root/'provenance.json').read_text())
    for name,sha in provenance['artifacts_sha256'].items():
        path=root/name
        assert hashlib.sha256(path.read_bytes()).hexdigest()==sha
        if path.suffix=='.jsonl':
            verify_records([json.loads(line) for line in path.read_text().splitlines() if line.strip()])
    result=json.loads((root/'assessment.json').read_text())
    assert result['source_commit']==bench.load_manifest()['commit']
    assert all((root/case['report']).is_file() for case in result['cases'])
    assert (root/result['dose_comparison']['openrad_report']).is_file()
    assert (root/result['dose_comparison']['plot']).is_file()
