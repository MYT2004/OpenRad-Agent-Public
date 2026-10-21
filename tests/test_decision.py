"""Independent threshold boundaries, source immutability and signature adversaries."""
import base64
import hashlib
import json
from pathlib import Path
import numpy as np
import pytest
from src.decision import EvaluationRequest, Policy, threshold_rule
from src.evaluation import evaluate_model
from src.storage import StorageManager, session_scope
from src.governance import canonical, signed_review, verify_records


@pytest.fixture
def case(tmp_path):
    source = tmp_path / 'raw'; source.mkdir()
    def save(name, data):
        path = source / (name + '.npy'); np.save(path, data); return str(path)
    shape = (3, 3, 3)
    grid = dict(shape=shape, spacing_mm=[2, 2, 2], origin_mm=[0, 0, 0], frame_id='test-frame')
    evidence = source / 'evidence.json'; evidence.write_text('{"test_evidence":true}')
    weights = source / 'weights.bin'; weights.write_bytes(b'never deserialize me')
    args = dict(model_name='phantom', dataset_id='synthetic', model_weights_path=str(weights),
        input_paths=[str(weights)], reference_path=save('reference', np.full(shape, 40.)),
        prediction_path=save('prediction', np.full(shape, 40.)), image_grid=grid, reference_grid=grid,
        prediction_grid=grid, prescription_gy=40., target_mask_path=save('target', np.ones(shape)),
        oar_mask_paths={'Brainstem': save('oar', np.ones(shape))}, oar_limits_gy={'Brainstem':50.},
        uncertainty_std_path=save('uncertainty', np.zeros(shape)), confidence=1., ood_score=0., inference_seed=42,
        qualification_evidence_path=str(evidence), uncertainty_calibration_path=str(evidence), ood_calibration_path=str(evidence))
    manager = StorageManager(str(tmp_path / 'outputs'))
    return args, manager, save, source


def run(case, **updates):
    args, manager, _, _ = case
    with session_scope(manager, 'test-session'):
        return evaluate_model(EvaluationRequest.model_validate({**args, **updates}))


@pytest.mark.parametrize('name,value,p,f,higher,outcome', [
    ('gamma',95,95,90,True,'PASS'), ('gamma',90,95,90,True,'REVIEW'), ('gamma',89.999,95,90,True,'REJECT'),
    ('strict',90,90,85,True,'PASS'), ('strict',85,90,85,True,'REVIEW'), ('strict',84.99,90,85,True,'REJECT'),
    ('ptv',95,95,93,True,'PASS'), ('ptv',93,95,93,True,'REVIEW'), ('ptv',92.99,95,93,True,'REJECT'),
    ('mae',1.499,1.5,3,False,'PASS'), ('mae',1.5,1.5,3,False,'REVIEW'), ('mae',3,1.5,3,False,'REVIEW'),
    ('mae',3.001,1.5,3,False,'REJECT')])
def test_thresholds(name,value,p,f,higher,outcome):
    assert threshold_rule(name,value,p,f,higher).outcome == outcome


def test_uniform_oracle_and_readonly(case):
    source = case[3]
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
    result = run(case)
    assert result['status'] == 'APPROVED' and not result['clinical_release']
    assert result['metrics']['mae_percent_rx'] == 0
    assert result['metrics']['ptv_d95_percent_rx'] == 100
    assert result['gamma_pass_rate_3mm3pct'] == 100
    assert result['artifacts']
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
    assert str(source) not in json.dumps(result)
    again = run(case)
    assert again['decision_hash'] == result['decision_hash']


@pytest.mark.parametrize('dose',[-.001,float('nan'),float('inf')])
def test_invalid_dose_rejects(case,dose):
    path = case[2]('bad',np.full((3,3,3),dose))
    result = run(case,prediction_path=path)
    assert result['status'] == 'REJECTED' and not result['hard_checks_passed']
    assert not result['artifacts']


