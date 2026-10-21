"""Storage Manager for OpenRad Agent sessions, execution trajectories, and artifacts."""

import re
from pathlib import Path
import json
import os
import time
from typing import Any, Dict, List, Optional


try:
    import fcntl
except ImportError:
    fcntl = None
import shutil
from datetime import datetime
from uuid import uuid4


class CorruptedSessionError(ValueError, IOError):
    """Raised when session data or trajectory log is unreadable or corrupted."""
    pass


class StorageManager:
    """Manages session directories, execution trajectory logs, and visual/code artifacts

    for the OpenRad Agent runtime.
    """

    def __init__(self, base_dir: str = "./storage/sessions"):
        from src.readonly import assert_output_path
        self.base_dir = str(assert_output_path(base_dir))
        os.makedirs(self.base_dir, exist_ok=True)

    def initialize_session(self, session_id: str) -> str:
        session_dir = self.get_session_dir(session_id)
        artifacts_dir = self.get_artifacts_dir(session_id)

        os.makedirs(session_dir, exist_ok=True)
        os.makedirs(artifacts_dir, exist_ok=True)

        self._require_locking()
        meta_file = os.path.join(session_dir, "metadata.json")
        with open(os.path.join(session_dir, '.metadata.lock'), 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                if not os.path.exists(meta_file):
                    self._atomic_json(meta_file, {
                        'session_id': session_id,
                        'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                        'version': '1.0.0'})
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

        return session_dir

    def session_exists(self, session_id: str) -> bool:
        return os.path.exists(self.get_session_dir(session_id))

    def get_session_dir(self, session_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session_id):
            raise ValueError("Invalid session ID.")
        from src.readonly import assert_output_path
        target = assert_output_path(Path(self.base_dir) / session_id)
        if target.parent != Path(self.base_dir):
            raise ValueError('Session path escapes its storage boundary.')
        return str(target)

    def get_artifacts_dir(self, session_id: str) -> str:
        from src.readonly import assert_output_path
        directory = Path(self.get_session_dir(session_id))
        target = assert_output_path(directory / 'artifacts')
        if target.parent != directory:
            raise ValueError('Artifact directory escapes its session boundary.')
        return str(target)

    @staticmethod
    def _validate_event(event):
        if not isinstance(event, dict) or not all(isinstance(event.get(k), str)
                for k in ('timestamp', 'user_prompt', 'agent_response')):
            raise ValueError('Trajectory requires string timestamp, prompt and response.')
        datetime.strptime(event['timestamp'], '%Y-%m-%dT%H:%M:%SZ')
        version = event.get('schema_version', 1)  # Legacy valid events remain readable.
        if type(version) is not int or version != 1:
            raise ValueError('Unsupported trajectory schema version.')
        json.dumps(event, allow_nan=False)

    @staticmethod
    def _require_locking():
        if fcntl is None:
            raise RuntimeError('POSIX file locking (fcntl) is required for safe storage.')

    @staticmethod
    def _atomic_json(path, value):
        path = os.fspath(path)
        temporary = path + '.' + uuid4().hex + '.tmp'
        try:
            with open(temporary, 'x', encoding='utf-8') as handle:
                json.dump(value, handle, indent=2, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            # Persist the directory entry as well as the file on the local POSIX store.
            fd = os.open(os.path.dirname(path), os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _read_history(self, path):
        if not os.path.exists(path):
            return []
        try:
            with open(path, encoding='utf-8') as handle:
                history = json.load(handle)
            if not isinstance(history, list):
                raise ValueError('Trajectory must be a list.')
            for event in history:
                self._validate_event(event)
            return history
        except (ValueError, TypeError, OverflowError, OSError):
            backup = path + '.corrupt.' + uuid4().hex
            try:
                shutil.copy2(path, backup)
                preserved = True
            except OSError:
                preserved = False
            raise CorruptedSessionError(
                'Corrupted session trajectory; original was not replaced; '
                + ('a diagnostic copy was preserved.' if preserved else 'diagnostic copy unavailable.')
            ) from None

    def save_trajectory(self, session_id: str, prompt: str, response: str,
                        extra: Optional[Dict[str, Any]] = None) -> str:
        self._require_locking()
        reserved = {'timestamp', 'user_prompt', 'agent_response', 'schema_version'}
        if extra is not None and (not isinstance(extra, dict) or reserved.intersection(extra)):
            raise ValueError('Extra metadata cannot override reserved trajectory fields.')
        entry = dict(timestamp=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                     user_prompt=prompt, agent_response=response, schema_version=1)
        entry.update(extra or {})
        self._validate_event(entry)  # Refuse malformed new events before touching history.
        directory = self.get_session_dir(session_id)
        os.makedirs(directory, exist_ok=True)
        trajectory = os.path.join(directory, 'trajectory.json')
        with open(os.path.join(directory, '.trajectory.lock'), 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                history = self._read_history(trajectory)
                self._atomic_json(trajectory, history + [entry])
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
        return trajectory

    def load_trajectory(self, session_id: str) -> List[Dict[str, Any]]:
        self._require_locking()
        directory = self.get_session_dir(session_id)
        if not os.path.exists(directory):
            return []
        with open(os.path.join(directory, '.trajectory.lock'), 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            try:
                return self._read_history(os.path.join(directory, 'trajectory.json'))
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def list_artifacts(self, session_id: str) -> List[str]:
        artifacts_dir = self.get_artifacts_dir(session_id)
        if not os.path.exists(artifacts_dir):
            return []

        rel_artifacts = []
        for root, _, files in os.walk(artifacts_dir):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, self.base_dir)
                rel_artifacts.append(f"/artifacts/{rel_path}")
        return rel_artifacts

    def get_metadata(self, session_id: str) -> Dict[str, Any]:
        meta_file = os.path.join(self.get_session_dir(session_id), "metadata.json")
        if os.path.exists(meta_file):
            with open(meta_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

# Context-local sessions keep concurrent API/CLI calls in separate artifact folders.
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

_active_session = ContextVar('openrad_session', default=None)


@contextmanager
def session_scope(manager, session_id=None):
    session_id = session_id or str(uuid4())
    manager.initialize_session(session_id)
    token = _active_session.set((manager, session_id))
    try:
        yield session_id
    finally:
        _active_session.reset(token)


def current_session():
    active = _active_session.get()
    if active is None:
        manager = StorageManager(os.getenv('STORAGE_DIR', './storage/sessions'))
        session_id = str(uuid4())
        manager.initialize_session(session_id)
        return manager, session_id
    return active
