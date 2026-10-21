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
    result = evaluate_gamma_index(np.full((2, 2), 100.), np.full((2, 2), 106.), reference_spacing_mm=[1,1], evaluated_spacing_mm=[1,1])
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


def test_resolve_save_path_blocks_raw_writes():
    from src.tools import resolve_save_path
    from pathlib import Path
    with pytest.raises(PermissionError):
        resolve_save_path('data/raw/modified.dcm')
    with pytest.raises(PermissionError):
        resolve_save_path('./data/raw/test/sample.txt')
    raw_abs = (Path.cwd() / 'data' / 'raw' / 'forbidden.npy').resolve()
    with pytest.raises(PermissionError):
        resolve_save_path(str(raw_abs))


def test_resolve_save_path_directs_to_processed(tmp_path,monkeypatch):
    from src.tools import resolve_save_path
    monkeypatch.chdir(tmp_path)
    out = resolve_save_path('dvh_test.png', patient_id='PT_123')
    assert 'data/processed/PT_123/dvh_test.png' in str(out).replace('\\', '/')
    assert out.parent.exists()


def test_builtin_roi_aliases():
    from src.tools import BUILTIN_ROI_ALIASES
    assert BUILTIN_ROI_ALIASES['cord'] == 'SpinalCord'
    assert BUILTIN_ROI_ALIASES['rt parotid'] == 'Parotid_R'
    assert BUILTIN_ROI_ALIASES['lt parotid'] == 'Parotid_L'


def test_resolve_save_path_3_args_blocks_raw_writes():
    from src.tools import resolve_save_path
    with pytest.raises(PermissionError):
        resolve_save_path('data/raw/test_patient/file.dcm', 'test_patient', 'test.dcm')
    with pytest.raises(PermissionError):
        resolve_save_path('safe_dir', 'test_patient', 'data/raw/target.dcm')


def test_ensure_case_output_separation_enforces_permission_error(tmp_path):
    from src.case_verification import ensure_case_output_separation
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    inside_dir = case_dir / "output"
    inside_dir.mkdir()

    # Rule 1: output inside case directory must raise PermissionError
    with pytest.raises(PermissionError):
        ensure_case_output_separation(case_dir, inside_dir)

    # Rule 1: output targeting data/raw must raise PermissionError
    with pytest.raises(PermissionError):
        ensure_case_output_separation(case_dir, "data/raw/forbidden_out")


def test_storage_trajectory_concurrency_and_corruption_quarantine(tmp_path):
    import concurrent.futures
    from src.storage import StorageManager, CorruptedSessionError
    mgr = StorageManager(str(tmp_path / "sessions"))
    session_id = "concurrent_test"
    mgr.initialize_session(session_id)

    # 1. Test concurrent writes preserve all entries
    num_writes = 32
    def write_worker(idx):
        mgr.save_trajectory(session_id, f"prompt_{idx}", f"response_{idx}", {"worker": idx})

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(write_worker, range(num_writes)))

    history = mgr.load_trajectory(session_id)
    assert len(history) == num_writes
    assert len({h["user_prompt"] for h in history}) == num_writes

    # 2. Test corruption quarantine: corrupt JSON must not be silently wiped
    traj_file = tmp_path / "sessions" / session_id / "trajectory.json"
    traj_file.write_text("{invalid_json_corrupted", encoding="utf-8")

    with pytest.raises(CorruptedSessionError):
        mgr.load_trajectory(session_id)

    with pytest.raises(CorruptedSessionError):
        mgr.save_trajectory(session_id, "new_prompt", "new_response")

    # Confirm quarantine file exists
    corrupt_files = list((tmp_path / "sessions" / session_id).glob("trajectory.json.corrupt.*"))
    assert len(corrupt_files) >= 1


def test_api_rejects_boolean_beam_energy(tmp_path, monkeypatch):
    import server
    from fastapi.testclient import TestClient
    from src.storage import StorageManager
    monkeypatch.setattr(server, 'storage_mgr', StorageManager(str(tmp_path / 'api')))
    client = TestClient(server.app)

    # Boolean energy must be rejected with HTTP 422
    res_bool = client.post('/api/v1/topas/generate', json={'particle': 'proton', 'energy_mev': True, 'histories': 1000})
    assert res_bool.status_code == 422
    assert 'boolean' in res_bool.text.lower()

    # Valid float energy must be accepted
    res_valid = client.post('/api/v1/topas/generate', json={'particle': 'proton', 'energy_mev': 150.0, 'histories': 1000})
    assert res_valid.status_code == 200


