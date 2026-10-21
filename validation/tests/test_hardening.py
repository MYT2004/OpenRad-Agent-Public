"""Regression tests for audited boundary failures, using nonpatient controls only."""
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pytest
from src.storage import StorageManager, session_scope
from openrad.validation.physics_rules import PhysicsValidationEngine as PV, DVHCurveError
from validation.tests.test_submission import dicom_pair


@pytest.mark.parametrize('dtype',['U40','S40',object])
def test_npy_parse_errors_never_echo_contents(tmp_path,monkeypatch,dtype):
    import server
    from fastapi.testclient import TestClient
    monkeypatch.setattr(server,'storage_mgr',StorageManager(str(tmp_path/'sessions')))
    bad=tmp_path/'sensitive-filename.npy';good=tmp_path/'valid.npy'
    np.save(bad,np.full((2,2),'NONPATIENT_SECRET_MARKER',dtype=dtype));np.save(good,np.ones((2,2)))
    r=TestClient(server.app).post('/api/v1/gamma/evaluate',json={'reference_dose_path':str(bad),'evaluated_dose_path':str(good),'reference_spacing_mm':[1,1],'evaluated_spacing_mm':[1,1]})
    assert r.status_code==400
    assert 'NONPATIENT_SECRET_MARKER' not in r.text
    assert 'sensitive-filename' not in r.text and str(tmp_path) not in r.text


@pytest.mark.parametrize('d,v',[(1.,100.),(None,None),([0,1],100.),([0,10**400],[100,0]),(['NONPATIENT_SECRET_MARKER',1],[100,0])])
def test_malformed_curve_has_safe_structured_failure(d,v):
    r=PV.validate_dvh_curve(d,v)
    assert not r.passed and 'NONPATIENT_SECRET_MARKER' not in str(r.to_dict())
    with pytest.raises(DVHCurveError):PV.validate_dvh_curve(d,v,raise_on_fail=True)


def test_real_dvh_boundary_rejects_faulty_curve_before_artifacts(dicom_pair,tmp_path,monkeypatch):
    import src.tools as tools
    paths,_=dicom_pair
    def faulty(*a,**k):return {'course_linkage_verified':True,'structures':{'Brainstem':{'found':True,'dvh_curve':{'dose_bins_Gy':[0,10],'volume_percent':[100,-50]}}}}
    monkeypatch.setattr(tools,'analyze_dvh_datasets',faulty)
    manager=StorageManager(str(tmp_path/'outputs'))
    with session_scope(manager,'faulty'):
        with pytest.raises(DVHCurveError):tools.parse_and_evaluate_dvh(paths['dose'],paths['struct'],['Brainstem'],rtplan_path=paths['plan'])
    assert not list((tmp_path/'outputs').rglob('*.png'))
    assert not list((tmp_path/'outputs').rglob('report_*.md'))
    assert not list((tmp_path/'outputs').rglob('tool-audit.jsonl'))


@pytest.mark.parametrize('curve',[( [10,20],[80,20]),([0,10],[0,0])])
def test_complete_dvh_requires_normalized_endpoints(curve):
    assert not PV.validate_dvh_curve(*curve,require_complete=True).passed


@pytest.mark.parametrize('extra',[{'timestamp':None},{'user_prompt':[]},{'agent_response':{}},{'schema_version':2}])
def test_history_reserved_fields_rejected_before_write(tmp_path,extra):
    m=StorageManager(str(tmp_path/'s'));m.initialize_session('s')
    with pytest.raises(ValueError):m.save_trajectory('s','prompt','response',extra)
    assert not (Path(m.get_session_dir('s'))/'trajectory.json').exists()


def test_history_types_validated_on_read(tmp_path):
    from src.storage import CorruptedSessionError
    m=StorageManager(str(tmp_path/'s'));m.initialize_session('s');p=Path(m.get_session_dir('s'))/'trajectory.json'
    p.write_text(json.dumps([{'timestamp':None,'user_prompt':[],'agent_response':{}}]))
    before=p.read_bytes()
    with pytest.raises(CorruptedSessionError):m.load_trajectory('s')
    assert p.read_bytes()==before


def test_failed_history_commit_keeps_old_data_and_cleans_temp(tmp_path):
    m=StorageManager(str(tmp_path/'s'));m.initialize_session('s');m.save_trajectory('s','first','done');p=Path(m.get_session_dir('s'))/'trajectory.json';before=p.read_bytes()
    with patch('src.storage.os.replace',side_effect=OSError('injected failure')):
        with pytest.raises(OSError):m.save_trajectory('s','second','done')
    assert p.read_bytes()==before and len(m.load_trajectory('s'))==1
    assert not list(p.parent.glob('*.tmp'))


