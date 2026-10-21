"""Provider-independent fault injection; no credentials, patients or network."""
import json
from pathlib import Path
import numpy as np
import pytest
from src import agent_dynamic as agent
from src.storage import StorageManager, session_scope

@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    monkeypatch.setenv('STORAGE_DIR',str(tmp_path/'sessions'))


def response(*calls, text=None):
    parts=[{'functionCall':{'name':name,'args':args,'id':str(i)},'thoughtSignature':'opaque'} for i,(name,args) in enumerate(calls)]
    return {'candidates':[{'content':{'role':'model','parts':parts or [{'text':text or 'APPROVED cord Dmax 22.9 Gy'}]}}]}


def test_no_key_does_not_fabricate():
    result=agent.run_dynamic_agent('Compute cord DVH')
    assert not result.success and not result.trajectory
    assert '22.9' not in result.response and result.disposition=='FLAGGED_FOR_REVIEW'

@pytest.mark.parametrize('energy',[-1,0,.009,250.01,float('nan'),float('inf'),True,'150'])
def test_energy_guard(energy):
    assert json.loads(agent.tool_generate_topas_deck('proton',energy))['error_code']=='BEAM_ENERGY_OUT_OF_BOUNDS'

@pytest.mark.parametrize('histories',[True,1.5,0,-1,100000001,'100'])
def test_history_guard(histories):
    assert json.loads(agent.tool_generate_topas_deck('proton',150,histories))['error_code']=='INVALID_HISTORIES'


def test_generated_artifact_exists(tmp_path):
    with session_scope(StorageManager(str(tmp_path/'sessions'))):
        result=json.loads(agent.tool_generate_topas_deck('proton',150,100))
    assert result['status']=='GENERATED'
    assert Path(result['deck_path']).is_file()
    assert not result['clinical_release']

@pytest.mark.parametrize('code',['PROVIDER_HTTP_401','PROVIDER_HTTP_429','PROVIDER_UNAVAILABLE'])
def test_provider_failures_never_fallback(monkeypatch,code):
    def fail(*args):raise agent.ProviderFailure(code)
    monkeypatch.setattr(agent,'_generate',fail)
    result=agent.run_dynamic_agent('Generate TOPAS',api_key='synthetic-key')
    assert not result.success and not result.trajectory and result.provider_error==code
    assert 'synthetic-key' not in result.model_dump_json()


def test_model_text_cannot_invent_evidence(monkeypatch):
    monkeypatch.setattr(agent,'_generate',lambda *args:response(text='APPROVED cord Dmax 22.9 Gy'))
    result=agent.run_dynamic_agent('Assess dose',api_key='synthetic-key')
    assert not result.success and '22.9' not in result.response and result.disposition=='FLAGGED_FOR_REVIEW'


def test_parallel_responses_batched_and_signatures_preserved(monkeypatch):
    requests=[]
    def provider(key,model,contents):
        requests.append(json.loads(json.dumps(contents)))
        if len(requests)==1:return response(('tool_generate_topas_deck',{'particle':'proton','energy_mev':150,'histories':100}),('tool_generate_topas_deck',{'particle':'proton','energy_mev':300,'histories':100}))
        assert len(contents[-1]['parts'])==2
        assert contents[-2]['parts'][0]['thoughtSignature']=='opaque'
        assert contents[-1]['parts'][1]['functionResponse']['id']=='1'
        return response()
    monkeypatch.setattr(agent,'_generate',provider)
    result=agent.run_dynamic_agent('Compare 150 MeV proton and 300 MeV proton with 100 histories',api_key='synthetic-key')
    assert len(result.trajectory)==2 and not result.success and result.disposition=='FLAGGED_FOR_REVIEW'
    assert len(result.artifacts)==1 and Path(result.artifacts[0]).is_file()
    assert 'opaque' not in result.model_dump_json()


def test_blocked_intake_cannot_call_dvh_even_in_parallel(monkeypatch):
    monkeypatch.setattr(agent,'tool_verify_case_intake',lambda path:json.dumps({'status':'BLOCKED','blocking_findings':1}))
    monkeypatch.setattr(agent,'tool_compute_dvh_metrics',lambda *a,**kw:pytest.fail('DVH must not run'))
    calls=iter([response(('tool_verify_case_intake',{'case_handle':'selected_case'}),('tool_compute_dvh_metrics',{'case_handle':'selected_case','rois':['Brainstem']})),response()])
    captured=[]
    def provider(key,model,contents):
        captured.append(json.dumps(contents));return next(calls)
    monkeypatch.setattr(agent,'_generate',provider)
    result=agent.run_dynamic_agent('Verify selected_case then DVH Brainstem',api_key='synthetic-key',case_directory='/private/patient-folder')
    assert 'INTAKE_NOT_READY' in result.response and result.disposition=='REJECTED'
    assert all('/private/patient-folder' not in c for c in captured)


