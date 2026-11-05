from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from omnixat_core.evidence_intake import EvidenceIntakeError, MAX_EVIDENCE_BYTES, stage_evidence


class EvidenceIntakeTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.quarantine = Path(directory.name)

    def stage(self, source, **options):
        defaults = {"media_type": "text/csv", "quarantine_dir": self.quarantine}
        return stage_evidence(source, **(defaults | options))

    def test_partial_reads_preserve_original_and_compute_metadata(self):
        class ShortReads(BytesIO):
            def read(self, size):
                return super().read(min(size, 3))

        original = b"Fictional heading,Example\r\nFictional entry,100\r\n"
        source = ShortReads(original)
        with self.stage(source, expected_size=len(original)) as staged:
            self.assertEqual(staged.content_sha256, sha256(original).hexdigest())
            self.assertEqual(staged.byte_size, len(original))
            self.assertEqual(staged.media_type, "text/csv")
            self.assertEqual(b"".join(iter(lambda: staged.read_for_scan(5), b"")), original)
            self.assertEqual(list(self.quarantine.iterdir()), [])
        self.assertFalse(source.closed)
        with self.assertRaises(ValueError):
            staged.read_for_scan()

    def test_exact_limit_succeeds_and_one_extra_byte_rejects(self):
        class RepeatingStream:
            def __init__(self, size):
                self.remaining = size

            def read(self, size):
                if not 0 < size <= 64 * 1024:
                    raise AssertionError("Unbounded stream read")
                returned = min(size, self.remaining)
                self.remaining -= returned
                return b"x" * returned

        with self.stage(RepeatingStream(MAX_EVIDENCE_BYTES)) as staged:
            self.assertEqual(staged.byte_size, MAX_EVIDENCE_BYTES)
        with self.assertRaises(EvidenceIntakeError), self.stage(RepeatingStream(MAX_EVIDENCE_BYTES + 1)):
            self.fail("Overlimit stream entered quarantine reader")
        self.assertEqual(list(self.quarantine.iterdir()), [])

    def test_bad_length_empty_and_unsupported_media_are_rejected(self):
        for data, options in (
            (b"", {}), (b"two", {"expected_size": 2}),
            (b"one", {"expected_size": 4}), (b"x", {"expected_size": True}),
            (b"x", {"media_type": "text/html"}),
        ):
            with self.subTest(options=options), self.assertRaises(EvidenceIntakeError):
                with self.stage(BytesIO(data), **options):
                    self.fail("Invalid stream entered quarantine reader")

    def test_rejects_nonprivate_directory_and_symlink_before_read(self):
        shared = self.quarantine / "shared"
        shared.mkdir()
        shared.chmod(0o755)
        symlink = self.quarantine / "symlink"
        symlink.symlink_to(self.quarantine, target_is_directory=True)
        for directory in (shared, symlink):
            source = BytesIO(b"fixture")
            with self.subTest(directory=directory.name), self.assertRaises(EvidenceIntakeError):
                with self.stage(source, quarantine_dir=directory):
                    self.fail("Unsafe directory used")
            self.assertEqual(source.tell(), 0)

    def test_source_error_and_consumer_error_leave_no_staged_file(self):
        class BrokenStream(BytesIO):
            def read(self, size):
                if self.tell():
                    raise OSError("fictional interrupted stream")
                return super().read(size)

        with self.assertRaises(OSError), self.stage(BrokenStream(b"fictional partial body")):
            self.fail("Interrupted stream entered quarantine reader")
        with self.assertRaises(RuntimeError):
            with self.stage(BytesIO(b"fictional body")) as staged:
                raise RuntimeError("fictional scanner outage")
        self.assertEqual(list(self.quarantine.iterdir()), [])
        with self.assertRaises(ValueError):
            staged.read_for_scan()

    def test_invalid_reader_output_never_reaches_scan(self):
        class InvalidReader:
            def __init__(self, result):
                self.result = result

            def read(self, size):
                return self.result

        for result in ("not bytes", None, b"x" * 65537):
            with self.subTest(result_type=type(result)), self.assertRaises(EvidenceIntakeError):
                with self.stage(InvalidReader(result)):
                    self.fail("Invalid reader output entered quarantine")
        self.assertEqual(list(self.quarantine.iterdir()), [])
