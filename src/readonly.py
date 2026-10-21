"""Prevent application output under raw patient-data roots (including symlinks)."""
import json
import os
from pathlib import Path


def assert_output_path(path):
    target = Path(path).resolve()
    configured = json.loads(os.getenv('OPENRAD_DATA_ROOTS', '[]'))
    if not isinstance(configured, list) or not all(isinstance(root, str) for root in configured):
        raise ValueError('OPENRAD_DATA_ROOTS must contain a JSON list of paths')
    roots = [Path(root).resolve() for root in configured]
    if 'raw' in target.parts or any(target == root or root in target.parents for root in roots):
        raise ValueError('Raw data is read-only; choose an output directory outside raw data roots')
    return target
