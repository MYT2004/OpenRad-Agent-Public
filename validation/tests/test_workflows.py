from types import SimpleNamespace
import numpy as np
import pytest
from openrad.tools.contours import sample_contour_doses
from openrad.core.agent import OpenRadAgent


def contour(z, shift=0, kind='CLOSED_PLANAR'):
    return SimpleNamespace(ContourGeometricType=kind,ContourData=[1+shift,1,z,3+shift,1,z,3+shift,3,z,1+shift,3,z])


def test_contour_spacing_not_dose_spacing_and_no_double_count():
    grid=np.full((3,8,8),50.)
    item=SimpleNamespace(ContourSequence=[contour(z) for z in (0,1,2)])
    doses,volume,thickness=sample_contour_doses(item,grid,np.array([0.,2.,4.]),0,0,1,1)
    assert volume == .001
    assert thickness == 1
    # Identical polygons must not double-count the same voxel.
    duplicate=SimpleNamespace(ContourSequence=item.ContourSequence*2)
    extra,v,_=sample_contour_doses(duplicate,grid,np.array([0.,2.,4.]),0,0,1,1)
    assert len(extra)==len(doses)


def test_contour_z_interpolation():
    grid=np.broadcast_to(np.array([0.,20.,40.])[:,None,None],(3,8,8))
    item=SimpleNamespace(ContourSequence=[contour(z) for z in (1,3)])
    doses,_,_=sample_contour_doses(item,grid,np.array([0.,2.,4.]),0,0,1,1)
    assert set(doses)=={10.,30.}


@pytest.mark.parametrize('seq', [[contour(0)], [contour(z) for z in (0,1,3)], [contour(z,10) for z in (0,1)], [contour(z,kind='POINT') for z in (0,1)]])
def test_unsupported_contours_block(seq):
    with pytest.raises(ValueError):
        sample_contour_doses(SimpleNamespace(ContourSequence=seq),np.ones((4,8,8)),np.arange(4.),0,0,1,1)


def test_no_synthetic_patient_results_or_prompt_execution(tmp_path):
    agent=OpenRadAgent(artifact_dir=str(tmp_path))
    assert not agent.run('Calculate patient NTCP').success
    assert not agent.run('Calculate DVH for my patient').success
    assert not agent.run("open('untrusted-file','w').write('bad')").success
    assert not (tmp_path/'untrusted-file').exists()
    assert not agent.run('Generate patient CT TOPAS deck at 150 MeV').success
    assert not agent.run('Generate TOPAS deck at -10 MeV').success


def test_llm_stub_is_explicit_failure(tmp_path):
    assert not OpenRadAgent(artifact_dir=str(tmp_path),llm_client=object()).run('DVH').success


def test_api_mapping_forwarded(monkeypatch,tmp_path):
    monkeypatch.setenv('STORAGE_DIR',str(tmp_path))
    from fastapi.testclient import TestClient
    import server
    captured={}
    def analyze(*args,**kwargs):captured.update(kwargs);return {'status':'test'}
    monkeypatch.setattr(server,'parse_and_evaluate_dvh',analyze)
    client=TestClient(server.app)
    res=client.post('/api/v1/dvh/analyze',json={'dicom_rtstruct_path':'struct','dicom_rtdose_path':'dose','roi_names':['Cord'],'reviewed_name_map':{'Cord':'SpinalCord'}})
    assert res.status_code==200
    assert captured['reviewed_name_map']=={'Cord':'SpinalCord'}
    assert client.get('/health').status_code==200
    assert client.post('/api/v1/agent/run',json={'prompt':'x','session_id':'../escape'}).status_code==400


def test_streamlit_all_modes_and_error_paths(monkeypatch):
    monkeypatch.setenv('OPENRAD_DATA_ROOTS','[]')
    from streamlit.testing.v1 import AppTest
    modes=['Interactive Agent Query','DICOM-RT & DVH Analyzer','Gamma Index QA (AAPM TG-218)','TOPAS Monte Carlo Deck Generator','Radiobiology (TCP / NTCP)','Stateful Python REPL Sandbox']
    from pathlib import Path
    app_path=Path(__file__).resolve().parents[2]/'frontend'/'app.py'
    at=AppTest.from_file(str(app_path),default_timeout=15).run()
    for mode in modes:
        at.sidebar.selectbox[0].select(mode).run()
        assert not at.exception, (mode,at.exception)
    at.sidebar.selectbox[0].select('Gamma Index QA (AAPM TG-218)').run()
    next(b for b in at.button if b.label=='Evaluate Gamma Index').click().run()
    assert at.error and not at.exception
    at.sidebar.selectbox[0].select('Radiobiology (TCP / NTCP)').run()
    at.radio[0].set_value('Poisson_LQ').run()
    next(b for b in at.button if b.label=='Calculate TCP / NTCP').click().run()
    assert at.error and not at.exception
    at.sidebar.selectbox[0].select('TOPAS Monte Carlo Deck Generator').run()
    next(b for b in at.button if b.label=='Generate TOPAS Deck').click().run()
    assert at.code and not at.exception


def test_radiobiology_explicit_semantics_and_uniform_dose():
    from openrad.tools.radiobio_tool import calculate_tcp_ntcp
    uniform={'dose_bins_Gy':[0,60],'volume_percent':[0,100]}
    result=calculate_tcp_ntcp(uniform,'LKB',{'TD50':60,'m':.15,'n':.25},dvh_type='differential')
    assert result['NTCP']==pytest.approx(.5)
    assert result['EUD_Gy']==pytest.approx(60)
    with pytest.raises(ValueError):
        calculate_tcp_ntcp(uniform,'LKB',{'TD50':60,'m':.15,'n':.25})
    with pytest.raises(ValueError):
        calculate_tcp_ntcp({'dose_bins_Gy':[0,20,40],'volume_percent':[100,50,0]},'Poisson_LQ',{})


def test_gamma_requires_spacing_and_matches_brute_force():
    from openrad.tools.gamma_tool import evaluate_gamma_index
    ref=np.array([[20.,30.],[40.,50.]])
    ev=np.array([[22.,29.],[35.,55.]])
    with pytest.raises(ValueError):evaluate_gamma_index(ref,ev)
    result=evaluate_gamma_index(ref,ev,reference_spacing_mm=[2,3],evaluated_spacing_mm=[2,3])
    points=np.array([[0,0],[0,3],[2,0],[2,3]])
    expected=[]
    for point,dose in zip(points,ref.ravel()):
        expected.append(np.min(np.sqrt(np.sum((points-point)**2,axis=1)/4 + ((ev.ravel()-dose)/1.5)**2)))
    assert result['passing_rate']==pytest.approx(100*np.mean(np.array(expected)<=1))
    assert result['average_gamma']==pytest.approx(np.mean(expected),abs=.001)
