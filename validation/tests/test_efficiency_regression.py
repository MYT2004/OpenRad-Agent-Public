"""Independent numerical oracles and lazy UI initialization regressions."""
from pathlib import Path

import numpy as np
import pytest

from openrad.tools.gamma_tool import evaluate_gamma_index
from src.storage import StorageManager, session_scope


@pytest.mark.parametrize('shape,evaluation_shape', [((3, 4), (4, 5)), ((2, 3, 4), (3, 4, 5))])
@pytest.mark.parametrize('cutoff', [0., 80., 100.])
def test_gamma_matches_exhaustive_physical_distance_oracle(tmp_path, shape, evaluation_shape, cutoff):
    rng = np.random.default_rng(263)
    reference = rng.uniform(1, 70, shape)
    evaluation = rng.uniform(1, 70, evaluation_shape)
    ref_spacing = np.arange(1, len(shape) + 1) * .7
    eval_spacing = np.arange(1, len(shape) + 1) * 1.1
    # Independent Cartesian enumeration, including unequal sizes and spacing.
    ref_points = np.array(list(np.ndindex(shape))) * ref_spacing
    eval_points = np.array(list(np.ndindex(evaluation_shape))) * eval_spacing
    keep = reference.ravel() >= reference.max() * cutoff / 100
    squared_distance = np.sum(((ref_points[keep, None] - eval_points[None]) / 2)**2, axis=2)
    squared_dose = ((reference.ravel()[keep, None] - evaluation.ravel()[None]) / (reference.max() * .03))**2
    expected = np.sqrt(squared_distance + squared_dose).min(axis=1)
    with session_scope(StorageManager(str(tmp_path / 'sessions'))):
        result = evaluate_gamma_index(reference, evaluation, 3, 2, cutoff,
                                      list(ref_spacing), list(eval_spacing))
    assert result['evaluated_voxels'] == len(expected)
    assert result['passing_rate'] == 100 * np.count_nonzero(expected <= 1) / len(expected)
    assert result['average_gamma_unrounded'] == pytest.approx(float(expected.mean()), abs=1e-12)
    assert result['max_gamma_unrounded'] == pytest.approx(float(expected.max()), abs=1e-12)


def test_intake_defers_agent_and_reuses_it_when_needed(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('OPENRAD_DATA_ROOTS', '[]')
    monkeypatch.setenv('STORAGE_DIR', str(tmp_path / 'sessions'))
    path = Path(__file__).resolve().parents[2] / 'frontend' / 'app.py'
    app = AppTest.from_file(str(path), default_timeout=30).run()
    assert not app.exception
    assert 'agent' not in app.session_state
    assert not list((tmp_path / 'sessions').glob('*'))
    app.sidebar.selectbox[0].select('Stateful Python REPL Sandbox').run()
    assert not app.exception
    original = app.session_state['agent']
    app.sidebar.selectbox[0].select('Interactive Agent Query').run()
    assert not app.exception
    assert app.session_state['agent'] is original
