"""Storage Manager for OpenRad Agent sessions, execution trajectories, and artifacts."""

import re
import json
import os
import time
from typing import Any, Dict, List, Optional


try:
    import fcntl
except ImportError:
    fcntl = None
import shutil
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

        meta_file = os.path.join(session_dir, "metadata.json")
        if not os.path.exists(meta_file):
            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "session_id": session_id,
                        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "version": "1.0.0",
                    },
                    f,
                    indent=2,
                )

        return session_dir

    def session_exists(self, session_id: str) -> bool:
        return os.path.exists(self.get_session_dir(session_id))

    def get_session_dir(self, session_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session_id):
            raise ValueError("Invalid session ID.")
        return os.path.join(self.base_dir, session_id)

    def get_artifacts_dir(self, session_id: str) -> str:
        return os.path.join(self.get_session_dir(session_id), "artifacts")

    def save_trajectory(
        self,
        session_id: str,
        prompt: str,
        response: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        if fcntl is None:
            raise RuntimeError("POSIX file locking (fcntl) is required for safe concurrent storage operations.")

        session_dir = self.get_session_dir(session_id)
        os.makedirs(session_dir, exist_ok=True)
        traj_file = os.path.join(session_dir, "trajectory.json")
        lock_file = os.path.join(session_dir, ".trajectory.lock")

        # Serialized atomic append via file locking
        with open(lock_file, "a", encoding="utf-8") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                history = []
                if os.path.exists(traj_file):
                    try:
                        with open(traj_file, "r", encoding="utf-8") as f:
                            content = f.read()
                        if not content.strip():
                            raise ValueError("Trajectory file exists but is empty or whitespace-only")
                        parsed = json.loads(content)
                        if not isinstance(parsed, list):
                            raise ValueError("Trajectory content must be a JSON list")
                        for idx, ev in enumerate(parsed):
                            if not isinstance(ev, dict) or not all(k in ev for k in ("timestamp", "user_prompt", "agent_response")):
                                raise ValueError(f"Trajectory entry at index {idx} is invalid or missing required schema fields")
                        history = parsed
                    except Exception as exc:
                        corrupt_backup = f"{traj_file}.corrupt.{int(time.time() * 1000)}"
                        try:
                            shutil.copy2(traj_file, corrupt_backup)
                        except Exception:
                            pass
                        raise CorruptedSessionError(
                            f"Corrupted trajectory in session {session_id}; preserved at {corrupt_backup}"
                        ) from exc

                entry = {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "user_prompt": prompt,
                    "agent_response": response,
                }
                if extra:
                    entry.update(extra)
                history.append(entry)

                # Atomic replacement in session dir ensures zero torn writes
                tmp_file = os.path.join(session_dir, f".trajectory.{uuid4().hex}.tmp")
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(history, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_file, traj_file)
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)

        return traj_file

    def load_trajectory(self, session_id: str) -> List[Dict[str, Any]]:
        session_dir = self.get_session_dir(session_id)
        traj_file = os.path.join(session_dir, "trajectory.json")
        if not os.path.exists(traj_file):
            return []
        if fcntl is None:
            raise RuntimeError("POSIX file locking (fcntl) is required for safe concurrent storage operations.")

        lock_file = os.path.join(session_dir, ".trajectory.lock")
        with open(lock_file, "a", encoding="utf-8") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_SH)
            try:
                with open(traj_file, "r", encoding="utf-8") as f:
                    content = f.read()
                if not content.strip():
                    raise ValueError("Trajectory file exists but is empty or whitespace-only")
                parsed = json.loads(content)
                if not isinstance(parsed, list):
                    raise ValueError("Trajectory content must be a JSON list")
                for idx, ev in enumerate(parsed):
                    if not isinstance(ev, dict) or not all(k in ev for k in ("timestamp", "user_prompt", "agent_response")):
                        raise ValueError(f"Trajectory entry at index {idx} is invalid or missing required schema fields")
                return parsed
            except Exception as exc:
                corrupt_backup = f"{traj_file}.corrupt.{int(time.time() * 1000)}"
                try:
                    shutil.copy2(traj_file, corrupt_backup)
                except Exception:
                    pass
                raise CorruptedSessionError(
                    f"Corrupted trajectory in session {session_id}; preserved at {corrupt_backup}"
                ) from exc
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)

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
