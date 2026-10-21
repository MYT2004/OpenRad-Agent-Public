"""In-memory numerical preflight, not a clinical release or model qualification.

Use src.evaluation for file provenance, the complete evidence contract and audits.
"""
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional, Sequence, Tuple
import numpy as np
import pydicom
from pydantic import BaseModel, ConfigDict, Field
from scipy.ndimage import distance_transform_edt
from openrad.tools.gamma_tool import evaluate_gamma_index
from openrad.validation.physics_rules import PhysicsValidationEngine
from src.decision import threshold_rule


class DecisionStatus(str, Enum):
    APPROVED = 'APPROVED'
    REJECTED = 'REJECTED'
    FLAGGED_FOR_REVIEW = 'FLAGGED_FOR_REVIEW'


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    model_id: str
    dataset_id: str
    timestamp: str
    status: DecisionStatus
    hard_physics_passed: bool
    gamma_3mm3pct_pass_rate: Optional[float] = None
    gamma_2mm2pct_pass_rate: Optional[float] = None
    oar_violations: List[str] = Field(default_factory=list)
    rejection_reasons: List[str] = Field(default_factory=list)
    audit_hash_sha256: str
    metrics: Dict[str, Any] = Field(default_factory=dict)
    clinical_summary: str = ''
    follow_up_actions: List[str] = Field(default_factory=list)
    clinical_release: bool = False

    def to_markdown(self):
        from src.reports import markdown, number
        report = dict(title='Dose-model numerical preflight', summary=self.clinical_summary,
            metrics=[{'Measure':key.replace('_',' '), 'Result':str(value), 'Interpretation':'Computed numerical evidence; see review triggers.'}
                     for key,value in self.metrics.items()],
            follow_up_actions=self.follow_up_actions,
            limitations=['Research only; no clinical release. Geometry registration and model qualification are not established.',
                         'Missing measurements are not passes. SHA-256 is an integrity digest, not a digital signature or proof of registry entry.',
                         'Use the full evaluation manifest workflow for model/input/output provenance and signed reviewer dispositions.'])
        for title, value in [('Custom gamma 3%/3 mm',self.gamma_3mm3pct_pass_rate),('Custom gamma 2%/2 mm',self.gamma_2mm2pct_pass_rate)]:
            report['metrics'].append({'Measure':title,'Result':number(value,'%'),'Interpretation':'Discrete global gamma; not the TG-218 reference criterion.'})
        report['metrics'].append({'Measure':'Audit Integrity Hash (SHA-256)','Result':self.audit_hash_sha256,'Interpretation':'Digest of this assessment and supplied array hashes; unsigned.'})
        text = markdown(report)
        text += '\n## Failures and review triggers\n\n' + '\n'.join(f'- {reason}' for reason in self.rejection_reasons) + '\n'
        return text


# Retained for API compatibility only. These values are never applied automatically.
DEFAULT_SERIAL_OAR_LIMITS_GY = {'spinalcord':45.,'brainstem':54.}


def scrub_patient_hipaa_metadata(ds: pydicom.Dataset):
    """Legacy name: read-only screening of selected tags, not de-identification or HIPAA certification."""
    tags = ['PatientName','PatientID','PatientBirthDate','PatientSex','PatientAge','PatientAddress',
            'InstitutionName','InstitutionalDepartmentName','ReferringPhysicianName','PerformingPhysicianName','OperatorsName']
    found = [tag for tag in tags if str(getattr(ds,tag,'')).strip().upper() not in ('','ANON','ANONYMOUS','N/A')]
    return dict(hipaa_compliant=not found, unscrubbed_tags=found,
                limitation='Selected-tag screening only; no HIPAA or DICOM confidentiality-profile certification.')


def compute_fast_gamma(evaluated_dose, reference_dose, spacing_mm, dose_pct, dist_mm, threshold_pct=10.):
    return float(evaluate_gamma_index(reference_dose,evaluated_dose,dose_pct,dist_mm,threshold_pct,
                                     list(spacing_mm),list(spacing_mm))['passing_rate'])


