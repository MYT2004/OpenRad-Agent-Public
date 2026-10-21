"""Narrow, read-only comparison with the pinned Eclipse phantom DVH export.

TPS exports are independent numerical comparators, not measured dose truth.
This parser supports only the explicit cumulative cGy/relative-volume format.
"""
import re
from pathlib import Path
import numpy as np
import pydicom
import pydicom.dicomio
if not hasattr(pydicom.dicomio, 'read_file'):
    pydicom.dicomio.read_file = pydicom.dcmread
if not hasattr(pydicom, 'read_file'):
    pydicom.read_file = pydicom.dcmread
from dicompylercore import dvhcalc
from openrad.tools.dataset import discover_dataset
from src.storage import session_scope
from src.tools import parse_and_evaluate_dvh


def dose_at_volume(dose,volume,target):
    indices=np.flatnonzero(volume>=target)
    if not len(indices) or indices[-1]>=len(dose)-1:
        raise ValueError('Reference curve does not bracket the requested volume')
    i=int(indices[-1])
    if volume[i]==target:return float(dose[i])
    return float(dose[i]+(dose[i+1]-dose[i])*(volume[i]-target)/(volume[i]-volume[i+1]))


def parse_eclipse_export(text,selected_names=None):
    if 'Type                 : Cumulative Dose Volume Histogram' not in text:
        raise ValueError('Only the explicit Eclipse cumulative DVH format is supported')
    plans=set(re.findall(r'^Plan:\s*(.+)$',text,re.M))
    rx=re.findall(r'^Prescribed dose \[cGy\]:\s*([0-9.]+)\s*$',text,re.M)
    patient=re.findall(r'^Patient ID\s*:\s*(.+)$',text,re.M)
    if len(plans)!=1 or len(rx)!=1 or len(patient)!=1 or float(rx[0])<=0:
        raise ValueError('Reference export identity, plan or prescription is ambiguous')
    result={'plan':next(iter(plans)).strip(),'patient_id':patient[0].strip(),'prescription_gy':float(rx[0])/100,'structures':{}}
    blocks=re.split(r'^Structure:\s*(.+)\s*$',text,flags=re.M)
    for name,block in zip(blocks[1::2],blocks[2::2]):
        if selected_names is not None and name.strip() not in selected_names:continue
        if 'Dose [cGy]' not in block or 'Ratio of Total Structure Volume [%]' not in block:
            raise ValueError('Reference curve units are not explicit')
        points=[]
        for line in block.splitlines():
            tokens=line.split()
            if len(tokens)!=3:continue
            try:points.append([float(token) for token in tokens])
            except ValueError:continue
        a=np.asarray(points,dtype=float)
        if a.ndim!=2 or a.shape[0]<2 or a.shape[1]!=3 or not np.isfinite(a).all():
            raise ValueError('Malformed reference DVH')
        dose=a[:,1]/100;volume=a[:,2]
        if dose[0]!=0 or (np.diff(dose)<=0).any() or (np.diff(volume)>0).any() or (volume<0).any() or (volume>100).any() or volume[0]!=100 or volume[-1]!=0:
            raise ValueError('Reference cumulative curve must run from 100% at zero to a zero-volume tail')
        if not np.allclose(a[:,0]*result['prescription_gy']/100,dose,atol=1e-5,rtol=0):
            raise ValueError('Reference relative and absolute dose columns disagree')
        vol=re.search(r'^Volume \[cm[^\]]*\]:\s*([0-9.]+)',block,re.M)
        mean=re.search(r'^Mean Dose \[%\]:\s*([0-9.]+)',block,re.M)
        if not vol or not mean or name.strip() in result['structures']:
            raise ValueError('Missing/ambiguous reference structure metrics')
        result['structures'][name.strip()]={'dose_gy':dose,'volume_percent':volume,
            'volume_cc':float(vol[1]),'mean_dose_Gy':float(mean[1])*result['prescription_gy']/100,
            'D95_Gy':dose_at_volume(dose,volume,95),'D50_Gy':dose_at_volume(dose,volume,50),'D2_Gy':dose_at_volume(dose,volume,2)}
    if not result['structures']:raise ValueError('No reference structures')
    if selected_names is not None and set(result['structures'])!=set(selected_names):
        raise ValueError('Selected reference structure is absent or ambiguous')
    return result