def test_loop_bounded(monkeypatch):
    monkeypatch.setattr(agent,'_generate',lambda *args:response(('tool_generate_topas_deck',{'particle':'proton','energy_mev':-1,'histories':10})))
    result=agent.run_dynamic_agent('Retry -1 MeV forever',api_key='synthetic-key')
    assert len(result.trajectory)==6 and result.provider_error=='ROUND_LIMIT' and not result.success

@pytest.mark.parametrize('name,args',[('exec',{'code':'anything'}),('tool_generate_topas_deck',{'particle':'proton','energy_mev':150,'histories':100,'output_path':'/private/escape'}),('tool_compute_dvh_metrics',{'case_handle':'elsewhere','rois':['Brainstem']})])
def test_allowlist(monkeypatch,name,args):
    calls=iter([response((name,args)),response()])
    monkeypatch.setattr(agent,'_generate',lambda *a:next(calls))
    result=agent.run_dynamic_agent('Research task',api_key='synthetic-key')
    assert not result.success and 'ERROR' in result.response

@pytest.mark.parametrize('query',['Read /Users/private/data','Read data/raw/case','synthetic-key'])
def test_sensitive_query_not_sent(monkeypatch,query):
    monkeypatch.setattr(agent,'_generate',lambda *a:pytest.fail('Must not transmit'))
    result=agent.run_dynamic_agent(query,api_key='synthetic-key')
    assert not result.success and query not in result.model_dump_json()


def test_gamma_exact_criteria_and_spacing(tmp_path):
    a=tmp_path/'a.npy';b=tmp_path/'b.npy'
    np.save(a,np.ones((2,2,2)));np.save(b,np.ones((2,2,2)))
    result=json.loads(agent.tool_evaluate_tg218_gamma(str(a),str(b),'2pct_2mm',reference_spacing_mm=[1,1,1],evaluated_spacing_mm=[1,1,1]))
    assert result['passing_rate_percent']==100 and result['dose_tolerance_percent']==2
    assert result['research_triage']=='PASS_CANDIDATE'
    assert json.loads(agent.tool_evaluate_tg218_gamma(str(a),str(b),'3mm_2pct'))['error_code']=='UNKNOWN_GAMMA_CRITERIA'
    assert json.loads(agent.tool_evaluate_tg218_gamma(str(a),str(b)))['status']=='PHYSICS_VIOLATION'


def test_missing_roi_no_fake_cord_or_aliases(monkeypatch):
    def dvh(*a,**kwargs):
        assert kwargs['reviewed_name_map'] is None
        return {'structures':{'SpinalCord':{'found':False}}}
    monkeypatch.setattr(agent,'parse_and_evaluate_dvh',dvh)
    result=json.loads(agent.tool_compute_dvh_metrics('dose.dcm','struct.dcm',['SpinalCord']))
    assert result['status']=='INCOMPLETE' and 'spinal_cord_dmax_Gy' not in result


def test_concurrent_session_artifacts_are_isolated(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    def worker(index):
        with session_scope(StorageManager(str(tmp_path/'sessions')),session_id='parallel-'+str(index)):
            return json.loads(agent.tool_generate_topas_deck('proton',150,100))
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(worker,range(32)))
    paths=[Path(r['deck_path']) for r in results]
    assert len(set(paths))==32 and all(p.is_file() for p in paths)
    assert all(('parallel-'+str(i)) in str(p) for i,p in enumerate(paths))