@pytest.mark.parametrize('value',[True,False,np.bool_(True),'150'])
def test_core_energy_requires_numeric_nonboolean(value):
    from openrad.tools.topas_tool import generate_topas_deck
    assert not PV.validate_beam_energy(value).passed
    with pytest.raises(ValueError):generate_topas_deck('proton',value)


@pytest.mark.parametrize('tolerance',[-1.,-.001,.001])
def test_negative_dose_invariant_cannot_be_relaxed(tolerance):
    with pytest.raises(ValueError):PV.validate_dose_grid([-.0005,1],tolerance=tolerance)


@pytest.mark.parametrize('geometry',['water_phantom','slab_heterogeneity'])
def test_topas_serialization_keeps_positive_geometry(geometry):
    import re
    from openrad.tools.topas_tool import generate_topas_deck
    text=generate_topas_deck('proton',150,geometry_type=geometry,phantom_dimensions_cm=[.001,.001,.001])
    sizes=[float(v) for v in re.findall(r'd:Ge/[^ /]+/HL[XYZ] = ([0-9.eE+-]+) cm',text)]
    assert sizes and all(v>0 for v in sizes)
    assert float(re.search(r'd:Ge/Phantom/HLX = ([0-9.eE+-]+)',text)[1])==pytest.approx(.0005,rel=1e-12)


def test_gamma_direct_difference_threshold_policy():
    from openrad.tools.gamma_tool import evaluate_gamma_index
    # This exact binary-float pair cancels differently if normalized before subtracting.
    ref=np.array([[46.25,46.0],[45.5,46.25]])
    ev=ref*1.03
    dd=float(ref.max())*3./100.
    pts=np.stack(np.meshgrid(np.arange(2.),np.arange(2.),indexing='ij'),axis=-1).reshape(-1,2)
    g=np.sqrt(np.sum(((pts[:,None]-pts[None,:])/2.)**2,axis=2)+((ref.ravel()[:,None]-ev.ravel()[None,:])/dd)**2).min(axis=1)
    r=evaluate_gamma_index(ref,ev,reference_spacing_mm=[1,1],evaluated_spacing_mm=[1,1])
    assert r['passing_rate']==float(np.mean(g<=1)*100)
    assert r['average_gamma_unrounded']==pytest.approx(float(g.mean()),abs=1e-14)
    assert r['threshold_policy']=='direct_difference_float64_le_1'


def test_policy_resources_available_outside_checkout(tmp_path,monkeypatch):
    from src.config import load_skill_policies
    monkeypatch.chdir(tmp_path)
    policies=load_skill_policies()
    assert len(policies)==2 and all(len(v)>100 for v in policies.values())


def test_input_budget_checked_before_numpy_allocation(tmp_path,monkeypatch):
    from openrad.tools.gamma_tool import evaluate_gamma_index
    monkeypatch.setenv('OPENRAD_MAX_DOSE_VOXELS','10')
    p=tmp_path/'dose.npy';np.save(p,np.ones((3,3,3)))
    with patch('numpy.load',side_effect=AssertionError('must refuse header before load')):
        with pytest.raises(ValueError,match='budget'):evaluate_gamma_index(str(p),np.ones((2,2)),reference_spacing_mm=[1,1,1],evaluated_spacing_mm=[1,1])


def test_packaged_policies_match_canonical_sources():
    from src.config import load_skill_policies
    root=Path(__file__).resolve().parents[2];policies=load_skill_policies()
    assert policies['global']==(root/'SKILL.md').read_text()
    assert policies['radiation_physics']==(root/'skills/radiation_physics/SKILL.md').read_text()


def test_evidence_preflight_refuses_existing_before_work(tmp_path,monkeypatch):
    from validation.benchmarks.stress import stress_all_menus as runner
    p=tmp_path/'comprehensive_stress_assessment.json';p.write_text('{"keep":true}')
    monkeypatch.setattr('sys.argv',['runner','--output-dir',str(tmp_path)])
    def must_not_run(*args):raise AssertionError('work must not run')
    monkeypatch.setattr(runner,'stress_test_menu_1_patient_verification',must_not_run)
    with pytest.raises(SystemExit) as exc:runner.main()
    assert exc.value.code==1 and p.read_text()=='{"keep":true}'


def test_evidence_reservation_prevents_concurrent_ownership(tmp_path):
    from validation.paths import reserve_evidence
    p=tmp_path/'result.json'
    with reserve_evidence(p):
        with pytest.raises(ValueError,match='already in use'):
            with reserve_evidence(p):pass


