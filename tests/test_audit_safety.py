import numpy as np
import pytest
from openrad.validation.physics_rules import PhysicsValidationEngine as V
from openrad.tools.gamma_tool import evaluate_gamma_index
from openrad.tools.radiobio_tool import calculate_tcp_ntcp
from openrad.tools.topas_tool import generate_topas_deck

@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), -1e-8])
def test_invalid_dose_rejected(value):
    assert not V.validate_dose_grid([1, value]).passed

@pytest.mark.parametrize('value', [float('nan'), float('inf')])
def test_nonfinite_inputs_rejected(value):
    assert not V.validate_beam_energy(value).passed
    assert not V.validate_dicom_geometry([1, value]).passed
    assert not V.validate_gamma_index(95, max_gamma=value).passed

@pytest.mark.parametrize('kwargs', [{'dose_tolerance_percent': 0}, {'distance_tolerance_mm': -1}, {'dose_threshold_percent': 101}])
def test_gamma_bad_criteria(kwargs):
    with pytest.raises(ValueError):
        evaluate_gamma_index(np.ones((2, 2)), np.ones((2, 2)), **kwargs)

def test_gamma_analytic_constant_difference():
    result = evaluate_gamma_index(np.full((2, 2), 100.), np.full((2, 2), 106.))
    assert result['passing_rate'] == 0
    assert result['average_gamma'] == 2
    assert result['clinical_release'] is False

@pytest.mark.parametrize('volumes', [[100, 110, 0], [100, 50, 10], [0, 0, 0], [100, -1, 0]])
def test_bad_dvh(volumes):
    with pytest.raises(ValueError):
        calculate_tcp_ntcp({'dose_bins_Gy': [0, 20, 40], 'volume_percent': volumes}, 'LKB', {'TD50': 40, 'm': .2, 'n': 1})

def test_patient_water_substitution_blocked():
    with pytest.raises(ValueError, match='water-box'):
        generate_topas_deck('proton', 150, geometry_type='ct_patient')

from pydicom.dataset import Dataset
from openrad.tools.dose_geometry import validate_axial_dose
from openrad.core.agent import OpenRadAgent


def axial_dataset():
    ds = Dataset()
    ds.Modality = 'RTDOSE'
    ds.DoseUnits = 'GY'
    ds.DoseType = 'PHYSICAL'
    ds.DoseGridScaling = .01
    ds.PixelSpacing = [2, 2]
    ds.ImagePositionPatient = [0, 0, 0]
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.GridFrameOffsetVector = [0, 3, 6]
    ds.NumberOfFrames = 3
    return ds


def test_supported_axial_geometry():
    validate_axial_dose(axial_dataset())


@pytest.mark.parametrize('field,value', [('DoseUnits', 'RELATIVE'), ('DoseGridScaling', -1), ('GridFrameOffsetVector', [0, 3, 7]), ('ImageOrientationPatient', [0, 1, 0, 1, 0, 0])])
def test_unsupported_geometry_rejected(field, value):
    ds = axial_dataset()
    setattr(ds, field, value)
    with pytest.raises(ValueError):
        validate_axial_dose(ds)


def test_missing_geometry_rejected():
    ds = axial_dataset()
    del ds.ImagePositionPatient
    with pytest.raises(ValueError):
        validate_axial_dose(ds)


def test_agent_does_not_repair_requested_energy(tmp_path):
    agent = OpenRadAgent(artifact_dir=str(tmp_path))
    result = agent.run('Generate TOPAS deck for a 500 MeV proton beam')
    assert not result.success
    assert not result.artifacts


def test_agent_does_not_substitute_gamma_self_comparison(tmp_path):
    result = OpenRadAgent(artifact_dir=str(tmp_path)).run('Evaluate gamma QA')
    assert not result.success
    assert not result.tool_records
