"""One location and collision-resistant naming for generated benchmark runs."""
from datetime import datetime, timezone
from pathlib import Path
import re
from uuid import uuid4

REPO_ROOT=Path(__file__).resolve().parents[1]


def new_run_directory(suite):
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',suite):
        raise ValueError('Use a simple benchmark suite name')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return REPO_ROOT/'validation/runs'/suite/f'{stamp}-{uuid4().hex[:8]}'