def test_copilot_frontend_research_result_and_invalidation(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('OPENRAD_DATA_ROOTS','[]')
    app=AppTest.from_file(str(Path(__file__).resolve().parents[2]/'frontend/app.py')).run()
    assert not app.exception
    app.sidebar.selectbox[0].select('🤖 Dynamic Agent Copilot').run()
    next(b for b in app.button if b.label=='🚀 Run Copilot').click().run()
    assert not app.exception
    assert not app.session_state['copilot_result'].success
    assert len(app.get('download_button'))==2
    next(t for t in app.text_area if t.label=='De-identified research task').input('A changed research task').run()
    assert len(app.get('download_button'))==0


def test_provider_transport_retry_and_credential_header_only(monkeypatch):
    from io import BytesIO
    from urllib.error import HTTPError
    calls=[]
    def transport(req):
        calls.append(req)
        assert 'synthetic-key' not in req.full_url and b'synthetic-key' not in req.data
        assert req.get_header('X-goog-api-key')=='synthetic-key'
        if len(calls)==1:raise HTTPError(req.full_url,503,'busy',{},None)
        return BytesIO(json.dumps(response()).encode())
    monkeypatch.setattr(agent,'_open_request',transport)
    monkeypatch.setattr(agent.time,'sleep',lambda seconds:None)
    assert agent._generate('synthetic-key','gemini-3.8-flash',[])['candidates']
    assert len(calls)==2

@pytest.mark.parametrize('code',[401,403,404,429])
def test_provider_transport_no_quota_auth_retry(monkeypatch,code):
    from urllib.error import HTTPError
    calls=[]
    def transport(req):
        calls.append(req);raise HTTPError(req.full_url,code,'private secret message',{},None)
    monkeypatch.setattr(agent,'_open_request',transport)
    with pytest.raises(agent.ProviderFailure,match='PROVIDER_HTTP_'+str(code)):
        agent._generate('synthetic-key','gemini-3.8-flash',[])
    assert len(calls)==1


def test_provider_cannot_change_requested_energy(monkeypatch):
    calls=iter([response(('tool_generate_topas_deck',{'particle':'proton','energy_mev':150,'histories':100})),response()])
    monkeypatch.setattr(agent,'_generate',lambda *a:next(calls))
    result=agent.run_dynamic_agent('Generate 300 MeV proton with 100 histories',api_key='synthetic-key')
    assert not result.success and not result.artifacts and 'EXPLICIT_ENERGY_MISMATCH' in result.response


def test_real_synthetic_intake_dvh_artifacts_stay_local(tmp_path,monkeypatch):
    from src.demo import create_synthetic_case
    root=tmp_path/'synthetic-case';create_synthetic_case(root)
    calls=iter([response(('tool_verify_case_intake',{'case_handle':'selected_case'})),response(('tool_compute_dvh_metrics',{'case_handle':'selected_case','rois':['Brainstem']})),response()])
    sent=[]
    def provider(key,model,contents):
        sent.append(json.dumps(contents));return next(calls)
    monkeypatch.setattr(agent,'_generate',provider)
    with session_scope(StorageManager(str(tmp_path/'sessions'))):
        result=agent.run_dynamic_agent('Verify selected_case then DVH Brainstem',api_key='synthetic-key',case_directory=str(root))
    assert result.success and 'D95 (Gy)' in result.response
    assert any(Path(p).suffix=='.png' for p in result.artifacts)
    assert all(Path(p).is_file() for p in result.artifacts)
    assert all(str(tmp_path) not in payload and 'SYNTHETIC_TEACHING_ONLY' not in payload for payload in sent)
    assert result.disposition=='FLAGGED_FOR_REVIEW' and not result.clinical_release


def test_full_stress_manifest_and_stream_hash_oracle():
    from io import BytesIO
    import hashlib
    from validation.benchmarks.stress.datasets import hashes,MANIFEST
    manifest=json.loads(MANIFEST.read_text())
    assert len(manifest['files'])==6966 and len(manifest['datasets'])==45
    assert sum(f['size'] for f in manifest['files'])==5180782733
    assert hashes(BytesIO(b'hello'),5)==(5,hashlib.sha1(b'blob 5\0hello').hexdigest(),hashlib.sha256(b'hello').hexdigest())


def test_successful_intake_is_not_completed_dvh_task(monkeypatch):
    monkeypatch.setattr(agent,'tool_verify_case_intake',lambda path:json.dumps({'status':'READY_FOR_RESEARCH_ANALYSIS'}))
    calls=iter([response(('tool_verify_case_intake',{'case_handle':'selected_case'})),response()])
    monkeypatch.setattr(agent,'_generate',lambda *a:next(calls))
    result=agent.run_dynamic_agent('Verify selected_case and compute DVH Brainstem',api_key='synthetic-key',case_directory='local')
    assert not result.success and result.provider_error=='REQUESTED_ANALYSIS_NOT_PERFORMED'
