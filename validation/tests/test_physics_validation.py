"""Test suite for OpenRad Agent physics validation guardrails and tools."""

import numpy as np
import pytest

from openrad.validation.physics_rules import (
    PhysicsValidationEngine,
    DoseIntegrityError,
    BeamEnergyBoundsError,
    GammaEvaluationError,
    DICOMGeometryError,
    RadiobiologyBoundsError,
)
from openrad.tools.dicom_tool import analyze_dvh
from openrad.tools.gamma_tool import evaluate_gamma_index
from openrad.tools.topas_tool import generate_topas_deck
from openrad.tools.radiobio_tool import calculate_tcp_ntcp
from openrad.sandbox.repl import StatefulPythonREPL
from openrad.core.agent import OpenRadAgent


# ==============================================================================
# 1. Physics Guardrail Tests
# ==============================================================================

def test_dose_grid_integrity_valid():
    """Validates that non-negative dose array passes integrity check."""
    valid_dose = np.array([0.0, 1.5, 45.0, 69.96])
    res = PhysicsValidationEngine.validate_dose_grid(valid_dose, raise_on_fail=True)
    assert res.passed is True


def test_dose_grid_integrity_negative_rejected():
    """Validates that negative doses are caught and raise DoseIntegrityError."""
    invalid_dose = np.array([10.0, 5.0, -0.5, 20.0])
    with pytest.raises(DoseIntegrityError) as exc_info:
        PhysicsValidationEngine.validate_dose_grid(invalid_dose, raise_on_fail=True)
    assert "Negative dose values detected" in str(exc_info.value)

    # Check non-raising validation result
    res = PhysicsValidationEngine.validate_dose_grid(invalid_dose, raise_on_fail=False)
    assert res.passed is False
    assert "re-check array calibration" in res.remediation_suggestion.lower()


def test_beam_energy_bounds_clinical_valid():
    """Clinical energies (e.g. 6 MV, 150 MeV) pass validation."""
    for energy in [0.05, 6.0, 18.0, 70.0, 150.0, 250.0]:
        res = PhysicsValidationEngine.validate_beam_energy(energy, raise_on_fail=True)
        assert res.passed is True


def test_beam_energy_bounds_unphysical_rejected():
    """Energies < 0.01 MeV or > 250 MeV are rejected as unphysical."""
    for bad_energy in [-10.0, 0.001, 300.0, 1000.0]:
        with pytest.raises(BeamEnergyBoundsError):
            PhysicsValidationEngine.validate_beam_energy(bad_energy, raise_on_fail=True)

        res = PhysicsValidationEngine.validate_beam_energy(bad_energy, raise_on_fail=False)
        assert res.passed is False
        assert "outside clinical radiotherapy bounds" in res.error_message


def test_gamma_index_bounds():
    """Validates Gamma passing rate must be strictly within 0% - 100%."""
    # Valid
    assert PhysicsValidationEngine.validate_gamma_index(98.5, 0.45, 1.2).passed is True
    assert PhysicsValidationEngine.validate_gamma_index(0.0).passed is True
    assert PhysicsValidationEngine.validate_gamma_index(100.0).passed is True

    # Invalid
    with pytest.raises(GammaEvaluationError):
        PhysicsValidationEngine.validate_gamma_index(105.0, raise_on_fail=True)

    with pytest.raises(GammaEvaluationError):
        PhysicsValidationEngine.validate_gamma_index(-5.0, raise_on_fail=True)


def test_dicom_geometry_spacing_and_orthogonality():
    """Validates voxel spacing > 0 and orthogonal orientation vectors."""
    # Valid spacing and standard axial orientation: [1, 0, 0, 0, 1, 0]
    res_valid = PhysicsValidationEngine.validate_dicom_geometry(
        pixel_spacing=[2.0, 2.0],
        slice_thickness=3.0,
        image_orientation=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        raise_on_fail=True,
    )
    assert res_valid.passed is True

    # Non-positive spacing rejected
    with pytest.raises(DICOMGeometryError):
        PhysicsValidationEngine.validate_dicom_geometry([0.0, 2.0], raise_on_fail=True)

    # Non-orthogonal orientation rejected (dot product != 0)
    with pytest.raises(DICOMGeometryError) as exc_info:
        PhysicsValidationEngine.validate_dicom_geometry(
            pixel_spacing=[1.0, 1.0],
            image_orientation=[1.0, 0.0, 0.0, 2**-0.5, 2**-0.5, 0.0],  # dot product = 0.707
            raise_on_fail=True,
        )
    assert "not orthogonal" in str(exc_info.value)


