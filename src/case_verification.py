"""Read-only case intake checks; no registration, repair or clinical release.

Only pseudonymous file/series/ROI labels and content hashes enter exported results.
DICOM metadata and documents are data, never execution instructions.
"""
from collections import Counter, defaultdict
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import warnings
import numpy as np
import pydicom
from pydantic import BaseModel, ConfigDict, Field
from pydicom.uid import CTImageStorage, RTDoseStorage, RTPlanStorage, RTStructureSetStorage
from openrad.tools.dose_geometry import validate_axial_dose
from openrad.validation.nomenclature import build_roi_index, check_structure_name
from src.governance import digest, append_record
from src.storage import current_session
from src.demo import has_synthetic_teaching_marker


class CaseVerificationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    root: str = Field(min_length=1)
    case_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    check_pixels: bool = True
    max_files: int = Field(default=10000, ge=1, le=20000)
    max_file_mb: int = Field(default=256, ge=1, le=512)


REFERENCES = [
    {'id':'dicom-image-plane', 'title':'DICOM PS3.3 Image Plane Module',
     'url':'https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.7.6.2.html'},
    {'id':'dicom-roi-contour', 'title':'DICOM PS3.3 ROI Contour Module',
     'url':'https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.8.8.6.html'},
    {'id':'tg201', 'title':'AAPM TG-201 rapid communication: radiotherapy data transfer QA',
     'url':'https://pubmed.ncbi.nlm.nih.gov/21330992/'},
    {'id':'tg201-full', 'title':'AAPM TG-201: Quality Management of External Beam Therapy Data Transfer',
     'url':'https://www.aapm.org/pubs/reports/detail.asp?docid=213'},
    {'id':'tg263', 'title':'AAPM TG-263: standardized nomenclature',
     'url':'https://www.aapm.org/pubs/reports/RPT_263.pdf'},
]


def _hash_file(path):
    hasher=hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def _identity(ds):
    return (str(getattr(ds,'PatientID','')).strip(), str(getattr(ds,'IssuerOfPatientID','')).strip())


def _image_references(ds):
    """Only image-reference sequences: never confuse plan/structure refs with CT refs."""
    refs=[]
    for element in ds:
        if element.VR=='SQ':
            for item in element.value:
                if element.keyword=='ContourImageSequence':
                    refs.append(str(getattr(item,'ReferencedSOPInstanceUID','')))
                else:
                    refs.extend(_image_references(item))
    return refs


def _geometry(ds):
    orient=np.asarray(ds.ImageOrientationPatient,dtype=float)
    position=np.asarray(ds.ImagePositionPatient,dtype=float)
    spacing=np.asarray(ds.PixelSpacing,dtype=float)
    if orient.shape!=(6,) or position.shape!=(3,) or spacing.shape!=(2,):
        raise ValueError('Malformed geometry')
    if not all(np.isfinite(a).all() for a in (orient,position,spacing)) or (spacing<=0).any():
        raise ValueError('Nonfinite or nonpositive geometry')
    row,column=orient[:3],orient[3:]
    if not np.allclose([np.linalg.norm(row),np.linalg.norm(column)],1,atol=1e-4,rtol=0) or abs(np.dot(row,column))>1e-4:
        raise ValueError('Nonorthonormal orientation')
    if int(ds.Rows)<=0 or int(ds.Columns)<=0:
        raise ValueError('Invalid dimensions')
    return orient,position,spacing


class CaseOutputSeparationError(PermissionError, ValueError):
    """Raised when output path violates case separation or raw data immutability."""
    pass


def ensure_case_output_separation(root, output_dir):
    from src.readonly import assert_output_path
    source = Path(root).expanduser().resolve()
    target = Path(output_dir).expanduser().resolve()
    if source == target or source in target.parents:
        raise CaseOutputSeparationError('Session output must be outside the input case directory')
    try:
        assert_output_path(target)
    except ValueError as exc:
        raise CaseOutputSeparationError('Session output cannot target a protected raw directory') from exc


