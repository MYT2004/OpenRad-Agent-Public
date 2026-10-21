"""Deterministic research triage. Never authorizes clinical use or loads model code."""
from enum import Enum
from typing import Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class DecisionStatus(str, Enum):
    APPROVED = 'APPROVED'
    REJECTED = 'REJECTED'
    FLAGGED_FOR_REVIEW = 'FLAGGED_FOR_REVIEW'


class Grid(Contract):
    shape: Tuple[int, int, int]
    spacing_mm: Tuple[float, float, float]
    origin_mm: Tuple[float, float, float]
    # Row-major direction cosines; array axes are z,y,x, in a common frame.
    direction: Tuple[float, ...] = (1., 0., 0., 0., 1., 0., 0., 0., 1.)
    frame_id: str = Field(min_length=1)
    dose_units: Literal['Gy'] = 'Gy'


class Policy(Contract):
    version: Literal['osi-research-1'] = 'osi-research-1'
    seed: int = Field(default=42, ge=0, le=2147483647)
    max_uncertainty_gy: float = Field(default=2., gt=0)
    gradient_gy_per_mm: float = Field(default=1., gt=0)
    critical_margin_mm: float = Field(default=3., ge=0)
    min_confidence: float = Field(default=.95, ge=0, le=1)
    max_ood_score: float = Field(default=.1, ge=0, le=1)
    mass_density_limit_g_cm3: float = Field(default=3., gt=0)
    max_fluence_per_mm2: Optional[float] = Field(default=None, gt=0)
    max_voxels: int = Field(default=1000000, gt=0, le=1000000)


class EvaluationRequest(Contract):
    # Pseudonyms only; never put patient names or identifiers in these fields.
    model_name: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    dataset_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    model_kind: Literal['dose_predictor', 'monte_carlo', 'auto_segmentation'] = 'dose_predictor'
    model_weights_path: str
    input_paths: List[str] = Field(min_length=1)
    reference_path: str
    prediction_path: str
    image_grid: Grid
    reference_grid: Grid
    prediction_grid: Grid
    prescription_gy: float = Field(gt=0)
    target_mask_path: str
    oar_mask_paths: Dict[str, str] = Field(min_length=1)
    oar_limits_gy: Dict[str, float] = Field(min_length=1)
    uncertainty_std_path: Optional[str] = None
    mass_density_path: Optional[str] = None
    energy_mev: Optional[float] = Field(default=None, strict=True)
    fluence_per_mm2: Optional[float] = None
    probabilities: Dict[str, float] = Field(default_factory=dict)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    ood_score: Optional[float] = Field(default=None, ge=0, le=1)
    ood_flags: List[Literal['metal_artifact', 'post_surgical', 'pediatric', 'unseen_geometry']] = Field(default_factory=list)
    # Hash evidence, rather than presenting caller assertions as independent validation.
    qualification_evidence_path: Optional[str] = None
    uncertainty_calibration_path: Optional[str] = None
    ood_calibration_path: Optional[str] = None
    inference_seed: Optional[int] = Field(default=None, ge=0, le=2147483647)
    depth_dose_path: Optional[str] = None  # two columns: depth mm, dose Gy
    homogeneous_photon_depth_dose: bool = False
    buildup_end_mm: Optional[float] = None
    depth_dose_tolerance_gy: float = Field(default=0., ge=0)
    policy: Policy = Field(default_factory=Policy)


class Rule(Contract):
    name: str
    outcome: Literal['PASS', 'REVIEW', 'REJECT']
    observed: object
    criterion: str
    hard: bool = False


class ModelEvaluationResult(Contract):
    model_name: str
    dataset_id: str
    status: DecisionStatus
    hard_checks_passed: bool
    gamma_pass_rate_3mm3pct: Optional[float] = None
    oar_tolerance_violations: List[str] = Field(default_factory=list)
    max_uncertainty_gy: Optional[float] = None
    rejection_reasons: List[str] = Field(default_factory=list)
    reviewer_notes: Optional[str] = None
    clinical_release: Literal[False] = False
    scope: str = 'One supplied case; APPROVED means research candidate only.'
    metrics: dict = Field(default_factory=dict)
    rules: List[Rule] = Field(default_factory=list)
    provenance: dict = Field(default_factory=dict)
    policy: Policy
    decision_hash: str = ''
    artifacts: List[str] = Field(default_factory=list)
    session_id: str = ''
    human_report: dict = Field(default_factory=dict)


def threshold_rule(name, value, pass_at, fail_at, higher=True):
    """Inclusive pass/fail boundaries, with MAE handled separately below."""
    outcome = ('PASS' if value >= pass_at else 'REJECT' if value < fail_at else 'REVIEW') if higher else (
        'PASS' if value < pass_at else 'REJECT' if value > fail_at else 'REVIEW')
    return Rule(name=name, outcome=outcome, observed=value,
                criterion=f'pass {">=" if higher else "<"} {pass_at}; reject {"<" if higher else ">"} {fail_at}; otherwise review')


def decide(rules):
    return (DecisionStatus.REJECTED if any(r.outcome == 'REJECT' for r in rules) else
            DecisionStatus.FLAGGED_FOR_REVIEW if any(r.outcome == 'REVIEW' for r in rules) else DecisionStatus.APPROVED)