def test_qualification_mode_rejects_skips_and_never_publishes(tmp_path,monkeypatch):
    from validation.benchmarks.stress import stress_all_menus as runner
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('sys.argv',['runner','--output-dir',str(tmp_path/'out'),'--require-complete','--publish-evidence'])
    names=[n for n in vars(runner) if n.startswith('stress_test_menu_')]
    for name in names:
        monkeypatch.setattr(runner,name,lambda records:records.append({'status':'SKIP','passed':False}))
    with pytest.raises(SystemExit) as exc:runner.main()
    assert exc.value.code==2
    result=json.loads((tmp_path/'out/comprehensive_stress_assessment.json').read_text())
    assert result['skipped']==len(names) and not result['qualification_gate_passed']
    assert not (tmp_path/'validation/evidence/stress/comprehensive_stress_assessment.json').exists()


def test_job_admission_refuses_overlap_and_recovers_after_failure():
    from src.runtime import JobAdmission
    from fastapi import HTTPException
    gate=JobAdmission(1)
    @gate.bounded
    def nested():return 'ok'
    @gate.bounded
    def outer():return nested()
    with pytest.raises(HTTPException) as exc:outer()
    assert exc.value.status_code==429
    assert nested()=='ok'


def test_shared_profile_is_not_silently_claimed(monkeypatch):
    from src.runtime import validate_deployment_profile,research_readiness
    monkeypatch.setenv('OPENRAD_DEPLOYMENT_PROFILE','shared')
    with pytest.raises(RuntimeError,match='not qualified'):validate_deployment_profile()
    assert not research_readiness()['production_ready']


def test_rest_does_not_accept_ignored_model_choice():
    from server import AgentRunRequest
    with pytest.raises(ValueError,match='deterministic'):AgentRunRequest(prompt='x',model='gemini-unused')


def test_paths_as_gamma_inputs_are_supported(tmp_path):
    from openrad.tools.gamma_tool import evaluate_gamma_index
    a=tmp_path/'a.npy';b=tmp_path/'b.npy';np.save(a,np.ones((2,2)));np.save(b,np.ones((2,2))*1.01)
    assert evaluate_gamma_index(a,b,reference_spacing_mm=[1,1],evaluated_spacing_mm=[1,1])['passing_rate']==100


def test_session_symlink_cannot_redirect_outputs_to_raw(tmp_path,monkeypatch):
    protected=tmp_path/'protected-input';protected.mkdir()
    monkeypatch.setenv('OPENRAD_DATA_ROOTS',json.dumps([str(protected)]))
    m=StorageManager(str(tmp_path/'outputs'))
    (Path(m.base_dir)/'alias').symlink_to(protected,target_is_directory=True)
    with pytest.raises(ValueError):m.initialize_session('alias')
    assert not list(protected.iterdir())


def test_artifact_directory_cannot_escape_session(tmp_path):
    m=StorageManager(str(tmp_path/'outputs'));m.initialize_session('s');outside=tmp_path/'elsewhere';outside.mkdir()
    directory=Path(m.get_artifacts_dir('s'));directory.rmdir();directory.symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError):m.get_artifacts_dir('s')
    assert not list(outside.iterdir())


def test_topas_rejects_underflowed_geometry():
    from openrad.tools.topas_tool import generate_topas_deck
    with pytest.raises(ValueError,match='too small'):generate_topas_deck('proton',150,phantom_dimensions_cm=[5e-324]*3)


def test_pydicom_security_backport_refuses_traversal(tmp_path,dicom_pair):
    """Exercise public FileSet loading on generated files, never a patient source."""
    import pydicom
    from pydicom.fileset import FileSet
    from pydicom.uid import generate_uid
    _,datasets=dicom_pair;dose=datasets['dose']
    for key,value in dict(StudyInstanceUID=generate_uid(),SeriesInstanceUID=generate_uid(),StudyDate='20000101',StudyTime='120000',StudyID='CONTROL',SeriesNumber=1,InstanceNumber=1,DoseSummationType='PLAN').items():setattr(dose,key,value)
    fs=FileSet();fs.add(dose);root=tmp_path/'fileset';fs.write(root)
    directory=pydicom.dcmread(root/'DICOMDIR')
    entry=next(r for r in directory.DirectoryRecordSequence if 'ReferencedFileID' in r)
    outside=tmp_path/'OUTSIDE';outside.write_bytes(b'NONPATIENT_SECURITY_CONTROL')
    with pytest.warns(UserWarning):entry.ReferencedFileID=['..','OUTSIDE']
    directory.save_as(root/'DICOMDIR')
    with pytest.raises(PermissionError):FileSet(root/'DICOMDIR')
    assert outside.read_bytes()==b'NONPATIENT_SECURITY_CONTROL'


