"""Enforced post-tool validation; internal arrays never enter API responses."""
from functools import wraps
import numpy as np
from openrad.validation.physics_rules import PhysicsValidationEngine, DoseIntegrityError


def validate_tool_output(output):
    if not isinstance(output, dict):
        raise DoseIntegrityError('Tools must return structured results.')
    def inspect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ('dose_grid', 'dose_array', 'dose_values'):
                    arr = np.asarray(item, dtype=float)
                    PhysicsValidationEngine.validate_dose_grid(arr, raise_on_fail=True)
                    if key != 'dose_values' and arr.ndim != 3:
                        raise DoseIntegrityError('Dose grid must have three spatial axes.')
                    expected = value.get('expected_shape')
                    if expected is not None and tuple(arr.shape) != tuple(expected):
                        raise DoseIntegrityError('Dose grid shape differs from declared geometry.')
                    axes = value.get('axes_mm')
                    if axes is not None and (len(axes) != arr.ndim or any(len(axis) != size or not np.isfinite(axis).all() or (np.diff(axis) <= 0).any() for axis, size in zip(axes, arr.shape))):
                        raise DoseIntegrityError('Dose axes do not match array geometry.')
                elif isinstance(item, (dict, list)):
                    inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)
    inspect(output)
    return {key: value for key, value in output.items() if key != '_physics'}


def post_tool_call(fn):
    """Run mandatory checks after every invocation of a decorated tool."""
    @wraps(fn)
    def checked(*args, **kwargs):
        return validate_tool_output(fn(*args, **kwargs))
    return checked
