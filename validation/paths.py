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


from contextlib import contextmanager
import fcntl
import json
import os


def write_evidence(path, value):
    """Atomically commit evidence under the caller's output reservation."""
    from src.readonly import assert_output_path
    path = assert_output_path(path)
    temporary = path.with_name('.' + path.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as handle:
            json.dump(value, handle, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def reserve_evidence(path, overwrite=False):
    """Refuse collisions before tool work, retaining one writer per output file."""
    from src.readonly import assert_output_path
    path = assert_output_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name('.' + path.name + '.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Evidence destination is already in use.') from None
        try:
            if path.exists() and not overwrite:
                raise ValueError('Evidence already exists; choose a new directory or explicit --force-overwrite.')
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