@pytest.mark.parametrize('update',[
    {'uncertainty_std_path':None}, {'confidence':None}, {'ood_flags':['metal_artifact']},
    {'qualification_evidence_path':None}, {'ood_calibration_path':None}, {'inference_seed':None},
    {'model_kind':'auto_segmentation'}, {'fluence_per_mm2':1.}])
def test_missing_or_unsupported_evidence_never_approves(case,update):
    assert run(case,**update)['status'] == 'FLAGGED_FOR_REVIEW'


@pytest.mark.parametrize('limit,status',[(40.9,'PASS'),(40/.98,'REVIEW'),(40.,'REVIEW'),(39.9,'REJECT')])
def test_oar_boundaries(case,limit,status):
    result = run(case,oar_limits_gy={'Brainstem':limit})
    assert next(r for r in result['rules'] if r['name']=='oar_Brainstem')['outcome'] == status


@pytest.mark.parametrize('update',[
    {'energy_mev':250.1}, {'probabilities':{'TCP':1.01}}, {'fluence_per_mm2':-1.},
    {'prediction_grid':dict(shape=[3,3,3],spacing_mm=[2,2,2],origin_mm=[1,0,0],frame_id='test-frame')},
    {'prediction_grid':dict(shape=[3,3,3],spacing_mm=[2,2,2],origin_mm=[0,0,0],frame_id='other-frame')},
    {'prediction_grid':dict(shape=[3,3,3],spacing_mm=[2,2,2],origin_mm=[0,0,0],frame_id='test-frame',direction=[1]*9)},
])
def test_hard_constraints(case,update):
    result = run(case,**update)
    assert result['status']=='REJECTED' and not result['hard_checks_passed']


def test_uncertainty_and_density(case):
    uncertain=case[2]('uncertain',np.full((3,3,3),3.))
    assert run(case,uncertainty_std_path=uncertain)['status']=='FLAGGED_FOR_REVIEW'
    density=case[2]('density',np.full((3,3,3),3.01))
    assert run(case,mass_density_path=density)['status']=='REJECTED'


def test_no_implicit_grid_repair(case):
    wrong=case[2]('wrong',np.ones((2,2,2)))
    assert run(case,prediction_path=wrong)['status']=='REJECTED'


def test_depth_dose_applicability(case):
    path=case[2]('depth',np.array([[0,0],[1,1],[2,.9],[3,1.1]]))
    assert run(case,depth_dose_path=path)['status']=='FLAGGED_FOR_REVIEW'
    result=run(case,depth_dose_path=path,homogeneous_photon_depth_dose=True,buildup_end_mm=1.)
    assert result['status']=='REJECTED' and not result['hard_checks_passed']


def test_signoff_replay_and_tamper(case):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    decision=run(case)
    audit=Path(case[1].get_session_dir('test-session'))/'decisions.jsonl'
    key=Ed25519PrivateKey.generate()
    keys={'reviewer-1':base64.b64encode(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()}
    payload=dict(decision_hash=decision['decision_hash'],session_id=decision['session_id'],reviewer_id='reviewer-1',disposition='FLAGGED_FOR_REVIEW',
                 justification='Independent commissioning still required',nonce='unique-nonce-00000001')
    signature=base64.b64encode(key.sign(canonical(payload))).decode()
    record=signed_review(audit,decision,payload,signature,keys)
    assert record['event']['clinical_release'] is False
    with pytest.raises(ValueError,match='already used'):
        signed_review(audit,decision,payload,signature,keys)
    with pytest.raises(ValueError,match='signature'):
        signed_review(audit,decision,{**payload,'justification':'Changed after signing'},signature,keys)
    records=[json.loads(line) for line in audit.read_text().splitlines()]
    assert verify_records(records)==record['hash']
    records[0]['event']['status']='REJECTED'
    with pytest.raises(ValueError,match='integrity'):
        verify_records(records)


def test_raw_output_guard(case,monkeypatch,tmp_path):
    from src.readonly import assert_output_path
    monkeypatch.setenv('OPENRAD_DATA_ROOTS',json.dumps([str(case[3])]))
    with pytest.raises(ValueError,match='read-only'):
        StorageManager(str(case[3]/'sessions'))
    link=tmp_path/'alias';link.symlink_to(case[3],target_is_directory=True)
    with pytest.raises(ValueError,match='read-only'):
        assert_output_path(link/'new.txt')


def test_api_and_cli(case,tmp_path,monkeypatch,capsys):
    from fastapi.testclient import TestClient
    import server
    from agent_main import main
    monkeypatch.setattr(server,'storage_mgr',case[1])
    with TestClient(server.app) as client:
        response=client.post('/api/v1/evaluations',json=case[0])
        assert response.status_code==200
        assert response.json()['status']=='APPROVED'
        assert client.get(response.json()['artifacts'][0]).status_code==200
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(case[0]))
    assert main(['--storage-dir',str(tmp_path/'cli-output'),'evaluate','--manifest',str(manifest)])==0
    assert json.loads(capsys.readouterr().out)['status']=='APPROVED'


