"""Verification and test coverage for the High-Consequence Medical Physics Verification Engine.

Tests strict AAPM QA criteria (TG-218, TG-53), hard deterministic physics boundaries,
serial OAR tolerance limits, HIPAA compliance, and cryptographic audit hashing.
"""

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, RTDoseStorage, generate_uid
from pathlib import Path
import pytest

from src.validation import (
    DecisionStatus,
    EvaluationReport,
    verify_model_output,
    scrub_patient_hipaa_metadata,
)


def create_synthetic_dicom_dose(
    shape=(5, 10, 10),
    spacing=(3.0, 1.0, 1.0),
    base_dose=40.0,
    patient_name="ANON",
    patient_id="ANON",
    orientation=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
) -> FileDataset:
    """Creates a minimal synthetic DICOM RTDOSE FileDataset."""
    sop_uid = generate_uid()
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = RTDoseStorage
    meta.MediaStorageSOPInstanceUID = sop_uid

    ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = RTDoseStorage
    ds.SOPInstanceUID = sop_uid
    ds.Modality = "RTDOSE"
    ds.DoseUnits = "GY"
    ds.DoseType = "PHYSICAL"
    ds.DoseGridScaling = 0.01

    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.NumberOfFrames = shape[0]
    ds.Rows = shape[1]
    ds.Columns = shape[2]
    ds.PixelSpacing = [spacing[1], spacing[2]]
    ds.GridFrameOffsetVector = list(np.arange(shape[0]) * spacing[0])
    ds.ImagePositionPatient = [0.0, 0.0, 0.0]
    ds.ImageOrientationPatient = list(orientation)

    pixel_data = (np.full(shape, base_dose, dtype=float) / ds.DoseGridScaling).astype("<u2")
    ds.PixelData = pixel_data.tobytes()
    return ds


def test_valid_numerical_grid_still_requires_qualification():
    """A matching numerical grid cannot establish registration or model qualification."""
    shape = (5, 15, 15)
    ref_dose = np.full(shape, 50.0, dtype=float)
    eval_dose = np.full(shape, 50.0, dtype=float)

    # Masks for PTV and OARs
    ptv_mask = np.zeros(shape, dtype=bool)
    ptv_mask[:, 3:12, 3:12] = True

    cord_mask = np.zeros(shape, dtype=bool)
    cord_mask[:, 0:2, 0:2] = True
    eval_dose[cord_mask] = 25.0  # Well below 45 Gy tolerance
    ref_dose[cord_mask] = 25.0

    report = verify_model_output(
        evaluated_dose=eval_dose,
        reference_dose=ref_dose,
        spacing_mm=(3.0, 1.0, 1.0),
        model_id="deep_dose_v1",
        dataset_id="test_cohort",
        energy_mev=6.0,
        image_orientation=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        prescription_dose_gy=50.0,
        structure_masks={"PTV_High": ptv_mask, "SpinalCord": cord_mask},
    )

    assert isinstance(report, EvaluationReport)
    assert report.status == DecisionStatus.FLAGGED_FOR_REVIEW
    assert report.hard_physics_passed is True
    assert report.gamma_3mm3pct_pass_rate >= 95.0
    assert report.gamma_2mm2pct_pass_rate >= 90.0
    assert len(report.oar_violations) == 0
    assert any('provenance' in reason for reason in report.rejection_reasons)
    assert len(report.audit_hash_sha256) == 64


def test_negative_dose_voxels_rejected():
    """Test case 2: Injected negative dose voxels -> assert REJECTED."""
    shape = (5, 10, 10)
    eval_dose = np.full(shape, 40.0, dtype=float)
    eval_dose[2, 5, 5] = -0.5  # Erroneous CT offset or unphysical subtraction

    report = verify_model_output(
        evaluated_dose=eval_dose,
        reference_dose=np.full(shape, 40.0, dtype=float),
        spacing_mm=(3.0, 1.0, 1.0),
        model_id="corrupt_model",
        dataset_id="test_cohort",
    )

    assert report.status == DecisionStatus.REJECTED
    assert report.hard_physics_passed is False
    assert any("non-negativity" in r.lower() for r in report.rejection_reasons)


def test_gamma_failure_rejected():
    """Test case 3: Failing 3%/3 mm gamma (< 90%) -> assert REJECTED."""
    shape = (5, 20, 20)
    ref_dose = np.full(shape, 60.0, dtype=float)
    # Severely miscalculated dose grid (e.g. 30% cold spot across entire volume)
    eval_dose = np.full(shape, 40.0, dtype=float)

    report = verify_model_output(
        evaluated_dose=eval_dose,
        reference_dose=ref_dose,
        spacing_mm=(3.0, 1.0, 1.0),
        model_id="deviating_model",
        dataset_id="test_cohort",
    )

    assert report.status == DecisionStatus.REJECTED
    assert report.gamma_3mm3pct_pass_rate < 90.0
    assert any("gamma" in r.lower() and "90.0%" in r for r in report.rejection_reasons)


