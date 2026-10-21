"""Minimal local operation outcomes; never persist prompts, arguments or exceptions."""
from functools import wraps
import hashlib
import json
from pathlib import Path
from uuid import uuid4
from src.storage import current_session, session_scope
from src.governance import append_record


def audited_operation(function):
    """Bind nested tools to one session and record returned/error outcomes.

    Audit failure propagates: a successful committed result must not be claimed
    when its audit record cannot be written. This is local POSIX persistence,
    not authenticated durable multi-instance storage or external anchoring.
    """
    @wraps(function)
    def run(*args, **kwargs):
        manager, session_id = current_session()
        operation_id = uuid4().hex
        path = Path(manager.get_session_dir(session_id)) / 'operations.jsonl'
        common = dict(operation=function.__name__, operation_id=operation_id,
                      clinical_release=False)
        with session_scope(manager, session_id):
            append_record(path, dict(type='operation_started', **common))
            try:
                result = function(*args, **kwargs)
                payload = result.model_dump(mode='json') if hasattr(result, 'model_dump') else result
                # No prompts, arguments, output contents or external exception text
                # enter the ledger, including serialization failures.
                encoded = json.dumps(payload, sort_keys=True, allow_nan=False).encode()
            except Exception as exc:
                append_record(path, dict(type='operation_error', error_type=type(exc).__name__, **common))
                raise
            append_record(path, dict(type='operation_returned',
                                      output_sha256=hashlib.sha256(encoded).hexdigest(), **common))
            return result
    return run