def test_low_confidence_rejects(case):
    result=run(case,confidence=.94)
    assert result['status']=='REJECTED'
    assert result['hard_checks_passed']


def test_uncertainty_overlap_and_nonnegative(case):
    prediction=np.broadcast_to(np.array([40.,44.,48.]),(3,3,3))
    result=run(case,prediction_path=case[2]('gradient',prediction),
               uncertainty_std_path=case[2]('high-sd',np.full((3,3,3),2.)))
    assert next(r for r in result['rules'] if r['name']=='critical_uncertainty_overlap')['observed']==27
    result=run(case,uncertainty_std_path=case[2]('negative-sd',np.full((3,3,3),-.1)))
    assert result['status']=='REJECTED' and not result['hard_checks_passed']


def test_hard_rejection_cannot_be_signed_away(case):
    result=run(case,energy_mev=999.)
    audit=Path(case[1].get_session_dir('test-session'))/'decisions.jsonl'
    payload=dict(decision_hash=result['decision_hash'],session_id=result['session_id'],reviewer_id='reviewer',disposition='APPROVED',
                 justification='Cannot bypass invalid beam energy',nonce='another-unique-nonce-00001')
    with pytest.raises(ValueError,match='cannot be approved'):
        signed_review(audit,result,payload,'',{})


def test_frontend_triage(case,monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('STORAGE_DIR',case[1].base_dir)
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'frontend'/'app.py')).run()
    app.selectbox[0].select('Model Evaluation & Triage').run()
    next(area for area in app.text_area if area.label=='Evaluation manifest JSON').input(json.dumps(case[0]))
    next(button for button in app.button if button.label=='Evaluate supplied model output').click().run()
    assert not app.exception
    assert app.metric[0].value=='APPROVED'


def test_signed_review_api(case,monkeypatch):
    from fastapi.testclient import TestClient
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    import server
    monkeypatch.setattr(server,'storage_mgr',case[1])
    private=Ed25519PrivateKey.generate()
    registry={'reviewer':base64.b64encode(private.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()}
    monkeypatch.setenv('OPENRAD_REVIEWER_KEYS',json.dumps(registry))
    with TestClient(server.app) as client:
        result=client.post('/api/v1/evaluations',json=case[0]).json()
        payload=dict(decision_hash=result['decision_hash'],session_id=result['session_id'],reviewer_id='reviewer',disposition='REJECTED',
                     justification='Held out cohort validation is required',nonce='api-review-nonce-00000001')
        signature=base64.b64encode(private.sign(canonical(payload))).decode()
        url=f"/api/v1/sessions/{result['session_id']}/reviews"
        assert client.post(url,json={'payload':payload,'signature_b64':signature}).status_code==200
        assert client.post(url,json={'payload':payload,'signature_b64':signature}).status_code==400