def test_operation_records_outcomes_without_sensitive_arguments(tmp_path):
    from src.operations import audited_operation
    from src.governance import verify_records
    m=StorageManager(str(tmp_path/'s'))
    @audited_operation
    def success(secret):return {'value':secret}
    @audited_operation
    def failure(secret):raise ValueError(secret)
    with session_scope(m,'s'):
        assert success('NONPATIENT_PRIVATE_TOKEN')
        with pytest.raises(ValueError):failure('NONPATIENT_PRIVATE_TOKEN')
    data=(Path(m.get_session_dir('s'))/'operations.jsonl').read_text()
    assert 'NONPATIENT_PRIVATE_TOKEN' not in data
    records=[json.loads(line) for line in data.splitlines()];verify_records(records)
    assert [r['event']['type'] for r in records]==['operation_started','operation_returned','operation_started','operation_error']


def test_operation_audit_failure_does_not_return_success(tmp_path,monkeypatch):
    from src.operations import audited_operation
    @audited_operation
    def operation():return {'status':'success'}
    monkeypatch.setattr('src.operations.append_record',lambda *a,**k:(_ for _ in ()).throw(OSError('unavailable')))
    with session_scope(StorageManager(str(tmp_path/'s'))):
        with pytest.raises(OSError):operation()


def test_operation_serialization_failure_is_recorded(tmp_path):
    from src.operations import audited_operation
    m=StorageManager(str(tmp_path/'s'))
    @audited_operation
    def bad_result():return {'value':float('nan')}
    with session_scope(m,'s'):
        with pytest.raises(ValueError):bad_result()
    rows=[json.loads(line)['event'] for line in (Path(m.get_session_dir('s'))/'operations.jsonl').read_text().splitlines()]
    assert rows[-1]['type']=='operation_error' and rows[-1]['error_type']=='ValueError'


def test_api_calculation_and_report_share_operation_session(tmp_path,monkeypatch):
    import server
    from fastapi.testclient import TestClient
    m=StorageManager(str(tmp_path/'s'));monkeypatch.setattr(server,'storage_mgr',m)
    a=tmp_path/'a.npy';b=tmp_path/'b.npy';np.save(a,np.ones((2,2)));np.save(b,np.ones((2,2))*1.01)
    r=TestClient(server.app).post('/api/v1/gamma/evaluate',json={'reference_dose_path':str(a),'evaluated_dose_path':str(b),'reference_spacing_mm':[1,1],'evaluated_spacing_mm':[1,1]})
    assert r.status_code==200
    directory=Path(m.get_session_dir(r.json()['session_id']))
    assert (directory/'operations.jsonl').exists()
    assert len(list(Path(m.base_dir).glob('*/metadata.json')))==1


def test_asgi_import_cannot_bypass_deployment_profile(tmp_path):
    import os,subprocess,sys
    env=dict(os.environ,OPENRAD_DEPLOYMENT_PROFILE='shared',STORAGE_DIR=str(tmp_path/'s'),GEMINI_API_KEY='',PYTHONDONTWRITEBYTECODE='1')
    r=subprocess.run([sys.executable,'-c','import server'],cwd=Path(__file__).resolve().parents[2],env=env,capture_output=True,text=True,timeout=30)
    assert r.returncode!=0 and 'not qualified' in r.stderr
    assert not (tmp_path/'s').exists()


@pytest.mark.parametrize('path_type',[str,Path])
def test_dicom_identity_guard_is_independent_of_path_type(dicom_pair,tmp_path,path_type):
    from openrad.tools.gamma_tool import evaluate_gamma_index
    from pydicom.uid import generate_uid
    paths,datasets=dicom_pair;other=tmp_path/'other-dose.dcm'
    datasets['dose'].FrameOfReferenceUID=generate_uid();datasets['dose'].save_as(other)
    with pytest.raises(ValueError,match='matching explicit patient and frame'):
        evaluate_gamma_index(path_type(paths['dose']),path_type(other))


@pytest.mark.parametrize('boolean',[True,False])
def test_model_and_agent_schemas_cannot_coerce_boolean_energy(boolean):
    from openrad.tools.topas_tool import TOPASGeneratorInput
    from src.decision import EvaluationRequest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):TOPASGeneratorInput(particle_type='proton',energy_MeV=boolean)
    with pytest.raises(ValidationError) as exc:EvaluationRequest.model_validate({'energy_mev':boolean})
    assert any(e['loc']==('energy_mev',) for e in exc.value.errors())
