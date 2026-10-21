"""Independent analytic, privacy, CLI and REST regression checks for OSI tools."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pydicom
import pytest
from pydicom.dataset import FileDataset,FileMetaDataset,Dataset
from pydicom.uid import ExplicitVRLittleEndian,RTDoseStorage,RTStructureSetStorage,RTPlanStorage,generate_uid
from src.tools import parse_and_evaluate_dvh,generate_topas_file
from src.storage import StorageManager,session_scope
from src.hooks import post_tool_call


@pytest.fixture
def dicom_pair(tmp_path):
    uid={name:generate_uid() for name in ('dose','struct','plan','frame')}
    datasets={}
    for name,modality,cls in [('dose','RTDOSE',RTDoseStorage),('struct','RTSTRUCT',RTStructureSetStorage),('plan','RTPLAN',RTPlanStorage)]:
        meta=FileMetaDataset();meta.TransferSyntaxUID=ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID=cls;meta.MediaStorageSOPInstanceUID=uid[name]
        ds=FileDataset(None,{},file_meta=meta,preamble=b'\0'*128)
        ds.is_little_endian=True;ds.is_implicit_VR=False
        ds.SOPClassUID=cls;ds.SOPInstanceUID=uid[name];ds.FrameOfReferenceUID=uid['frame'];ds.Modality=modality
        ds.PatientID='PRIVATE_SENTINEL';ds.PatientName='PRIVATE_SENTINEL';ds.PatientBirthDate='19700101'
        ds.InstitutionName='PRIVATE_SENTINEL';ds.StudyDescription='PRIVATE_SENTINEL'
        ds.add_new((0x0011,0x0010),'LO','PRIVATE_SENTINEL')
        datasets[name]=ds
    dose=datasets['dose'];dose.DoseUnits='GY';dose.DoseType='PHYSICAL';dose.DoseGridScaling=.01
    dose.Rows=5;dose.Columns=5;dose.NumberOfFrames=3;dose.PixelSpacing=[1,1]
    dose.ImagePositionPatient=[0,0,0];dose.ImageOrientationPatient=[1,0,0,0,1,0];dose.GridFrameOffsetVector=[0,1,2]
    dose.SamplesPerPixel=1;dose.PhotometricInterpretation='MONOCHROME2';dose.BitsAllocated=16;dose.BitsStored=16;dose.HighBit=15;dose.PixelRepresentation=0
    dose.PixelData=np.full((3,5,5),6000,dtype='<u2').tobytes()
    ref=Dataset();ref.ReferencedSOPInstanceUID=uid['plan'];dose.ReferencedRTPlanSequence=[ref]
    ref=Dataset();ref.ReferencedSOPInstanceUID=uid['struct'];datasets['plan'].ReferencedStructureSetSequence=[ref]
    r=Dataset();r.ROINumber=1;r.ROIName='Brainstem';r.ReferencedFrameOfReferenceUID=uid['frame']
    datasets['struct'].StructureSetROISequence=[r]
    contours=[]
    for z in (0,1):
        c=Dataset();c.ContourGeometricType='CLOSED_PLANAR';c.NumberOfContourPoints=4
        c.ContourData=[0,0,z,4,0,z,4,4,z,0,4,z];c.add_new((0x0010,0x0010),'PN','PRIVATE_SENTINEL');contours.append(c)
    rc=Dataset();rc.ReferencedROINumber=1;rc.ContourSequence=contours;datasets['struct'].ROIContourSequence=[rc]
    paths={}
    for name,ds in datasets.items():
        path=tmp_path/(name+'.dcm');ds.save_as(path);paths[name]=str(path)
    return paths,datasets


def test_uniform_dvh_privacy_and_unchanged_source(dicom_pair,tmp_path):
    paths,sources=dicom_pair
    before={name:hashlib.sha256(Path(path).read_bytes()).hexdigest() for name,path in paths.items()}
    manager=StorageManager(str(tmp_path/'sessions'))
    with session_scope(manager,'test-session'):
        result=parse_and_evaluate_dvh(paths['dose'],paths['struct'],['Brainstem'],rtplan_path=paths['plan'])
    metrics=result['structures']['Brainstem']['tg263_metrics']
    assert metrics=={'D95%[Gy]':60.,'D50%[Gy]':60.,'D2%[Gy]':60.,'V50Gy[%]':100.,'V50Gy[cc]':pytest.approx(result['structures']['Brainstem']['volume_cc'],abs=.001)}
    assert result['structures']['Brainstem']['mean_dose_Gy']==60.
    assert result['course_linkage_verified']
    assert '_physics' not in result
    payload=json.dumps(result)
    assert 'PRIVATE_SENTINEL' not in payload
    assert str(sources['dose'].SOPInstanceUID) not in payload
    plots=list((tmp_path/'sessions'/'test-session'/'artifacts').glob('*.png'))
    assert len(plots)==1 and plots[0].read_bytes().startswith(b'\x89PNG')
    assert b'PRIVATE_SENTINEL' not in plots[0].read_bytes()
    assert before=={name:hashlib.sha256(Path(path).read_bytes()).hexdigest() for name,path in paths.items()}


def test_recursive_metadata_allowlist(dicom_pair):
    from src.privacy import scrub_analysis_copies
    _,sources=dicom_pair
    dose,struct,plan,_=scrub_analysis_copies(sources['dose'],sources['struct'],sources['plan'])
    for ds in (dose,struct,plan):
        assert 'PRIVATE_SENTINEL' not in str(ds)
        assert not any(e.is_private for e in ds.iterall())
        assert 'PatientName' not in ds and 'PatientBirthDate' not in ds
    assert dose.FrameOfReferenceUID==struct.StructureSetROISequence[0].ReferencedFrameOfReferenceUID
    assert dose.ReferencedRTPlanSequence[0].ReferencedSOPInstanceUID==plan.SOPInstanceUID
    assert sources['dose'].PatientName=='PRIVATE_SENTINEL'


@pytest.mark.parametrize('grid,expected',[(np.array([[[-1.]]]),[1,1,1]),(np.ones((2,2)),[2,2,2]),(np.ones((2,2,2)),[2,2,3]),(np.full((2,2,2),np.nan),[2,2,2])])
def test_post_tool_hook_rejects_invalid_dose(grid,expected):
    @post_tool_call
    def faulty():return {'_physics':{'dose_grid':grid,'expected_shape':expected}}
    with pytest.raises(ValueError):faulty()


def test_corrupt_pixel_shape_creates_no_artifact(dicom_pair,tmp_path):
    paths,sources=dicom_pair
    sources['dose'].NumberOfFrames=4;sources['dose'].save_as(paths['dose'])
    with session_scope(StorageManager(str(tmp_path/'sessions')),'bad-shape'):
        with pytest.raises(ValueError):parse_and_evaluate_dvh(paths['dose'],paths['struct'],['Brainstem'])
    assert not list((tmp_path/'sessions').rglob('*.png'))


def test_identity_mismatch_not_hidden_by_anonymisation(dicom_pair):
    paths,sources=dicom_pair
    sources['struct'].PatientID='OTHER';sources['struct'].save_as(paths['struct'])
    with pytest.raises(ValueError):parse_and_evaluate_dvh(paths['dose'],paths['struct'],['Brainstem'])


def test_three_argument_tool_marks_unverified_course(dicom_pair,tmp_path,monkeypatch):
    paths,_=dicom_pair;monkeypatch.setenv('STORAGE_DIR',str(tmp_path/'sessions'))
    result=parse_and_evaluate_dvh(paths['dose'],paths['struct'],['Brainstem'])
    assert not result['course_linkage_verified']
    assert result['structures']['Brainstem']['found']


def test_topas_bounds_complete_deck_and_no_overwrite(tmp_path):
    output=tmp_path/'topas.txt'
    result=generate_topas_file('proton',150.,1000,str(output))
    assert result['status']=='generated'
    deck=output.read_text()
    for marker in ('Ge/World/','Ph/Default/Modules','Ge/BeamPosition/Type','Sc/DoseScorer/','NumberOfHistoriesInRun = 1000'):
        assert marker in deck
    with pytest.raises(FileExistsError):generate_topas_file('proton',150.,1000,str(output))
    with pytest.raises(ValueError):generate_topas_file('proton',float('nan'),1000,str(tmp_path/'bad.txt'))
    assert not (tmp_path/'bad.txt').exists()


def test_cli_and_api_end_to_end(dicom_pair,tmp_path,capsys,monkeypatch):
    from agent_main import main
    from fastapi.testclient import TestClient
    import server
    paths,_=dicom_pair
    assert main(['--storage-dir',str(tmp_path/'cli'),'dvh','--rtdose',paths['dose'],'--rtstruct',paths['struct'],'--rtplan',paths['plan'],'--roi','Brainstem'])==0
    assert json.loads(capsys.readouterr().out)['artifacts']
    monkeypatch.setattr(server,'storage_mgr',StorageManager(str(tmp_path/'api')))
    client=TestClient(server.app)
    response=client.post('/api/v1/dvh/analyze',json={'rtdose_path':paths['dose'],'rtstruct_path':paths['struct'],'rtplan_path':paths['plan'],'rois':['Brainstem']})
    assert response.status_code==200,response.text
    artifact=response.json()['artifacts'][0]
    assert client.get(artifact).headers['content-type']=='image/png'
    assert 'PRIVATE_SENTINEL' not in response.text
    topas=client.post('/api/v1/topas/generate',json={'particle':'proton','energy_mev':150,'histories':1000})
    assert topas.status_code==200
    assert 'Ge/World/' in client.get(topas.json()['artifacts'][0]).text
    assert client.get('/artifacts/any/trajectory.json').status_code==404


def test_dynamic_port_and_shared_skill_paths(monkeypatch):
    import server,uvicorn,agent_main
    captured={}
    monkeypatch.setenv('PORT','9091')
    monkeypatch.setattr(uvicorn,'run',lambda *args,**kwargs:captured.update(kwargs))
    server.main()
    assert captured['port']==9091 and captured['host']=='0.0.0.0'
    assert server.skills_paths==agent_main.skills_paths==['./skills/radiation_physics','./SKILL.md']


def test_pymedphys_receives_scrubbed_metadata(dicom_pair,tmp_path,monkeypatch):
    import pymedphys
    paths,_=dicom_pair
    original=pymedphys.dicom.zyx_and_dose_from_dataset
    seen=[]
    def checked(dataset):
        assert dataset.PatientID=='ANON'
        assert 'PRIVATE_SENTINEL' not in str(dataset)
        seen.append(True)
        return original(dataset)
    monkeypatch.setattr(pymedphys.dicom,'zyx_and_dose_from_dataset',checked)
    with session_scope(StorageManager(str(tmp_path/'sessions')),'scrub-check'):
        parse_and_evaluate_dvh(paths['dose'],paths['struct'],['Brainstem'])
    assert seen


def test_dose_parser_coordinate_discrepancy_blocked(dicom_pair,tmp_path,monkeypatch):
    import pymedphys
    paths,_=dicom_pair
    original=pymedphys.dicom.zyx_and_dose_from_dataset
    def shifted(dataset):
        axes,dose=original(dataset)
        return tuple(np.asarray(axis)+10 for axis in axes),dose
    monkeypatch.setattr(pymedphys.dicom,'zyx_and_dose_from_dataset',shifted)
    with session_scope(StorageManager(str(tmp_path/'sessions')),'axis-mismatch'):
        with pytest.raises(ValueError,match='coordinates disagree'):
            parse_and_evaluate_dvh(paths['dose'],paths['struct'],['Brainstem'])
    assert not list((tmp_path/'sessions').rglob('*.png'))
