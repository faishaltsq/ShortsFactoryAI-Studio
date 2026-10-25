"""Durable job execution: state, leases, artifacts, retries, cancellation.

The property this package exists to guarantee: a job either finishes with a validated artifact or
records honestly why it did not. There is no path where a stage reports success without a file on
disk that parses.
"""

from .jobstore import IllegalTransition, JobRecord, JobStore
from .leases import Lease, LeaseKeeper, LeaseLost
from .runner import StageOutcome, run_stages

__all__ = [
    "IllegalTransition",
    "JobRecord",
    "JobStore",
    "Lease",
    "LeaseKeeper",
    "LeaseLost",
    "StageOutcome",
    "run_stages",
]