def test_spinal_cord_tolerance_breach_rejected():
    """Test case 4: Exceeding spinal cord maximum dose -> assert REJECTED with OAR violation logged."""
    shape = (5, 15, 15)
    eval_dose = np.full(shape, 40.0, dtype=float)
    ref_dose = np.full(shape, 40.0, dtype=float)

    cord_mask = np.zeros(shape, dtype=bool)
    cord_mask[2:4, 2:4, 2:4] = True
    # Clinical tolerance for spinal cord is 45 Gy; inject 52 Gy
    eval_dose[cord_mask] = 52.0
    ref_dose[cord_mask] = 52.0

    report = verify_model_output(
        evaluated_dose=eval_dose,
        reference_dose=ref_dose,
        spacing_mm=(3.0, 1.0, 1.0),
        model_id="toxic_dose_model",
        dataset_id="test_cohort",
        structure_masks={"SpinalCord": cord_mask},
        oar_tolerance_limits_gy={"SpinalCord":45.},
    )

    assert report.status == DecisionStatus.REJECTED
    assert len(report.oar_violations) > 0
    assert any("spinalcord" in v.lower() or "spinal_cord" in v.lower() for v in report.oar_violations)
    assert any("52.00 gy" in v.lower() or "52.0 gy" in v.lower() for v in report.oar_violations)


def test_beam_energy_bounds_fail_closed():
    """Verify that unphysical beam kinetic energies trigger immediate rejection."""
    eval_dose = np.full((3, 5, 5), 20.0, dtype=float)

    # 350 MeV exceeds clinical radiotherapy 250 MeV limit
    report = verify_model_output(
        evaluated_dose=eval_dose,
        energy_mev=350.0,
    )
    assert report.status == DecisionStatus.REJECTED
    assert report.hard_physics_passed is False
    assert any("energy" in r.lower() for r in report.rejection_reasons)


def test_coordinate_frame_orthogonality():
    """Verify that non-orthogonal direction cosines trigger immediate rejection."""
    eval_dose = np.full((3, 5, 5), 20.0, dtype=float)

    # Non-orthogonal row and column vectors (dot product > 1e-4)
    non_ortho = [1.0, 0.05, 0.0, 0.0, 1.0, 0.0]
    report = verify_model_output(
        evaluated_dose=eval_dose,
        image_orientation=non_ortho,
    )
    assert report.status == DecisionStatus.REJECTED
    assert report.hard_physics_passed is False
    assert any("orthogonality" in r.lower() for r in report.rejection_reasons)


def test_hipaa_unscrubbed_rejection():
    """Verify that unscrubbed patient identifiers in DICOM trigger HIPAA rejection."""
    ds = create_synthetic_dicom_dose(patient_name="John Doe", patient_id="12345")
    report = verify_model_output(
        evaluated_dose=np.full((5, 10, 10), 30.0, dtype=float),
        dicom_dataset=ds,
    )
    assert report.status == DecisionStatus.REJECTED
    assert report.hard_physics_passed is False
    assert any("hipaa" in r.lower() for r in report.rejection_reasons)


def test_clinical_summary_and_follow_up_actions_generation():
    """Verify that EvaluationReport provides human-interpretable clinical summary and follow-up actions."""
    shape = (5, 10, 10)
    cord_mask = np.zeros(shape, dtype=bool)
    cord_mask[2:4, 2:4, 2:4] = True
    eval_dose = np.full(shape, 40.0, dtype=float)
    eval_dose[cord_mask] = 52.0  # Serial OAR breach

    report = verify_model_output(
        evaluated_dose=eval_dose,
        reference_dose=np.full(shape, 40.0, dtype=float),
        spacing_mm=(3.0, 1.0, 1.0),
        structure_masks={"SpinalCord": cord_mask},
        oar_tolerance_limits_gy={"SpinalCord":45.},
    )

    assert report.status == DecisionStatus.REJECTED
    assert len(report.clinical_summary) > 20
    assert len(report.follow_up_actions) > 0
    # Check that actionable advice for TPS optimizer & OAR was generated
    assert any("TPS Optimization" in a for a in report.follow_up_actions)

    # Test Markdown formatting
    md = report.to_markdown()
    assert "# OpenRad — Dose-model numerical preflight" in md
    assert "Follow-up actions" in md
    assert "Audit Integrity Hash" in md


def test_agent_orchestration_with_follow_up_report(tmp_path):
    """Verify that OpenRadAgent executes model verification intent and saves report artifact."""
    from openrad.core.agent import OpenRadAgent

    shape = (5, 10, 10)
    dose = np.full(shape, 45.0, dtype=float)

    agent = OpenRadAgent(artifact_dir=str(tmp_path / "artifacts"))
    result = agent.run(
        task="Please verify the clinical dose model and generate a follow up actions report",
        context={
            "evaluation": {
                "evaluated_dose": dose,
                "reference_dose": dose,
                "spacing_mm": (3.0, 1.0, 1.0),
                "model_id": "deep_dose_net_v2",
                "dataset_id": "clinical_hnscc_test",
            }
        },
    )

    assert result.success is True
    assert "OpenRad — Dose-model numerical preflight" in result.response
    assert "Follow-up actions" in result.response
    assert len(result.artifacts) == 1
    assert result.artifacts[0].endswith(".md")
    assert (tmp_path / "artifacts" / Path(result.artifacts[0]).name).exists()

