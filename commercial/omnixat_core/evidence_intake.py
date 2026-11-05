"""Bounded local staging for evidence; no object is released for extraction."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
import os
from pathlib import Path
from stat import S_IMODE, S_ISDIR
from tempfile import TemporaryFile
from typing import BinaryIO, Iterator

MAX_EVIDENCE_BYTES = 20 * 1024 * 1024
EVIDENCE_MEDIA_TYPES = ("application/pdf", "image/jpeg", "image/png", "text/csv")
_CHUNK_BYTES = 64 * 1024


class EvidenceIntakeError(ValueError):
    """The stream does not meet the local staging contract."""


@dataclass(frozen=True)
class QuarantinedEvidence:
    content_sha256: str
    media_type: str
    byte_size: int
    _file: BinaryIO = field(repr=False, compare=False)

    def read_for_scan(self, size: int = _CHUNK_BYTES) -> bytes:
        """Read the next chunk inside the staging context, for trusted scanner code."""
        if type(size) is not int or not 1 <= size <= _CHUNK_BYTES:
            raise ValueError("Invalid quarantine read size")
        return self._file.read(size)


@contextmanager
def stage_evidence(
    source: BinaryIO,
    *,
    media_type: str,
    quarantine_dir: Path,
    expected_size: int | None = None,
) -> Iterator[QuarantinedEvidence]:
    """Stage a blocking binary stream in an operator-controlled private directory.

    The caller owns the input and must bound its read time. The temporary file
    belongs to this context and is never published, even after successful staging.
    """
    if media_type not in EVIDENCE_MEDIA_TYPES:
        raise EvidenceIntakeError("Unsupported evidence media type")
    if expected_size is not None and (
        type(expected_size) is not int or not 1 <= expected_size <= MAX_EVIDENCE_BYTES
    ):
        raise EvidenceIntakeError("Evidence size outside intake limit")

    if os.name != "posix":
        raise EvidenceIntakeError("Local quarantine requires POSIX temporary files")
    directory = Path(quarantine_dir)
    metadata = directory.lstat()
    if not S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid() or S_IMODE(metadata.st_mode) & 0o077:
        raise EvidenceIntakeError("Quarantine directory must be private and owned by the service user")

    limit = MAX_EVIDENCE_BYTES if expected_size is None else expected_size
    digest = sha256()
    total = 0
    with TemporaryFile(mode="w+b", dir=directory) as staged:
        while True:
            # Read at most one byte beyond the limit to distinguish EOF from overflow.
            requested = min(_CHUNK_BYTES, limit - total + 1)
            chunk = source.read(requested)
            if not isinstance(chunk, bytes) or len(chunk) > requested:
                raise EvidenceIntakeError("Invalid evidence stream")
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise EvidenceIntakeError("Evidence exceeds intake size")
            if staged.write(chunk) != len(chunk):
                raise OSError("Incomplete quarantine write")
            digest.update(chunk)
        if total == 0 or (expected_size is not None and total != expected_size):
            raise EvidenceIntakeError("Incomplete or empty evidence")

        staged.seek(0)
        yield QuarantinedEvidence(digest.hexdigest(), media_type, total, staged)