def verify_patient_case(request: CaseVerificationRequest):
    root=Path(request.root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('Case directory does not exist')
    findings, inventory, records, source_paths = [], [], {}, {}
    series=defaultdict(list); counts=Counter(); pixel_checks=0
    def finding(code,severity,scope,message,action,observed=None,reference='tg201'):
        findings.append(dict(code=code,severity=severity,scope=scope,message=message,
                             follow_up_action=action,observed=observed,reference_id=reference))
    paths=sorted(path for path in root.rglob('*') if path.is_file() or path.is_symlink())
    if len(paths)>request.max_files:
        raise ValueError('Case exceeds file budget; select a case-specific directory')
    expected_classes={'CT':str(CTImageStorage),'RTDOSE':str(RTDoseStorage),
                      'RTPLAN':str(RTPlanStorage),'RTSTRUCT':str(RTStructureSetStorage)}
    for index,path in enumerate(paths,1):
        label=f'F{index:05d}'
        if path.is_symlink() or root not in path.resolve().parents:
            finding('source_symlink','REVIEW',label,'Symlink source was not followed.',
                    'Provide an explicit authorized case directory containing the source files directly.')
            continue
        if path.stat().st_size>request.max_file_mb*1024*1024:
            finding('file_budget','REVIEW',label,'File exceeds the configured read budget; content not inspected.',
                    'Review the resource limit and process this object with an appropriate validated reader.')
            continue
        raw=path.read_bytes()
        sha=hashlib.sha256(raw).hexdigest();source_paths[label]=path
        entry=dict(file_id=label,sha256=sha,bytes=len(raw),kind='auxiliary' if path.name in ('.DS_Store','Thumbs.db','desktop.ini') else 'uninspected')
        inventory.append(entry)
        candidate=path.suffix.lower() in ('.dcm','.dicom','.ima') or raw[128:132]==b'DICM'
        if not candidate:
            continue
        try:
            with warnings.catch_warnings(record=True) as reader_warnings:
                warnings.simplefilter('always',UserWarning)
                ds=pydicom.dcmread(BytesIO(raw),stop_before_pixels=True)
            if reader_warnings:
                finding('dicom_reader_warning','REVIEW',label,'The DICOM reader reported metadata warnings; source values are withheld.',
                        'Inspect the object locally with the source TPS or validated DICOM tools.',len(reader_warnings))
            uid=str(ds.SOPInstanceUID);modality=str(ds.Modality)
            if not pydicom.uid.UID(uid).is_valid or not pydicom.uid.UID(str(getattr(ds,'SOPClassUID',''))).is_valid:
                raise ValueError('Missing SOP identity')
            entry['kind']=modality if modality in expected_classes else 'other-DICOM'
            counts[entry['kind']]+=1
            if uid in records:
                same=records[uid]['sha256']==sha
                finding('duplicate_sop','REVIEW' if same else 'BLOCK',label,
                        'Repeated SOP identity: identical copy.' if same else 'Repeated SOP identity has conflicting content.',
                        'Resolve duplicate exports in a separate curated dataset; retain original files unchanged.',
                        {'identical_content':same})
                continue
            for keyword,expected_uid in [('MediaStorageSOPInstanceUID',uid),('MediaStorageSOPClassUID',str(ds.SOPClassUID))]:
                declared=str(getattr(ds.file_meta,keyword,''))
                if declared and declared!=expected_uid:
                    finding('file_meta_identity','BLOCK',label,'DICOM file meta and dataset SOP identities disagree.',
                            'Verify the export with a validated reader; retain source bytes unchanged.')
            if modality in expected_classes and str(ds.SOPClassUID)!=expected_classes[modality]:
                finding('sop_class','BLOCK',label,'Modality and supported SOP class disagree.',
                        'Verify the export and use an appropriate reader; enhanced/multiframe image classes require a separate workflow.')
            if not _identity(ds)[0]:
                finding('missing_identity','BLOCK',label,'Patient identifier is absent; source association cannot be checked.',
                        'Obtain a properly associated or consistently pseudonymized source export.')
            if modality in ('CT','RTDOSE') and str(getattr(ds,'BurnedInAnnotation','')).upper()!='NO':
                finding('burned_in_annotation','REVIEW',label,'Absence of burned-in identifying content is not explicitly established.',
                        'Review image content and the de-identification procedure; this check does not certify privacy.')
            if modality not in expected_classes:
                finding('unsupported_modality','REVIEW',label,'DICOM object type is outside the supported conventional CT/RT workflow.',
                        'Use a validated modality-specific assessment. No unsupported object is treated as verified.')
            record=dict(file_id=label,ds=ds,sha256=sha,modality=modality,pixel_state='not_checked',synthetic=has_synthetic_teaching_marker(ds))
            records[uid]=record
            if modality in ('CT','RTDOSE'):
                try:
                    full=pydicom.dcmread(BytesIO(raw))
                    if not hasattr(full,'PixelData'):
                        raise ValueError('Missing pixel data')
                    if request.check_pixels:
                        pixels=full.pixel_array
                        frames=int(getattr(full,'NumberOfFrames',1))
                        expected=(frames,int(full.Rows),int(full.Columns)) if frames>1 else (int(full.Rows),int(full.Columns))
                        if pixels.shape!=expected or not np.isfinite(pixels).all():
                            raise ValueError('Invalid decoded pixel dimensions/values')
                        if modality=='RTDOSE':
                            dose=pixels.astype(float)*float(full.DoseGridScaling)
                            if not np.isfinite(dose).all() or (dose<0).any():
                                raise ValueError('Invalid absorbed dose')
                            record['dose_range_gy']=[float(dose.min()),float(dose.max())]
                        record['pixel_state']='decoded';pixel_checks+=1
                except (ValueError,TypeError,AttributeError,RuntimeError,NotImplementedError,KeyError,ImportError,OverflowError):
                    finding('pixel_integrity','BLOCK',label,'Pixel payload, shape, codec or finite-value check failed.',
                            'Inspect the source export, transfer syntax, declared dimensions and dose scaling in a validated viewer.')
                    record['pixel_state']='failed'
            if modality=='CT':
                if int(getattr(ds,'NumberOfFrames',1))!=1:
                    finding('multiframe_ct_unsupported','BLOCK',label,'Conventional single-frame CT workflow cannot verify a multiframe object.',
                            'Use the appropriate enhanced/multiframe image reader and a separately validated workflow.')
                series_uid=str(getattr(ds,'SeriesInstanceUID',''))
                if not series_uid:
                    finding('missing_series','BLOCK',label,'CT SeriesInstanceUID missing.',
                            'Obtain a complete CT series export with identifiers preserved consistently.')
                else:
                    series[series_uid].append(record)
        except (ValueError,AttributeError,TypeError,KeyError,EOFError,OSError,pydicom.errors.InvalidDicomError):
            finding('dicom_read','BLOCK',label,'Candidate DICOM could not be parsed or lacks required SOP metadata.',
                    'Inspect this local file and repeat the source export; do not fabricate missing identifiers.')
    if not records:
        finding('no_dicom','BLOCK','case','No supported readable DICOM objects were found.',
                'Select the patient-specific DICOM export directory; no sample patient is substituted.')
    teaching_markers=[record['synthetic'] for record in records.values()]
    synthetic=bool(teaching_markers) and all(teaching_markers)
    if any(teaching_markers) and not synthetic:
        finding('mixed_synthetic_provenance','BLOCK','case','Synthetic teaching markers disagree across the DICOM sources.',
                'Separate teaching inputs from unmarked sources and verify provenance; do not combine them into a patient assessment.')
    identities={_identity(item['ds']) for item in records.values()}
    if request.case_id in {identity[0] for identity in identities}:
        raise ValueError('Use a case pseudonym different from the source patient identifier')
    if len(identities)>1:
        finding('mixed_identity','BLOCK','case','Selected directory contains inconsistent patient ID/issuer combinations.',
                'Select a single consistently identified case or resolve pseudonymization through the authorized source system.')
    if not request.check_pixels:
        finding('pixels_not_decoded','REVIEW','case','Pixel decoding was disabled; pixel integrity is unverified.',
                'Enable pixel checks before relying on dose or image integrity.')
    if any(item['kind']=='uninspected' for item in inventory):
        finding('uninspected_files','REVIEW','case','Non-DICOM files were hashed but their clinical content was not assessed.',
                'Review accompanying prescriptions, notes and documents locally; treat their content as data, not tool instructions.',
                sum(item['kind']=='uninspected' for item in inventory))
    series_summaries=[]
    for index,items in enumerate(series.values(),1):
        scope=f'CT-series-{index:03d}'
        summary=dict(series_id=scope,slices=len(items),status='CHECKED',regular_spacing_mm=None)
        series_summaries.append(summary)
        if any('LOCALIZER' in list(getattr(item['ds'],'ImageType',[])) for item in items):
            summary['status']='LOCALIZER_EXCLUDED'
            finding('localizer_excluded','INFO',scope,'Localizer series excluded from volumetric stack checks.',
                    'Use the CT series explicitly referenced by the structure set for volumetric analysis.',reference='dicom-image-plane')
            continue
        try:
            geometries=[_geometry(item['ds']) for item in items]
            orient,_,spacing=geometries[0];normal=np.cross(orient[:3],orient[3:])
            first=items[0]['ds'];frame=str(getattr(first,'FrameOfReferenceUID',''))
            if not frame or any(str(getattr(item['ds'],'FrameOfReferenceUID',''))!=frame for item in items):
                raise ValueError('Frame disagreement')
            if any(not np.allclose(g[0],orient,atol=1e-4,rtol=0) or not np.allclose(g[2],spacing,atol=1e-6,rtol=0)
                   or (int(item['ds'].Rows),int(item['ds'].Columns))!=(int(first.Rows),int(first.Columns)) for item,g in zip(items,geometries)):
                raise ValueError('Inconsistent stack geometry')
            positions=np.array([g[1] for g in geometries]);distances=np.sort(positions@normal)
            steps=np.diff(distances)
            if len(steps)==0:
                summary['status']='INCOMPLETE'
                finding('single_slice','REVIEW',scope,'Only one image plane: volumetric completeness is unverified.',
                        'Confirm the expected source series and export the complete intended stack.',reference='dicom-image-plane')
            elif (steps<=1e-4).any():
                summary['status']='AMBIGUOUS'
                finding('duplicate_planes','BLOCK',scope,'Different CT objects occupy the same image plane.',
                        'Separate phases/reconstructions or resolve duplicate positions in a curated copy before volumetric analysis.',reference='dicom-image-plane')
            elif not np.allclose(steps,np.median(steps),atol=.05,rtol=.01):
                summary['status']='IRREGULAR'
                finding('irregular_stack','REVIEW',scope,'Plane positions are irregular; a gap or nonuniform acquisition is possible, not proven.',
                        'Compare against the source series inventory and referenced image list. Do not interpolate missing slices automatically.',
                        {'minimum_step_mm':float(steps.min()),'maximum_step_mm':float(steps.max())},'dicom-image-plane')
            else:
                summary['regular_spacing_mm']=float(np.median(steps))
            declared=[float(getattr(item['ds'],'SpacingBetweenSlices')) for item in items if hasattr(item['ds'],'SpacingBetweenSlices')]
            if declared and (not np.isfinite(declared).all() or any(value<=0 for value in declared) or
                    (len(steps)>0 and not np.allclose(steps,declared[0],atol=.05,rtol=.01)) or
                    not np.allclose(declared,declared[0],atol=.05,rtol=.01)):
                finding('declared_spacing','REVIEW',scope,'Position-derived spacing disagrees with declared spacing or its metadata is invalid.',
                        'Compare the source acquisition and image inventory; SliceThickness is not used as a substitute for slice-center spacing.',reference='dicom-image-plane')
            # Oblique stacks are valid. In-plane origin changes need explicit support.
            tangential=positions-np.outer(positions@normal,normal)
            if not np.allclose(tangential,tangential[0],atol=.05,rtol=0):
                finding('tilted_stack','REVIEW',scope,'Stack has in-plane origin changes; a simple rectangular grid must not be assumed.',
                        'Use a validated gantry-tilt/geometry-aware reader and document any derived resampling.',reference='dicom-image-plane')
        except (ValueError,AttributeError,TypeError):
            summary['status']='INVALID'
            finding('ct_geometry','BLOCK',scope,'CT geometry is absent, inconsistent, nonfinite or nonorthonormal.',
                    'Verify orientation, origin, spacing, dimensions and frame metadata against the source export.',reference='dicom-image-plane')
    if not series:
        finding('missing_ct','REVIEW','case','No conventional CT series was available for image association checks.',
                'Provide the source image series or document the explicitly supported non-CT workflow.')
    # Assess every structure set, even when dose/plan objects are absent.
    structure_naming={}
    for record in records.values():
        if record['modality']!='RTSTRUCT':continue
        scope=record['file_id'];struct=record['ds'];naming=[]
        structure_naming[str(struct.SOPInstanceUID)]=naming
        try:
            rois=list(getattr(struct,'StructureSetROISequence',[]))
            if not rois:raise ValueError('No ROI definitions')
            build_roi_index(rois)
            for roi in rois:
                verdict=check_structure_name(str(roi.ROIName))
                canonical=verdict['canonical_name']
                label=canonical or f'ROI_{int(roi.ROINumber)}'
                naming.append(dict(roi_number=int(roi.ROINumber),label=label,status=verdict['status']))
                if canonical is None or verdict['status'] not in ('official_primary',):
                    finding('roi_name_review','REVIEW',f'{scope}/ROI_{int(roi.ROINumber)}','Structure name requires scoped nomenclature/anatomical review.',
                            'Inspect the original label locally and confirm anatomy/laterality before supplying an explicit reviewed mapping.',reference='tg263')
            roi_numbers={int(roi.ROINumber) for roi in rois}
            contoured=set()
            for roi_contour in getattr(struct,'ROIContourSequence',[]):
                if getattr(roi_contour,'ContourSequence',[]):
                    contoured.add(int(roi_contour.ReferencedROINumber))
                if int(roi_contour.ReferencedROINumber) not in roi_numbers:
                    raise ValueError('Orphan ROI contour')
                for contour_index,contour in enumerate(getattr(roi_contour,'ContourSequence',[]),1):
                    contour_scope=f'{scope}/ROI_{int(roi_contour.ReferencedROINumber)}/Contour_{contour_index}'
                    if str(getattr(contour,'ContourGeometricType','')) not in ('CLOSED_PLANAR','CLOSEDPLANAR_XOR'):
                        finding('contour_type_scope','REVIEW',contour_scope,'One or more contours are not in the closed-planar DVH sampling scope.',
                                'Review the contour purpose and select a supported anatomical/dosimetric workflow.',reference='dicom-roi-contour')
                    points=np.asarray(getattr(contour,'ContourData',[]),dtype=float)
                    expected_points=int(getattr(contour,'NumberOfContourPoints',0))
                    if expected_points<1 or points.ndim!=1 or points.size!=3*expected_points or not np.isfinite(points).all():
                        finding('contour_integrity','BLOCK',contour_scope,'Contour point count or finite coordinates are invalid.',
                                'Review the structure export in the source TPS; do not invent or delete contour points.',reference='dicom-roi-contour')
                        continue
                    kind=str(getattr(contour,'ContourGeometricType',''))
                    if kind in ('CLOSED_PLANAR','CLOSEDPLANAR_XOR'):
                        if expected_points<3:
                            finding('contour_integrity','BLOCK',contour_scope,'Closed planar contours require at least three points.',
                                    'Review the source contour export; no area or volume is inferred.',
                                    {'number_of_points':expected_points,'minimum_for_closed_polygon':3},'dicom-roi-contour')
                            continue
                        xyz=points.reshape(-1,3)
                        centered=xyz-xyz.mean(axis=0)
                        _,_,directions=np.linalg.svd(centered,full_matrices=False)
                        residual=float(np.max(np.abs(np.sum(centered*directions[-1],axis=1))))
                        if not np.isfinite(residual):raise ValueError('Nonfinite contour plane residual')
                        if residual>0.01:
                            finding('contour_planarity','BLOCK',contour_scope,'A closed-planar contour is not coplanar within the numerical tolerance.',
                                    'Inspect the original contour in a validated viewer; do not flatten or repair source coordinates.',
                                    {'max_plane_residual_mm':residual,'tolerance_mm':0.01},'dicom-roi-contour')
                        elif float(np.ptp(xyz[:,2]))>0.01:
                            finding('contour_orientation_scope','REVIEW',contour_scope,'A planar contour is tilted relative to the supported axial DVH sampling planes.',
                                    'Use a validated orientation-aware contour/DVH workflow. A tilted contour can be valid DICOM; no axial projection is assumed.',
                                    reference='dicom-roi-contour')
            if roi_numbers-contoured:
                finding('roi_contours_absent','REVIEW',scope,'Some ROI definitions have no associated contour item.',
                        'Confirm which structures are intended for dose assessment and obtain their contours from the source system.',
                        len(roi_numbers-contoured),'dicom-roi-contour')
        except (ValueError,AttributeError,TypeError,KeyError,np.linalg.LinAlgError):
            finding('structure_integrity','BLOCK',scope,'Structure ROI definitions or contour associations are malformed or ambiguous.',
                    'Review the source structure export and ROI indices; no geometry or anatomical identity is inferred.')

    dose_cases=[]
    for record in records.values():
        if record['modality']!='RTDOSE':continue
        scope=record['file_id'];dose=record['ds']
        case=dict(dose_file=scope,plan_file=None,structure_file=None,linked_ct_series=[],course_linkage_verified=False,
                  dose_range_gy=record.get('dose_range_gy'),roi_naming=[])
        dose_cases.append(case)
        try:
            validate_axial_dose(dose)
        except (ValueError,AttributeError,TypeError):
            finding('dose_geometry','BLOCK',scope,'Dose units, scaling or geometry are invalid or unsupported by the axial dose tool.',
                    'Check the dose export. Oblique or nonuniform dose requires a separately validated workflow; no source repair is inferred.')
        try:
            plan_refs=list(getattr(dose,'ReferencedRTPlanSequence',[]))
            if len(plan_refs)!=1:raise ValueError('ambiguous plan')
            plan_record=records[str(plan_refs[0].ReferencedSOPInstanceUID)]
            if plan_record['modality']!='RTPLAN':raise ValueError('wrong modality')
            plan=plan_record['ds'];case['plan_file']=plan_record['file_id']
            struct_refs=list(getattr(plan,'ReferencedStructureSetSequence',[]))
            if len(struct_refs)!=1:raise ValueError('ambiguous structure')
            struct_record=records[str(struct_refs[0].ReferencedSOPInstanceUID)]
            if struct_record['modality']!='RTSTRUCT':raise ValueError('wrong modality')
            struct=struct_record['ds'];case['structure_file']=struct_record['file_id']
            if not _identity(dose)[0] or not (_identity(dose)==_identity(plan)==_identity(struct)):
                raise ValueError('identity mismatch')
            frame=str(getattr(dose,'FrameOfReferenceUID',''))
            rois=list(getattr(struct,'StructureSetROISequence',[]))
            if not frame or not rois or any(str(getattr(roi,'ReferencedFrameOfReferenceUID',''))!=frame for roi in rois):
                finding('frame_linkage','BLOCK',scope,'Dose and structure frames are absent or inconsistent.',
                        'Review the intended course and any approved registration in the source system; never overwrite frame UIDs to obtain a pass.')
            else:
                case['course_linkage_verified']=True
            plan_frame=str(getattr(plan,'FrameOfReferenceUID',''))
            if plan_frame and plan_frame!=frame:
                finding('plan_frame','BLOCK',scope,'Plan and dose frame identities disagree.',
                        'Verify the plan geometry and intended image/course association in the source system.')
            elif not plan_frame:
                finding('plan_frame_absent','REVIEW',scope,'Plan frame association is not explicit.',
                        'Review plan geometry and the applicable DICOM requirements; do not infer a patient-space association.')
            if any(str(getattr(item,'FrameOfReferenceUID',''))!=frame for item in getattr(struct,'ReferencedFrameOfReferenceSequence',[])):
                finding('structure_reference_frame','BLOCK',scope,'Structure source-reference frame and dose frame disagree.',
                        'Review the intended registered source images and course; retain the source identifiers unchanged.')
            case['roi_naming']=structure_naming.get(str(struct.SOPInstanceUID),[])
            refs=set(_image_references(struct))
            if not refs:
                finding('image_references_absent','REVIEW',scope,'No explicit source-image SOP references were found in the structure set.',
                        'Verify source CT association in the TPS; a matching frame alone does not prove acquisition identity.')
            missing=refs-set(records)
            if missing:
                finding('referenced_images_missing','BLOCK',scope,'Structure set references image objects absent from this case directory.',
                        'Export the complete referenced image series from the source system; retain original files unchanged.',len(missing))
            referenced_images=[records[uid] for uid in refs if uid in records]
            referenced_file_ids={image['file_id'] for image in referenced_images}
            if any(image['modality']!='CT' or _identity(image['ds'])!=_identity(struct)
                   or str(getattr(image['ds'],'FrameOfReferenceUID',''))!=frame for image in referenced_images):
                finding('image_association','BLOCK',scope,'Referenced images disagree in modality, patient/issuer or frame.',
                        'Confirm the exact image/structure/course association in the TPS before dose analysis.')
            for index,items in enumerate(series.values(),1):
                if any(item['file_id'] in referenced_file_ids for item in items):
                    case['linked_ct_series'].append(f'CT-series-{index:03d}')
        except (ValueError,AttributeError,TypeError,KeyError):
            finding('course_linkage','BLOCK',scope,'A unique dose→plan→structure association or unambiguous ROI index could not be established.',
                    'Export all referenced RT objects together and resolve identity, reference or ROI ambiguities in the authorized source system.')
    if not dose_cases:
        finding('missing_rt_course','REVIEW','case','No dose–plan–structure course was available for dosimetry intake.',
                'Provide the intended RTDOSE, RTPLAN and RTSTRUCT exports, or document that this is an image-only assessment.')
    # Completeness requires an external expected inventory, even for perfectly regular stacks.
    finding('completeness_scope','INFO','case','Uniform spacing and resolved references cannot prove that no unreferenced end slices or source objects were omitted.',
            'Compare with the authorized source-system inventory before consequential use. This tool does not provide independent clinical approval.')
    findings.sort(key=lambda item:({'BLOCK':0,'REVIEW':1,'INFO':2}[item['severity']],item['scope'],item['code']))
    status='BLOCKED' if any(item['severity']=='BLOCK' for item in findings) else 'FLAGGED_FOR_REVIEW' if any(item['severity']=='REVIEW' for item in findings) else 'READY_FOR_RESEARCH_ANALYSIS'
    for item in inventory:
        if _hash_file(source_paths[item['file_id']])!=item['sha256']:
            raise ValueError('Source changed during verification; no report committed')
    current_paths=sorted(path for path in root.rglob('*') if path.is_file() or path.is_symlink())
    if current_paths!=paths:
        raise ValueError('Case inventory changed during verification; no report committed')
    grouped={}
    for item in findings:
        key=(item['code'],item['severity'],item['message'],item['follow_up_action'])
        group=grouped.setdefault(key,dict(code=item['code'],severity=item['severity'],message=item['message'],
                                        follow_up_action=item['follow_up_action'],count=0,example_scopes=[],example_observations=[]))
        group['count']+=1
        if len(group['example_scopes'])<5:group['example_scopes'].append(item['scope'])
        if item['observed'] is not None and len(group['example_observations'])<5:
            group['example_observations'].append({'scope':item['scope'],'observed':item['observed']})
    result=dict(case_id=request.case_id,status=status,clinical_release=False,synthetic=synthetic,profile='case-intake-2',
                counts=dict(counts),files_hashed=len(inventory),pixel_objects_decoded=pixel_checks,
                check_pixels=request.check_pixels,ct_series=series_summaries,dose_cases=dose_cases,findings=findings,
                source_inventory=inventory,references=REFERENCES,findings_summary=list(grouped.values()),
                privacy={'source_files_modified':False,'source_paths_exported':False,'patient_identifiers_exported':False},
                software={'pydicom':pydicom.__version__,'numpy':np.__version__,'verifier_source_sha256':_hash_file(Path(__file__))},
                criteria={'orientation_atol':1e-4,'position_atol_mm':.05,'spacing_rtol':.01,'duplicate_plane_atol_mm':1e-4,
                          'contour_plane_atol_mm':.01,'contour_axial_z_span_atol_mm':.01},
                limitations=['Read-only research intake; no complete DICOM conformance, de-identification or treatment-plan certification.',
                             'No image registration, contour rasterization/topology assessment, clinical dose-constraint assessment or source correction is performed here.',
                             'Only conventional single-frame CT stacks and the existing axial RTDOSE scope are supported. Other workflows require review.'])
    result['verification_hash']=digest(result)
    result['generated_at_utc']=datetime.now(timezone.utc).isoformat()
    manager,session_id=current_session()
    ensure_case_output_separation(root,manager.base_dir)
    from src.reports import attach_report
    attach_report(result,'case_verification')
    append_record(Path(manager.get_session_dir(session_id))/'case-audit.jsonl',{'type':'case_verification',**result})
    return result
