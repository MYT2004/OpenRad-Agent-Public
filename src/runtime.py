"""Honest deployment profile and per-process admission control for research jobs."""
import os
import threading
from functools import wraps


def research_readiness():
    return {
        'execution_mode': 'deterministic_research',
        'access_model': 'single_trusted_operator',
        'production_ready': False,
        'clinical_release': False,
        'outstanding_requirements': [
            'Authenticated per-user/tenant ownership and approved input access',
            'Durable cross-instance transactional storage, recovery and external audit anchoring',
            'Isolated workers with enforced time/cancellation budgets and measured capacity',
            'Independent model/clinical qualification, protocol review and calibrated uncertainty/OOD'],
    }


def validate_deployment_profile():
    if os.getenv('OPENRAD_DEPLOYMENT_PROFILE', 'research') != 'research':
        raise RuntimeError('Only the single-operator research profile is implemented; shared/clinical deployment is not qualified.')


class JobAdmission:
    """Bound simultaneous CPU/memory jobs in one process; not a distributed queue."""
    def __init__(self, capacity=1):
        if type(capacity) is not int or not 1 <= capacity <= 8:
            raise ValueError('Job concurrency must be an integer in [1,8].')
        self._slots = threading.BoundedSemaphore(capacity)

    def bounded(self, function):
        @wraps(function)
        def run(*args, **kwargs):
            from fastapi import HTTPException
            if not self._slots.acquire(blocking=False):
                raise HTTPException(status_code=429, detail='Research job capacity reached; retry after the active job completes.')
            try:
                return function(*args, **kwargs)
            finally:
                self._slots.release()
        return run