def verify_model_output(evaluated_dose: np.ndarray, reference_dose: Optional[np.ndarray]=None,
    spacing_mm: Tuple[float,float,float]=(3.,1.,1.), model_id='dose_predictor', dataset_id='assessment',
    energy_mev: Optional[float]=None, image_orientation: Optional[Sequence[float]]=None,
    dicom_dataset: Optional[pydicom.Dataset]=None, prescription_dose_gy: Optional[float]=None,
    structure_masks: Optional[Dict[str,np.ndarray]]=None, oar_tolerance_limits_gy: Optional[Dict[str,float]]=None,
    uncertainty_grid: Optional[np.ndarray]=None):
    """Assess explicit in-memory arrays. Incomplete provenance always requires review.

    OAR limits must be explicit and exactly keyed to supplied masks. No clinical
    limit, registration, missing gamma score or model qualification is invented.
    """
    hard, rejects, reviews, violations, metrics, hashes = True, [], [], [], {}, {}
    def invalid(message):
        nonlocal hard
        hard=False; rejects.append(message)
    def dose_array(value, name):
        try:
            array=np.asarray(value,dtype=float)
        except (ValueError,TypeError):
            invalid(f'{name} must be a numeric 3D dose array.');return None
        if array.ndim!=3 or not array.size:
            invalid(f'{name} must be a nonempty 3D array.');return None
        if not np.isfinite(array).all():
            invalid(f'Non-finite values detected in {name}.');return None
        hashes[name]=hashlib.sha256(np.ascontiguousarray(array,dtype='<f8').tobytes()).hexdigest()
        if (array<0).any():
            invalid(f'Absorbed dose non-negativity violated in {name}; minimum {float(array.min()):.8g} Gy. Do not clip values to obtain a pass.')
        return array
    evaluated=dose_array(evaluated_dose,'evaluated_dose')
    reference=dose_array(reference_dose,'reference_dose') if reference_dose is not None else None
    if evaluated is not None:
        metrics.update(min_dose_gy=float(evaluated.min()),max_dose_gy=float(evaluated.max()))
    if reference is None:
        reviews.append('Independent reference dose missing or invalid; gamma and MAE are not evaluated.')
    elif evaluated is not None and reference.shape!=evaluated.shape:
        invalid('Reference and evaluated matrix shapes differ; explicit validated registration/resampling is required.')
    if len(spacing_mm)!=3 or not np.isfinite(spacing_mm).all() or any(v<=0 for v in spacing_mm):
        invalid('Voxel spacing must contain three finite positive mm values.')
    else:
        metrics['grid_spacing_mm']=list(spacing_mm)
    if energy_mev is not None and not PhysicsValidationEngine.validate_beam_energy(energy_mev,raise_on_fail=False).passed:
        invalid('Beam energy outside supported application range 0.01–250 MeV.')
    if image_orientation is not None:
        orientation=np.asarray(image_orientation,dtype=float)
        if orientation.shape!=(6,) or not np.isfinite(orientation).all():
            invalid('Orientation must contain six finite direction cosines.')
        elif not (abs(np.dot(orientation[:3],orientation[3:]))<=1e-4 and np.allclose([np.linalg.norm(orientation[:3]),np.linalg.norm(orientation[3:])],1,atol=1e-4,rtol=0)):
            invalid('Coordinate frame orthogonality or unit-vector condition failed.')
    else:
        reviews.append('Image orientation not provided; orientation was not verified.')
    if dicom_dataset is not None and not scrub_patient_hipaa_metadata(dicom_dataset)['hipaa_compliant']:
        invalid('Patient identifiers detected by limited metadata screening; HIPAA compliance is not certified. Create a separate scrubbed analysis copy.')
    masks={}
    limits=oar_tolerance_limits_gy or {}
    if any(not np.isfinite(v) or v<=0 for v in limits.values()):
        invalid('OAR dose limits must be finite positive Gy values.')
    for name, value in (structure_masks or {}).items():
        mask=np.asarray(value)
        if evaluated is None or mask.shape!=evaluated.shape or mask.dtype.kind not in 'bufi' or not np.isfinite(mask).all() or not np.isin(mask,[0,1]).all() or not mask.any():
            invalid(f'Mask for {name} must be finite, binary, nonempty and match the dose grid.');continue
        masks[name]=mask.astype(bool)
        hashes['mask_'+name]=hashlib.sha256(np.ascontiguousarray(mask,dtype='u1').tobytes()).hexdigest()
    if uncertainty_grid is not None:
        uncertainty=np.asarray(uncertainty_grid,dtype=float)
        if evaluated is None or uncertainty.shape!=evaluated.shape or not np.isfinite(uncertainty).all() or (uncertainty<0).any():
            invalid('Uncertainty SD must be finite, nonnegative Gy and match the dose grid.')
        else:
            hashes['uncertainty_std']=hashlib.sha256(np.ascontiguousarray(uncertainty,dtype='<f8').tobytes()).hexdigest()
            metrics['max_uncertainty_gy']=float(uncertainty.max())
            if uncertainty.max()>=2:
                reviews.append('Maximum uncertainty SD reaches the 2 Gy research review threshold.')
    else:
        uncertainty=None
        reviews.append('Uncertainty SD map not provided.')
    if prescription_dose_gy is None:
        reviews.append('Prescription not provided; target coverage and MAE / prescription are not evaluated.')
    elif not np.isfinite(prescription_dose_gy) or prescription_dose_gy<=0:
        invalid('Prescription must be finite and >0 Gy.')
    if set(limits)-set(masks):
        reviews.append('One or more specified OAR limits have no matching valid mask.')
    if hard:
        if reference is not None:
            if np.prod(evaluated.shape)>1000000:
                reviews.append('Grid exceeds the 1,000,000 voxel research gamma budget; gamma not evaluated.')
            else:
                for key,percent,distance,p,f in [('gamma_3mm3pct',3,3,95,90),('gamma_2mm2pct',2,2,90,85),('gamma_tg218_3pct2mm',3,2,95,90)]:
                    try:
                        value=compute_fast_gamma(evaluated,reference,spacing_mm,percent,distance)
                        metrics[key]=value
                        entry=threshold_rule(key,value,p,f)
                        message=f'{key}: {value:.3f}%; candidate ≥{p:.1f}%, reject < {f:.1f}%; otherwise review.'
                        if entry.outcome=='REJECT':rejects.append(message)
                        elif entry.outcome=='REVIEW':reviews.append(message)
                    except ValueError:
                        invalid('Gamma computation failed; review reference normalization and grid validity.')
            if prescription_dose_gy is not None:
                value=float(np.mean(np.abs(evaluated-reference))/prescription_dose_gy*100)
                metrics['mae_percent_rx']=value
                entry=threshold_rule('mae',value,1.5,3,False)
                if entry.outcome=='REJECT':rejects.append('MAE exceeds 3% of prescription.')
                elif entry.outcome=='REVIEW':reviews.append('MAE is within the 1.5–3% prescription review band.')
        for name,mask in masks.items():
            dmax=float(evaluated[mask].max());metrics[name+'_dmax_gy']=dmax
            if name.startswith('PTV'):
                if prescription_dose_gy is not None:
                    value=float(np.percentile(evaluated[mask],5)/prescription_dose_gy*100)
                    metrics[name+'_d95_percent_rx']=value
                    entry=threshold_rule('coverage',value,95,93)
                    if entry.outcome=='REJECT':rejects.append(f'{name} D95 is <93% of prescription.')
                    elif entry.outcome=='REVIEW':reviews.append(f'{name} D95 is ≥93% and <95% of prescription.')
            elif name not in limits:
                reviews.append(f'{name}: no explicit OAR tolerance supplied; not assessed against a clinical limit.')
            elif dmax>limits[name]:
                message=f'Serial OAR limit breach: {name} Dmax {dmax:.2f} Gy exceeds supplied {limits[name]:.2f} Gy limit.'
                violations.append(message);rejects.append(message)
            elif dmax>=.98*limits[name]:
                reviews.append(f'{name}: Dmax within the 98–100% limit review band.')
        if uncertainty is not None and masks:
            grad_sq=np.zeros(evaluated.shape)
            for axis,step in enumerate(spacing_mm):
                if evaluated.shape[axis]>1:grad_sq+=np.gradient(evaluated,step,axis=axis)**2
            oars=[mask for name,mask in masks.items() if not name.startswith('PTV')]
            if oars:
                proximity=distance_transform_edt(~np.logical_or.reduce(oars),sampling=spacing_mm)<=3
                count=int(((uncertainty>=2)&(np.sqrt(grad_sq)>=1)&proximity).sum())
                metrics['critical_uncertainty_voxels']=count
                if count:reviews.append('High uncertainty overlaps a steep gradient within 3 mm of an OAR.')
    # The convenience preflight cannot establish the full typed qualification contract.
    reviews.append('In-memory preflight lacks verified registration, model/source provenance, OOD and calibration records. Complete the evaluation manifest and independent review.')
    status=DecisionStatus.REJECTED if rejects or not hard else DecisionStatus.FLAGGED_FOR_REVIEW
    summary,actions=generate_clinical_summary_and_actions(status,hard,rejects,reviews,violations,
        metrics.get('gamma_3mm3pct'),metrics.get('gamma_2mm2pct'))
    metrics['input_array_sha256']=hashes
    payload=dict(model_id=model_id,dataset_id=dataset_id,status=status.value,hard_physics_passed=hard,
                 metrics=metrics,reasons=rejects+reviews,explicit_oar_limits_gy={k:v for k,v in limits.items() if np.isfinite(v)})
    audit=hashlib.sha256(json.dumps(payload,sort_keys=True,allow_nan=False).encode()).hexdigest()
    return EvaluationReport(model_id=model_id,dataset_id=dataset_id,timestamp=datetime.now(timezone.utc).isoformat(),status=status,
        hard_physics_passed=hard,gamma_3mm3pct_pass_rate=metrics.get('gamma_3mm3pct'),gamma_2mm2pct_pass_rate=metrics.get('gamma_2mm2pct'),
        oar_violations=violations,rejection_reasons=rejects+reviews,audit_hash_sha256=audit,metrics=metrics,
        clinical_summary=summary,follow_up_actions=actions)


def generate_clinical_summary_and_actions(status,hard_physics_passed,rejection_reasons,review_reasons,oar_violations,gamma_3mm3pct,gamma_2mm2pct):
    summary=('Numerical assessment rejected: '+(rejection_reasons[0] if rejection_reasons else 'Input integrity failure.')) if status==DecisionStatus.REJECTED else 'Numerical preflight requires review. Passed numerical checks do not establish a clinically acceptable plan or a qualified computational model.'
    actions=['Review every failure and missing-evidence item; retain raw inputs unchanged and correct only separately tracked derived outputs.',
             'Verify reference provenance, grid registration, units and dose calibration before interpreting dosimetric differences.',
             'Complete the full evaluation manifest with uncertainty/OOD calibration and model/source hashes; obtain qualified review.']
    if oar_violations:actions.append('[TPS Optimization] Review the supplied endpoint/fractionation-specific OAR limit, contour and PRV with the treating team before considering plan changes.')
    return summary,actions