# ==============================================================================
# 2. Deterministic Tools Tests
# ==============================================================================

def test_topas_generator_tool():
    """Generates and checks valid TOPAS deck."""
    deck = generate_topas_deck(
        particle_type="proton",
        energy_MeV=200.0,
        geometry_type="water_phantom",
        phantom_dimensions_cm=[30.0, 30.0, 30.0],
        number_of_histories=10000,
    )
    assert "s:So/Beam/BeamParticle = \"proton\"" in deck
    assert float(next(line.split("=")[1].split()[0] for line in deck.splitlines() if line.startswith("d:So/Beam/BeamEnergy"))) == 200.0
    assert "s:Ge/Phantom/Material = \"G4_WATER\"" in deck
    assert "s:Sc/DoseScorer/Quantity = \"DoseToMedium\"" in deck


def test_topas_generator_unphysical_energy():
    """Verifies that TOPAS generator raises error on unphysical energy."""
    with pytest.raises(BeamEnergyBoundsError):
        generate_topas_deck(particle_type="proton", energy_MeV=500.0)


def test_radiobiology_lkb_ntcp():
    """Tests Lyman-Kutcher-Burman NTCP calculation."""
    dvh = {
        "dose_bins_Gy": [0.0, 20.0, 40.0, 60.0, 80.0],
        "volume_percent": [100.0, 100.0, 80.0, 40.0, 0.0],
    }
    # Parameters for organ with TD50=65 Gy
    res = calculate_tcp_ntcp(dvh, "LKB", {"TD50": 65.0, "m": 0.15, "n": 0.25})
    assert "NTCP" in res
    assert 0.0 <= res["NTCP"] <= 1.0
    assert res["EUD_Gy"] > 0


def test_gamma_tool_in_memory():
    """Tests Gamma Index calculation on synthetic 2D Gaussian dose arrays."""
    x = np.linspace(-40, 40, 31)
    coords = (x, x)
    ref = np.exp(-(coords[0][:, None]**2 + coords[1][None, :]**2) / (2 * 15**2)) * 60.0
    # 1.5% dose difference
    eval_dose = ref * 0.985

    res = evaluate_gamma_index(
        reference_dose_path=ref,
        evaluated_dose_path=eval_dose,
        dose_tolerance_percent=3.0,
        distance_tolerance_mm=3.0,
        dose_threshold_percent=10.0,
        reference_spacing_mm=[80/30,80/30],
        evaluated_spacing_mm=[80/30,80/30],
    )
    assert res["passing_rate"] >= 95.0
    assert res["average_gamma"] < 1.0


# ==============================================================================
# 3. Stateful REPL & Agent Orchestrator Tests
# ==============================================================================

def test_stateful_repl_persistence():
    """Tests that the REPL preserves state across executions."""
    repl = StatefulPythonREPL()
    res1 = repl.execute("a = 15; b = 25")
    assert res1.success is True

    res2 = repl.execute("c = a + b; c")
    assert res2.success is True
    assert res2.result == 40


def test_stateful_repl_guardrail_rejection():
    """Tests that negative dose assigned in REPL triggers guardrail failure."""
    repl = StatefulPythonREPL()
    res = repl.execute("dose_matrix = np.array([[50.0, 20.0], [-1.0, 30.0]])")
    assert res.success is False
    assert "Physics Guardrail Violation" in res.error


def test_openrad_agent_orchestration():
    """Tests OpenRadAgent handling queries with tool routing and guardrails."""
    agent = OpenRadAgent()
    # Test TOPAS task
    res = agent.run("Generate TOPAS simulation deck for a 160 MeV proton beam in water phantom")
    assert res.success is True
    assert "TOPAS Monte Carlo Input Deck Generated" in res.response
    assert len(res.artifacts) > 0
