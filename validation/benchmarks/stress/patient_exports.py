"""Read-only export fault campaign; mutations exist only in scrubbed memory copies.

Run with explicit authorized case roots and a separate output JSON. Published
results contain pseudonymous case labels, counts and verdicts, never source paths.
A successful baseline is required per root; no skipped baseline qualifies.
"""
from copy import deepcopy
from pathlib import Path
import argparse
import hashlib
import json
import numpy as np
import pydicom
from pydicom.dataset import Dataset
from openrad.tools.dataset import discover_dataset
from openrad.tools.dicom_tool import analyze_dvh_datasets
from src.privacy import scrub_analysis_copies
from src.resources import preflight_dicom_dose
from validation.paths import reserve_evidence, write_evidence


def mutations():
    def source_planes(d,s,p):
        item=Dataset();item.SpacingBetweenSlices=5
        s.ROIContourSequence[0].SourcePixelPlanesCharacteristicsSequence=[item]
    def duplicate(d,s,p):s.ROIContourSequence.append(deepcopy(s.ROIContourSequence[0]))
    return {
        'plan_frame':lambda d,s,p:setattr(p,'FrameOfReferenceUID','2.25.123456789'),
        'duplicate_plan_reference':lambda d,s,p:d.ReferencedRTPlanSequence.append(deepcopy(d.ReferencedRTPlanSequence[0])),
        'duplicate_struct_reference':lambda d,s,p:p.ReferencedStructureSetSequence.append(deepcopy(p.ReferencedStructureSetSequence[0])),
        'point_count':lambda d,s,p:setattr(s.ROIContourSequence[0].ContourSequence[0],'NumberOfContourPoints',999999),
        'duplicate_roi_association':duplicate,
        'orphan_roi_association':lambda d,s,p:setattr(s.ROIContourSequence[0],'ReferencedROINumber',999999),
        'issuer_mismatch':lambda d,s,p:setattr(s,'IssuerOfPatientID','OTHER_ISSUER'),
        'wrong_structure_modality':lambda d,s,p:setattr(s,'Modality','RTPLAN'),
        'wrong_structure_sop_class':lambda d,s,p:setattr(s,'SOPClassUID',d.SOPClassUID),
        'file_meta_identity':lambda d,s,p:setattr(d.file_meta,'MediaStorageSOPInstanceUID','2.25.123456789'),
        'transformed_dose':lambda d,s,p:setattr(d,'SpatialTransformOfDose','NON_RIGID'),
        'source_pixel_planes':source_planes,
        'explicit_slab':lambda d,s,p:s.ROIContourSequence[0].ContourSequence[0].add_new((0x3006,0x0044),'DS',5.),
        'explicit_offset':lambda d,s,p:s.ROIContourSequence[0].ContourSequence[0].add_new((0x3006,0x0045),'DS',[0.,0.,1.]),
        'negative_scaling':lambda d,s,p:setattr(d,'DoseGridScaling',-.001),
        'zero_scaling':lambda d,s,p:setattr(d,'DoseGridScaling',0.),
        'relative_dose':lambda d,s,p:setattr(d,'DoseUnits','RELATIVE'),
        'frame_mismatch':lambda d,s,p:setattr(d,'FrameOfReferenceUID','2.25.123456789'),
        'wrong_plan_link':lambda d,s,p:setattr(d.ReferencedRTPlanSequence[0],'ReferencedSOPInstanceUID','2.25.123456789'),
        'nonorthogonal_orientation':lambda d,s,p:setattr(d,'ImageOrientationPatient',[1,0,0,1,0,0]),
        'duplicate_dose_planes':lambda d,s,p:setattr(d,'GridFrameOffsetVector',[0]*int(d.NumberOfFrames)),
    }


def _sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1048576),b''):h.update(chunk)
    return h.hexdigest()


def audit_case(root,label):
    discovery=discover_dataset(root)
    for pair in discovery['dose_cases']:
        if pair['blockers']:continue
        paths=[pair['dose_path'],pair['struct_path'],pair['plan_path']]
        before=[_sha(p) for p in paths]
        preflight_dicom_dose(paths[0])
        sources=[pydicom.dcmread(p) for p in paths]
        d,s,p,_=scrub_analysis_copies(*sources)
        # Select one supported canonical ROI without changing its geometry.
        # Unknown aliases and unsupported contours are never auto-repaired.
        names=[str(roi.ROIName) for roi in s.StructureSetROISequence]
        names.sort(key=lambda n:(n not in ('Brainstem','Bladder','SpinalCord'),n))
        baseline=None
        for name in names:
            r=analyze_dvh_datasets(s,d,[name],ds_plan=p)
            if r['structures'][name].get('found'):
                baseline=name;break
        if baseline is None:continue
        number=r['structures'][baseline]['roi_number']
        # Only the selected ROI enters the controlled campaign, so each fault
        # targets a measured structure rather than an unrelated contour.
        s.StructureSetROISequence=[roi for roi in s.StructureSetROISequence if int(roi.ROINumber)==number]
        s.ROIContourSequence=[roi for roi in s.ROIContourSequence if int(roi.ReferencedROINumber)==number]
        outcomes=[]
        for kind,change in mutations().items():
            dose,struct,plan=deepcopy(d),deepcopy(s),deepcopy(p)
            change(dose,struct,plan)
            try:
                dose,struct,plan,_=scrub_analysis_copies(dose,struct,plan)
                result=analyze_dvh_datasets(struct,dose,[baseline],ds_plan=plan)
                refused=not result['structures'][baseline].get('found',False)
            except ValueError:
                refused=True
            outcomes.append({'control':kind,'expected_refusal':True,'refused':refused})
        unchanged=before==[_sha(path) for path in paths]
        if not unchanged:raise RuntimeError('Protected source bytes changed')
        return {'case':label,'supported_baseline':True,'controls':outcomes,
                'all_expected':all(c['refused'] for c in outcomes),'selected_source_files_unchanged':unchanged}
    return {'case':label,'supported_baseline':False,'all_expected':False,
            'reason':'No unambiguous linked course with a supported canonical ROI; qualification incomplete.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',action='append',required=True,help='Authorized case root, read only')
    parser.add_argument('--output',required=True,help='New separate evidence JSON')
    args=parser.parse_args()
    from src.case_verification import ensure_case_output_separation
    for root in args.root:ensure_case_output_separation(root,Path(args.output).resolve().parent)
    with reserve_evidence(Path(args.output)):
        cases=[audit_case(root,f'case-{i:03d}') for i,root in enumerate(args.root,1)]
        result={'scope':'Selected-ROI export engineering controls, not independent clinical model qualification',
                'raw_files_edited':False,'cases':cases,'all_expected':all(c['all_expected'] for c in cases),
                'qualification_complete':all(c['supported_baseline'] for c in cases),
                'all_executed_controls_expected':all(v['refused'] for c in cases for v in c.get('controls',[])),
                'executed_controls':sum(len(c.get('controls',[])) for c in cases)}
        write_evidence(Path(args.output),result)
    print(json.dumps({'cases':len(cases),'all_expected':result['all_expected']}))
    if not result['all_expected']:raise SystemExit(2)


if __name__=='__main__':main()
