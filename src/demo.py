"""Explicit synthetic teaching fixture. Never substitutes for patient data.

Small, deliberately minimal DICOM objects exercise OpenRad's supported subset;
these are not complete clinical IOD examples or commissioned dose distributions.
"""
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL
import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset, Dataset
from pydicom.uid import CTImageStorage,RTDoseStorage,RTPlanStorage,RTStructureSetStorage,ExplicitVRLittleEndian
from src.readonly import assert_output_path


def create_synthetic_case(output_dir, defect='none'):
    if defect not in ('none','missing_slice','wrong_frame','negative_dose_scaling'):
        raise ValueError('Unknown synthetic defect')
    root=assert_output_path(output_dir)
    root.mkdir(parents=True,exist_ok=False)  # never modifies an existing dataset
    def uid(role):return '2.25.'+str(uuid5(NAMESPACE_URL,'openrad.synthetic.case.v1.'+role).int)
    def dataset(modality,sop_class,role):
        meta=FileMetaDataset();meta.TransferSyntaxUID=ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID=sop_class;meta.MediaStorageSOPInstanceUID=uid(role)
        ds=FileDataset(None,{},file_meta=meta,preamble=b'\0'*128)
        ds.is_little_endian=True;ds.is_implicit_VR=False
        ds.SOPClassUID=sop_class;ds.SOPInstanceUID=uid(role);ds.Modality=modality
        ds.PatientName='SYNTHETIC^TEACHING';ds.PatientID='SYNTHETIC_TEACHING_ONLY'
        ds.StudyInstanceUID=uid('study');ds.SeriesInstanceUID=uid('series-'+modality)
        ds.FrameOfReferenceUID=uid('frame');ds.BurnedInAnnotation='NO'
        ds.StudyDescription='SYNTHETIC NONCLINICAL DEMO'
        return ds
    def pixels(ds,values):
        ds.Rows=values.shape[-2];ds.Columns=values.shape[-1]
        ds.SamplesPerPixel=1;ds.PhotometricInterpretation='MONOCHROME2'
        ds.BitsAllocated=16;ds.BitsStored=16;ds.HighBit=15;ds.PixelRepresentation=0
        ds.PixelData=np.asarray(values,dtype='<u2').tobytes()
    def ref(sop_class,role):
        item=Dataset();item.ReferencedSOPClassUID=sop_class;item.ReferencedSOPInstanceUID=uid(role);return item
    images=[]
    for z in range(5):
        ds=dataset('CT',CTImageStorage,f'ct-{z}')
        ds.ImageType=['ORIGINAL','PRIMARY','AXIAL'];ds.ImageOrientationPatient=[1,0,0,0,1,0]
        ds.ImagePositionPatient=[0,0,2*z];ds.PixelSpacing=[2,2];ds.SliceThickness=2;ds.SpacingBetweenSlices=2
        ds.InstanceNumber=z+1;ds.RescaleSlope=1;ds.RescaleIntercept=-1000;ds.RescaleType='HU'
        pixels(ds,np.full((32,32),1000))
        images.append(ds)
        if defect!='missing_slice' or z!=2:ds.save_as(root/f'synthetic_ct_{z:02d}.dcm')
    dose=dataset('RTDOSE',RTDoseStorage,'dose')
    dose.DoseUnits='GY';dose.DoseType='PHYSICAL';dose.DoseSummationType='PLAN'
    dose.DoseGridScaling=-.01 if defect=='negative_dose_scaling' else .01
    dose.ImageOrientationPatient=[1,0,0,0,1,0];dose.ImagePositionPatient=[0,0,0]
    dose.PixelSpacing=[2,2];dose.NumberOfFrames=5;dose.GridFrameOffsetVector=[0,2,4,6,8]
    values=np.broadcast_to(np.linspace(1000,6000,32,dtype=int),(5,32,32))
    pixels(dose,values);dose.ReferencedRTPlanSequence=[ref(RTPlanStorage,'plan')]
    dose.save_as(root/'synthetic_dose.dcm')
    plan=dataset('RTPLAN',RTPlanStorage,'plan');plan.RTPlanLabel='SYNTHETIC';plan.RTPlanGeometry='PATIENT'
    plan.ReferencedStructureSetSequence=[ref(RTStructureSetStorage,'struct')]
    plan.save_as(root/'synthetic_plan.dcm')
    struct=dataset('RTSTRUCT',RTStructureSetStorage,'struct');struct.StructureSetLabel='SYNTHETIC'
    struct.StructureSetROISequence=[];struct.ROIContourSequence=[]
    for number,name,bounds in [(1,'Brainstem',(4,16,4,16)),(2,'PTV',(36,52,24,40))]:
        roi=Dataset();roi.ROINumber=number;roi.ROIName=name
        roi.ReferencedFrameOfReferenceUID=uid('wrong-frame' if defect=='wrong_frame' else 'frame')
        struct.StructureSetROISequence.append(roi)
        rc=Dataset();rc.ReferencedROINumber=number;rc.ContourSequence=[]
        x1,x2,y1,y2=bounds
        for z in range(5):
            contour=Dataset();contour.ContourGeometricType='CLOSED_PLANAR';contour.NumberOfContourPoints=4
            contour.ContourData=[x1,y1,2*z,x2,y1,2*z,x2,y2,2*z,x1,y2,2*z]
            contour.ContourImageSequence=[ref(CTImageStorage,f'ct-{z}')]
            rc.ContourSequence.append(contour)
        struct.ROIContourSequence.append(rc)
    series=Dataset();series.SeriesInstanceUID=uid('series-CT')
    series.ContourImageSequence=[ref(CTImageStorage,f'ct-{z}') for z in range(5)]
    study=Dataset();study.RTReferencedSeriesSequence=[series]
    frame=Dataset();frame.FrameOfReferenceUID=uid('frame');frame.RTReferencedStudySequence=[study]
    struct.ReferencedFrameOfReferenceSequence=[frame]
    struct.save_as(root/'synthetic_struct.dcm')
    return dict(status='generated',synthetic=True,clinical_release=False,root=str(root),case_id='synthetic-demo',
                defect=defect,expected_intake_state='READY_FOR_RESEARCH_ANALYSIS' if defect=='none' else 'BLOCKED',
                limitations=['Artificial geometry and dose; not patient data, a complete clinical IOD, a beam model or clinical validation.'])
