from pathlib import Path
import pydicom
from pydicom.dataset import FileDataset,FileMetaDataset,Dataset
from pydicom.uid import ExplicitVRLittleEndian,generate_uid
from openrad.tools.dataset import discover_dataset


def make_pair(root, mismatch=False):
    frame=generate_uid();struct_uid=generate_uid();plan_uid=generate_uid();dose_uid=generate_uid()
    objects={}
    for modality,uid in [('RTSTRUCT',struct_uid),('RTPLAN',plan_uid),('RTDOSE',dose_uid)]:
        meta=FileMetaDataset();meta.TransferSyntaxUID=ExplicitVRLittleEndian
        ds=FileDataset(None,{},file_meta=meta,preamble=b'\0'*128)
        ds.is_little_endian=True;ds.is_implicit_VR=False
        ds.Modality=modality;ds.SOPInstanceUID=uid;ds.PatientID='synthetic';ds.FrameOfReferenceUID=frame
        objects[modality]=ds
    r=Dataset();r.ROINumber=1;r.ROIName='Brainstem';r.ReferencedFrameOfReferenceUID=generate_uid() if mismatch else frame
    objects['RTSTRUCT'].StructureSetROISequence=[r]
    ref=Dataset();ref.ReferencedSOPInstanceUID=struct_uid;objects['RTPLAN'].ReferencedStructureSetSequence=[ref]
    dose=objects['RTDOSE'];ref=Dataset();ref.ReferencedSOPInstanceUID=plan_uid;dose.ReferencedRTPlanSequence=[ref]
    dose.DoseGridScaling=.01;dose.DoseUnits='GY';dose.DoseType='PHYSICAL';dose.PixelSpacing=[1,1]
    dose.ImagePositionPatient=[0,0,0];dose.ImageOrientationPatient=[1,0,0,0,1,0];dose.GridFrameOffsetVector=[0,1];dose.NumberOfFrames=2
    for index,ds in enumerate(objects.values()):
        folder=root/f'arbitrary-folder-{index}';folder.mkdir(parents=True,exist_ok=True);ds.save_as(folder/'object.dcm')
    return objects


def test_uid_linkage_ignores_directory_names(tmp_path):
    make_pair(tmp_path)
    scan=discover_dataset(tmp_path)
    assert not scan['scan_errors']
    assert len(scan['dose_cases'])==1
    assert not scan['dose_cases'][0]['blockers']
    assert scan['dose_cases'][0]['rois'][0]['name']=='Brainstem'


def test_frame_mismatch_blocked(tmp_path):
    make_pair(tmp_path,mismatch=True)
    assert 'frame-of-reference' in discover_dataset(tmp_path)['dose_cases'][0]['blockers'][0]


def test_duplicate_uid_quarantined(tmp_path):
    objects=make_pair(tmp_path)
    objects['RTPLAN'].save_as(tmp_path/'duplicate.dcm')
    scan=discover_dataset(tmp_path)
    assert scan['scan_errors']
    assert scan['dose_cases'][0]['blockers']
