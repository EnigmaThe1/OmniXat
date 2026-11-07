"""One explicit bounded evidence-inspection step. No scheduler or external work."""
from dataclasses import asdict, dataclass
from uuid import UUID

from .evidence_extraction_postgres import EvidenceNotEligible, read_evidence_for_extraction


@dataclass(frozen=True)
class EvidenceInspection:
    job_id: str
    organisation_id: str
    evidence_id: str
    content_sha256: str
    policy_version: str
    media_type: str
    byte_size: int


def inspect_preparation_evidence(jobs, gate_connection, access_token, tenant, job_id, lease_token) -> EvidenceInspection:
    """Observe one admitted source and conditionally save metadata-only progress.

    `jobs` is the server's AuthenticatedJobStore. Original bytes stay inside trusted
    code; this observation is not continuing eligibility or job completion.
    """
    claimed = jobs.get_claimed_evidence_task(access_token, tenant, job_id, lease_token)
    previous, task = claimed.checkpoint, claimed.task
    if previous and (set(previous) != {"step", "inspection"} or previous.get("step") != "evidence_inspected"):
        raise ValueError("Inspection cannot replace another preparation step")
    admitted = read_evidence_for_extraction(gate_connection, tenant, task.organisation_id, task.evidence_id)
    if admitted.evidence_id != task.evidence_id or admitted.content_sha256 != task.content_sha256.hex():
        raise EvidenceNotEligible("Evidence does not match the pinned task source")
    result = EvidenceInspection(str(UUID(str(job_id))), str(task.organisation_id), str(task.evidence_id),
                                admitted.content_sha256, admitted.policy_version, admitted.media_type,
                                len(admitted.original_bytes))
    # Each service call resolves fresh identity. The checkpoint also rechecks the
    # live worker/token/lease under lock and rejects newer saved progress.
    jobs.checkpoint(access_token, tenant, job_id, lease_token,
                    {"step": "evidence_inspected", "inspection": asdict(result)}, expected_progress=previous)
    return result