def test_gamma_rejects_same_path_self_comparison(tmp_path):
    import os
    from openrad.tools.gamma_tool import evaluate_gamma_index, GammaEvaluationError
    dose_file = tmp_path / "dose.npy"
    np.save(dose_file, np.ones((5, 5)))

    # 1. Exact path
    with pytest.raises(GammaEvaluationError, match="INDEPENDENT_REFERENCE_REQUIRED"):
        evaluate_gamma_index(str(dose_file), str(dose_file), reference_spacing_mm=[1,1], evaluated_spacing_mm=[1,1])

    # 2. Symlink alias
    symlink_file = tmp_path / "dose_symlink.npy"
    try:
        symlink_file.symlink_to(dose_file)
        with pytest.raises(GammaEvaluationError, match="INDEPENDENT_REFERENCE_REQUIRED"):
            evaluate_gamma_index(str(dose_file), str(symlink_file), reference_spacing_mm=[1,1], evaluated_spacing_mm=[1,1])
    except (OSError, NotImplementedError):
        pass

    # 3. Hardlink alias
    hardlink_file = tmp_path / "dose_hardlink.npy"
    try:
        os.link(str(dose_file), str(hardlink_file))
        with pytest.raises(GammaEvaluationError, match="INDEPENDENT_REFERENCE_REQUIRED"):
            evaluate_gamma_index(str(dose_file), str(hardlink_file), reference_spacing_mm=[1,1], evaluated_spacing_mm=[1,1])
    except (OSError, NotImplementedError):
        pass


def test_api_gamma_sanitizes_errors_and_redacts_paths(tmp_path, monkeypatch):
    import server
    from fastapi.testclient import TestClient
    from src.storage import StorageManager
    monkeypatch.setattr(server, 'storage_mgr', StorageManager(str(tmp_path / 'api')))
    client = TestClient(server.app)

    # Malformed file with internal text sentinel
    bad_file = tmp_path / "secret_patient_data.csv"
    bad_file.write_text("INTERNAL_SECRET_DIAGNOSTIC_DATA,123", encoding="utf-8")

    # Distinct valid evaluated file so it genuinely reaches the parser without short-circuiting on self-comparison guard
    valid_file = tmp_path / "valid_eval.npy"
    np.save(valid_file, np.ones((5, 5), dtype=np.float32) * 50.0)

    response = client.post('/api/v1/gamma/evaluate', json={
        'reference_dose_path': str(bad_file),
        'evaluated_dose_path': str(valid_file),
        'reference_spacing_mm': [1.0, 1.0],
        'evaluated_spacing_mm': [1.0, 1.0],
    })
    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported or malformed dose data: file could not be parsed as a numerical dose grid."
    # Must NOT echo the file content or internal data or full sensitive paths
    assert 'INTERNAL_SECRET_DIAGNOSTIC_DATA' not in response.text
    assert str(bad_file) not in response.text
    assert 'INDEPENDENT_REFERENCE_REQUIRED' not in response.text


def test_dvh_curve_physics_guardrails():
    from openrad.validation.physics_rules import PhysicsValidationEngine as PV, DVHCurveError

    # 1. Valid curve passes
    res_valid = PV.validate_dvh_curve([0, 10, 20, 30], [100, 90, 40, 0])
    assert res_valid.passed is True

    # 2. One-bin curve rejected
    res_1bin = PV.validate_dvh_curve([10], [100])
    assert res_1bin.passed is False
    assert "at least 2 points" in res_1bin.error_message
    with pytest.raises(DVHCurveError):
        PV.validate_dvh_curve([10], [100], raise_on_fail=True)

    # 3. Negative volume percentage rejected
    res_neg_v = PV.validate_dvh_curve([0, 10, 20], [100, -2, 0])
    assert res_neg_v.passed is False
    assert "outside physical range" in res_neg_v.error_message

    # 4. Descending dose bins rejected
    res_desc_d = PV.validate_dvh_curve([0, 20, 15], [100, 50, 0])
    assert res_desc_d.passed is False
    assert "strictly increasing" in res_desc_d.error_message

    # 5. Non-finite values rejected
    res_nan = PV.validate_dvh_curve([0, float('nan'), 20], [100, 50, 0])
    assert res_nan.passed is False
    assert "NaN or infinite" in res_nan.error_message

    # 6. Non-monotonic volume increase rejected
    res_non_mono = PV.validate_dvh_curve([0, 10, 20, 30], [100, 70, 85, 0])
    assert res_non_mono.passed is False
    assert "violates physical monotonicity" in res_non_mono.error_message


def test_trajectory_quarantines_empty_or_malformed_entries(tmp_path):
    from src.storage import StorageManager, CorruptedSessionError
    mgr = StorageManager(str(tmp_path / "sessions"))
    session_id = "test_quarantine_session"
    sess_dir = tmp_path / "sessions" / session_id
    sess_dir.mkdir(parents=True, exist_ok=True)
    traj_file = sess_dir / "trajectory.json"

    # Case A: 0-byte existing file must be quarantined as corrupted, not treated as new empty session
    traj_file.write_text("", encoding="utf-8")
    with pytest.raises(CorruptedSessionError):
        mgr.load_trajectory(session_id)
    assert len(list(sess_dir.glob("trajectory.json.corrupt.*"))) >= 1

    # Case B: Whitespace-only existing file must be quarantined
    traj_file.write_text("   \n\t  ", encoding="utf-8")
    with pytest.raises(CorruptedSessionError):
        mgr.load_trajectory(session_id)

    # Case C: JSON list containing invalid non-dict items (e.g. [1, 2])
    traj_file.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(CorruptedSessionError):
        mgr.load_trajectory(session_id)

    # Case D: JSON list containing dicts with missing mandatory schema keys
    traj_file.write_text('[{"missing_prompt": "val"}]', encoding="utf-8")
    with pytest.raises(CorruptedSessionError):
        mgr.load_trajectory(session_id)


