"""Malformed export regressions using generated nonpatient DICOM objects."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pydicom
import pytest
from pydicom.dataset import Dataset
from validation.tests.test_submission import dicom_pair
from validation.tests.test_case_verification import case_files, run, codes
from src.tools import parse_and_evaluate_dvh
from src.storage import StorageManager, session_scope


def mutate(datasets, kind):
    d,s,p=datasets['dose'],datasets['struct'],datasets['plan']
    rc=s.ROIContourSequence[0];c=rc.ContourSequence[0]
    if kind=='point_count':c.NumberOfContourPoints=99
    elif kind=='duplicate_roi_contour':s.ROIContourSequence.append(deepcopy(rc))
    elif kind=='orphan_roi_contour':rc.ReferencedROINumber=99
    elif kind=='issuer':s.IssuerOfPatientID='OTHER_ISSUER'
    elif kind=='wrong_modality':s.Modality='RTPLAN'
    elif kind=='wrong_sop_class':s.SOPClassUID=d.SOPClassUID
    elif kind=='file_meta_uid':d.file_meta.MediaStorageSOPInstanceUID='2.25.123456789'
    elif kind=='spatial_transform':d.SpatialTransformOfDose='NON_RIGID'
    elif kind=='source_pixel_planes':
        item=Dataset();item.SpacingBetweenSlices=5
        rc.SourcePixelPlanesCharacteristicsSequence=[item]
    elif kind=='slab_thickness':c.add_new((0x3006,0x0044),'DS',5.)
    elif kind=='plan_frame':p.FrameOfReferenceUID='2.25.123456789'
    elif kind=='duplicate_plan_ref':d.ReferencedRTPlanSequence.append(deepcopy(d.ReferencedRTPlanSequence[0]))
    elif kind=='duplicate_struct_ref':p.ReferencedStructureSetSequence.append(deepcopy(p.ReferencedStructureSetSequence[0]))
    elif kind=='invalid_uid':d.SOPInstanceUID='bad-uid'
    elif kind=='offset_vector':c.add_new((0x3006,0x0045),'DS',[0.,0.,1.])


@pytest.mark.parametrize('kind',['point_count','duplicate_roi_contour','orphan_roi_contour','issuer','wrong_modality','wrong_sop_class','file_meta_uid','spatial_transform','source_pixel_planes','slab_thickness','offset_vector','plan_frame','duplicate_plan_ref','duplicate_struct_ref','invalid_uid'])
def test_direct_dvh_does_not_bypass_intake_checks(dicom_pair,tmp_path,kind):
    paths,datasets=dicom_pair;mutate(datasets,kind)
    for name,ds in datasets.items():ds.save_as(paths[name])
    with session_scope(StorageManager(str(tmp_path/'outputs')),'export-control'):
        try:
            result=parse_and_evaluate_dvh(paths['dose'],paths['struct'],['Brainstem'],rtplan_path=paths['plan'])
        except ValueError:
            pass
        else:
            assert not result['structures']['Brainstem']['found'], kind
    assert not list((tmp_path/'outputs').rglob('*.png'))


def test_core_dvh_checks_count_without_scrubber(dicom_pair):
    from openrad.tools.dicom_tool import analyze_dvh_datasets
    _,ds=dicom_pair;mutate(ds,'point_count')
    r=analyze_dvh_datasets(ds['struct'],ds['dose'],['Brainstem'],ds_plan=ds['plan'])
    assert not r['structures']['Brainstem']['found']


def test_intake_budget_checked_before_dose_decode(case_files,monkeypatch):
    from pydicom.dataset import Dataset
    monkeypatch.setenv('OPENRAD_MAX_DOSE_VOXELS','10')
    original=Dataset.pixel_array.fget
    decoded_dose=[]
    def checked(ds):
        if ds.Modality=='RTDOSE':decoded_dose.append(True)
        return original(ds)
    with patch.object(Dataset,'pixel_array',property(checked)):
        result=run(case_files)
    assert not decoded_dose
    assert 'dose_resource_budget' in codes(result)
    assert result['status']=='BLOCKED'


@pytest.mark.parametrize('kind',['duplicate_roi_contour','source_pixel_planes','spatial_transform'])
def test_intake_highlights_export_ambiguity(case_files,kind):
    source,ds,_,_=case_files;mutate(ds,kind)
    for name,d in ds.items():d.save_as(source/(name+'.dcm'))
    r=run(case_files)
    expected={'duplicate_roi_contour':'structure_integrity','source_pixel_planes':'contour_sampling_scope','spatial_transform':'dose_geometry'}[kind]
    assert expected in codes(r)


def test_fraction_dose_is_labelled_without_course_inference(dicom_pair,tmp_path):
    paths,ds=dicom_pair;ds['dose'].DoseSummationType='FRACTION';ds['dose'].save_as(paths['dose'])
    with session_scope(StorageManager(str(tmp_path/'out'))):
        r=parse_and_evaluate_dvh(paths['dose'],paths['struct'],['Brainstem'],rtplan_path=paths['plan'])
    assert r['dose_summation_type']=='FRACTION'
    assert any('course' in text.lower() and 'summation' in text.lower() for text in r['limitations'])


@pytest.mark.parametrize('kind',['issuer','summation_scope','file_meta_uid','wrong_sop_class','transformed_dose'])
def test_gamma_refuses_export_association_errors(dicom_pair,tmp_path,kind):
    from pydicom.uid import generate_uid
    from openrad.tools.gamma_tool import evaluate_gamma_index
    paths,ds=dicom_pair;d=pydicom.dcmread(paths['dose']);d.SOPInstanceUID=generate_uid();d.file_meta.MediaStorageSOPInstanceUID=d.SOPInstanceUID
    if kind=='issuer':d.IssuerOfPatientID='OTHER'
    elif kind=='summation_scope':d.DoseSummationType='FRACTION'
    elif kind=='file_meta_uid':d.file_meta.MediaStorageSOPInstanceUID='2.25.123456789'
    elif kind=='wrong_sop_class':d.SOPClassUID=ds['struct'].SOPClassUID
    elif kind=='transformed_dose':d.SpatialTransformOfDose='RIGID'
    other=tmp_path/'other-dose.dcm';d.save_as(other)
    with session_scope(StorageManager(str(tmp_path/'outputs'))):
        with pytest.raises(ValueError):evaluate_gamma_index(paths['dose'],str(other))


def test_gamma_accepts_supported_independent_dicom_objects(dicom_pair,tmp_path):
    from pydicom.uid import generate_uid
    from openrad.tools.gamma_tool import evaluate_gamma_index
    paths,ds=dicom_pair;d=pydicom.dcmread(paths['dose']);d.SOPInstanceUID=generate_uid();d.file_meta.MediaStorageSOPInstanceUID=d.SOPInstanceUID
    other=tmp_path/'independent-control.dcm';d.save_as(other)
    with session_scope(StorageManager(str(tmp_path/'outputs'))):
        result=evaluate_gamma_index(paths['dose'],str(other))
    assert result['passing_rate']==100 and not result['clinical_release']


def test_export_campaign_cannot_qualify_missing_baseline(tmp_path,monkeypatch):
    import json
    from validation.benchmarks.stress import patient_exports as runner
    raw=tmp_path/'case';raw.mkdir();output=tmp_path/'evidence'/'result.json'
    monkeypatch.setattr('sys.argv',['runner','--root',str(raw),'--output',str(output)])
    monkeypatch.setattr(runner,'audit_case',lambda root,label:{'case':label,'supported_baseline':False,'all_expected':False})
    with pytest.raises(SystemExit) as exc:runner.main()
    assert exc.value.code==2
    result=json.loads(output.read_text())
    assert not result['qualification_complete'] and not result['all_expected']
    assert result['executed_controls']==0


def test_export_campaign_cannot_write_under_input_root(tmp_path,monkeypatch):
    from validation.benchmarks.stress import patient_exports as runner
    raw=tmp_path/'case';raw.mkdir()
    monkeypatch.setattr('sys.argv',['runner','--root',str(raw),'--output',str(raw/'evidence'/'result.json')])
    monkeypatch.setattr(runner,'audit_case',lambda *args:pytest.fail('work must not start'))
    with pytest.raises(ValueError):runner.main()
    assert not list(raw.iterdir())
