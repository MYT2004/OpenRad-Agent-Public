"""Storage Manager for OpenRad Agent sessions, execution trajectories, and artifacts."""

import json
import os
import time
from typing import Any, Dict, List


class StorageManager:
    """Manages session directories, execution trajectory logs, and visual/code artifacts

    for the OpenRad Agent runtime.
    """

    def __init__(self, base_dir: str = "./storage/sessions"):
        self.base_dir = os.path.abspath(base_dir)
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
        return os.path.join(self.base_dir, session_id)

    def get_artifacts_dir(self, session_id: str) -> str:
        return os.path.join(self.get_session_dir(session_id), "artifacts")

    def save_trajectory(self, session_id: str, prompt: str, response: str) -> str:
        session_dir = self.get_session_dir(session_id)
        traj_file = os.path.join(session_dir, "trajectory.json")

        history = []
        if os.path.exists(traj_file):
            try:
                with open(traj_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                history = []

        history.append(
            {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "user_prompt": prompt,
                "agent_response": response,
            }
        )

        with open(traj_file, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)

        return traj_file

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
