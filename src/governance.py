"""Hash chained local audit and signed review records. No clinical authorization."""
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def verify_records(records):
    previous = '0' * 64
    for index, record in enumerate(records):
        payload = {k: v for k, v in record.items() if k != 'hash'}
        if payload.get('sequence') != index or payload.get('previous_hash') != previous or digest(payload) != record.get('hash'):
            raise ValueError('Audit chain integrity failure')
        previous = record['hash']
    return previous


def append_record(path, event):
    """Lock, verify existing chain, append and fsync; never rewrites previous events."""
    with Path(path).open('a+', encoding='utf-8') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        records = [json.loads(line) for line in handle if line.strip()]
        previous = verify_records(records)
        record = dict(sequence=len(records), previous_hash=previous,
                      timestamp=datetime.now(timezone.utc).isoformat(), event=event)
        record['hash'] = digest(record)
        handle.write(canonical(record).decode() + '\n')
        handle.flush()
        os.fsync(handle.fileno())
        return record


def signed_review(audit_path, decision, payload, signature_b64, trusted_keys):
    """Verify external Ed25519 signoff against an operator-controlled key registry.

    payload: decision_hash, session_id, reviewer_id, disposition, justification, nonce.
    The automated result remains immutable, including hard physical rejections.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    required = {'decision_hash', 'session_id', 'reviewer_id', 'disposition', 'justification', 'nonce'}
    if set(payload) != required or not all(isinstance(v, str) and v.strip() for v in payload.values()):
        raise ValueError('Review requires decision hash, reviewer, disposition, justification and nonce')
    if len(payload['justification'].strip()) < 10 or len(payload['nonce']) < 16:
        raise ValueError('Provide a substantive justification and unique nonce of at least 16 characters')
    if payload['decision_hash'] != decision['decision_hash'] or payload['session_id'] != decision['session_id']:
        raise ValueError('Review does not match this decision')
    if payload['disposition'] not in ('APPROVED', 'REJECTED', 'FLAGGED_FOR_REVIEW'):
        raise ValueError('Invalid review disposition')
    if not decision['hard_checks_passed'] and payload['disposition'] == 'APPROVED':
        raise ValueError('Invalid physical inputs cannot be approved; correct the derived output and re-evaluate')
    key = trusted_keys.get(payload['reviewer_id'])
    if not isinstance(key, str):
        raise ValueError('Reviewer is not in the trusted key registry')
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(key, validate=True)).verify(
            base64.b64decode(signature_b64, validate=True), canonical(payload))
    except (InvalidSignature, ValueError) as exc:
        raise ValueError('Invalid reviewer signature') from exc
    # Replay prevention and appending must use the same lock.
    with Path(str(audit_path) + '.review.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        records = [json.loads(line) for line in Path(audit_path).read_text().splitlines() if line.strip()]
        verify_records(records)
        if not any(r['event'].get('decision_hash') == decision['decision_hash'] and r['event'].get('type') == 'evaluation' for r in records):
            raise ValueError('No original evaluation in this audit trail')
        if any(r['event'].get('payload', {}).get('nonce') == payload['nonce'] for r in records):
            raise ValueError('Review nonce already used')
        return append_record(audit_path, dict(type='signed_review', payload=payload, signature=signature_b64,
                            key_sha256=hashlib.sha256(base64.b64decode(key)).hexdigest(), clinical_release=False))
