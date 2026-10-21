"""Allocation preflight for bounded local research dose jobs; no clinical qualification."""
import math
import os
from pathlib import Path
import numpy as np


class InputBudgetError(ValueError):
    """Public error without source paths or file contents."""


def dose_voxel_budget():
    try:
        value = int(os.getenv('OPENRAD_MAX_DOSE_VOXELS', '2000000'))
    except ValueError:
        raise InputBudgetError('Dose voxel budget must be a positive integer.') from None
    if not 1 <= value <= 10000000:
        raise InputBudgetError('Dose voxel budget must lie between 1 and 10000000.')
    return value


def check_dose_shape(shape):
    if len(shape) not in (2, 3) or any(isinstance(n, bool) or n <= 0 for n in shape):
        raise InputBudgetError('Dose shape must have two or three nonempty spatial axes.')
    if math.prod(int(n) for n in shape) > dose_voxel_budget():
        raise InputBudgetError('Dose array exceeds the configured voxel budget.')


def check_input_file(path):
    # Byte cap also bounds structure/CSV parsing. Array headers are checked separately.
    if Path(path).stat().st_size > 128 * 1024 * 1024:
        raise InputBudgetError('Input exceeds the 128 MiB file budget.')


def preflight_npy(path):
    """Read header, not payload; never deserialize objects or allocate a claimed array."""
    check_input_file(path)
    with Path(path).open('rb') as handle:
        version = np.lib.format.read_magic(handle)
        if version == (1, 0):
            shape, _, dtype = np.lib.format.read_array_header_1_0(handle)
        elif version == (2, 0):
            shape, _, dtype = np.lib.format.read_array_header_2_0(handle)
        else:
            raise ValueError('Unsupported NPY header version.')
        check_dose_shape(shape)
        if dtype.kind not in 'ufi':
            raise ValueError('Dose requires a numeric, non-object dtype.')


def preflight_dicom_dose(path):
    import pydicom
    check_input_file(path)
    header = pydicom.dcmread(path, stop_before_pixels=True)
    check_dose_shape((int(header.NumberOfFrames), int(header.Rows), int(header.Columns)))
    return header