def compare_prostate(root,manager):
    case=root/'eclipse-8.1.20-phantom-prostate'
    source=case/'Rando, PROSTATE (TEST PHYS PROSTATE) DVH'
    names=['Bladder','PTV','Rectum']  # exact, already recognized source labels; no anatomical aliases
    reference=parse_eclipse_export(source.read_text(encoding='cp1252'),names)
    scan=discover_dataset(case/'Original')
    if len(scan['dose_cases'])!=1 or scan['dose_cases'][0]['blockers']:
        raise ValueError('Independent comparison requires one unambiguous dose course')
    pair=scan['dose_cases'][0]
    plan=pydicom.dcmread(pair['plan_path'],stop_before_pixels=True)
    rx=[float(r.TargetPrescriptionDose) for r in getattr(plan,'DoseReferenceSequence',[]) if hasattr(r,'TargetPrescriptionDose')]
    if str(plan.RTPlanLabel)!=reference['plan'] or str(plan.PatientID)!=reference['patient_id'] or rx!=[reference['prescription_gy']]:
        raise ValueError('TPS curve identity/plan/prescription does not match the DICOM plan')
    with session_scope(manager):
        evaluated=parse_and_evaluate_dvh(pair['dose_path'],pair['struct_path'],names,rtplan_path=pair['plan_path'])
    rows=[]
    for name in names:
        actual=evaluated['structures'][name];tps=reference['structures'][name]
        if not actual.get('found'):raise ValueError('Selected benchmark structure could not be evaluated')
        independent=dvhcalc.get_dvh(pair['struct_path'],pair['dose_path'],actual['roi_number'])
        oracle={'volume_cc':float(independent.volume),'mean_dose_Gy':float(independent.mean),
                'D95_Gy':float(independent.D95.value),'D50_Gy':float(independent.D50.value),'D2_Gy':float(independent.D2.value)}
        keys=list(oracle)
        curve=actual['dvh_curve']
        interpolated=np.interp(tps['dose_gy'],curve['dose_bins_Gy'],curve['volume_percent'],left=100,right=0)
        delta=interpolated-tps['volume_percent']
        rows.append({'structure':name,'openrad':{key:actual[key] for key in keys},
                     'tps_export':{key:tps[key] for key in keys},'dicompyler_core_default':oracle,
                     'openrad_minus_tps':{key:actual[key]-tps[key] for key in keys},
                     'openrad_minus_dicompyler':{key:actual[key]-oracle[key] for key in keys},
                     'curve_difference_percentage_points':{'max_absolute':float(np.max(np.abs(delta))),
                         'mean_absolute_over_export_dose_bins':float(np.mean(np.abs(delta)))}})
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    figure=Figure(figsize=(9,5));FigureCanvasAgg(figure);ax=figure.subplots()
    for row in rows:
        name=row['structure'];curve=evaluated['structures'][name]['dvh_curve'];tps=reference['structures'][name]
        line,=ax.plot(curve['dose_bins_Gy'],curve['volume_percent'],label=f'{name}: OpenRad')
        ax.plot(tps['dose_gy'],tps['volume_percent'],linestyle='--',color=line.get_color(),label=f'{name}: TPS export')
    ax.set(xlabel='Dose (Gy)',ylabel='Volume (%)',ylim=(0,105),title='External Eclipse phantom — numerical comparison only')
    ax.legend();ax.grid(alpha=.2);figure.tight_layout()
    figure.savefig(Path(manager.base_dir).parent/'dvh-comparison.png',dpi=150)
    return {'dataset':case.name,'clinical_release':False,'source_identity_plan_rx_match':True,'structures':rows,
            'plot':'dvh-comparison.png',
            'openrad_report':str(Path('sessions')/evaluated['session_id']/'artifacts'/Path(evaluated['artifacts'][-1]).name),
            'limitations':['TPS export is a numerical comparator, not independently measured dose truth.',
                           'TPS summary means are rounded relative-dose values; inverse cumulative D metrics use linear interpolation.',
                           'OpenRad uses axial voxel-center sampling, inferred uniform contour slabs and linear z-dose interpolation; curve threshold spacing is exported explicitly (normally 0.01 Gy).',
                           'dicompyler-core uses its default rasterization and dose-bin settings. Differences are observations, not validated clinical error margins.',
                           'No SlicerRT runtime execution or population-level model qualification was performed.']}


def probe_keyhole_topology(root):
    from shapely.geometry import Polygon
    from openrad.tools.dose_geometry import validate_axial_dose
    from openrad.tools.contours import sample_contour_doses
    case=root/'aria-phantom-contours-keyhole'
    dose=pydicom.dcmread(case/'RD.PYTIM05_.dcm');struct=pydicom.dcmread(case/'RS.PYTIM05_.dcm')
    validate_axial_dose(dose)
    unsupported=[];first=None
    for roi in struct.ROIContourSequence:
        for contour in getattr(roi,'ContourSequence',[]):
            if str(contour.ContourGeometricType) not in ('CLOSED_PLANAR','CLOSEDPLANAR_XOR'):continue
            points=np.asarray(contour.ContourData,dtype=float).reshape(-1,3)
            if np.ptp(points[:,2])>.01:continue
            if not Polygon(points[:,:2]).is_valid:
                unsupported.append(int(roi.ReferencedROINumber));first=first if first is not None else roi
    if first is None:
        first=next((roi for roi in struct.ROIContourSequence if len(getattr(roi,'ContourSequence',[]))>=2),None)
    result={'unsupported_polygon_rois':sorted(set(unsupported)),'sampler_rejected':False,'probe_executed':False,
            'scope':'Numeric topology probe only; no TG-263 alias or anatomical identity inferred. A keyhole encoding can be valid DICOM but outside this sampler.'}
    if first is not None:
        grid=dose.pixel_array.astype(float)*float(dose.DoseGridScaling)
        z=float(dose.ImagePositionPatient[2])+np.asarray(dose.GridFrameOffsetVector,dtype=float)
        try:
            sample_contour_doses(first,grid,z,float(dose.ImagePositionPatient[0]),float(dose.ImagePositionPatient[1]),
                                float(dose.PixelSpacing[1]),float(dose.PixelSpacing[0]))
            result.update(probe_executed=True,reason='Selected numeric contour probe was sampled; no anatomy or full topology correctness is established.')
        except ValueError as exc:
            result.update(probe_executed=True,sampler_rejected=True,reason=str(exc))
    return result
