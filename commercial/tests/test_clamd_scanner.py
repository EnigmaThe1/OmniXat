import stat
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from omnixat_core.clamd_scanner import ClamdScanner, ScannerUnavailable
from omnixat_core.evidence_intake import MAX_EVIDENCE_BYTES


class Channel:
    def __init__(self,reply):
        self.reply=list(reply); self.sent=[]
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def settimeout(self,value): pass
    def connect(self,path): self.path=path
    def sendall(self,data): self.sent.append(data)
    def recv(self,size): return self.reply.pop(0) if self.reply else b''


class ClamdScannerTests(unittest.TestCase):
    version='ClamAV fictional-qualified'
    def setUp(self):
        self.root=TemporaryDirectory(); self.addCleanup(self.root.cleanup)
        self.scanner=ClamdScanner(self.root.name+'/clamd.sock',expected_version=self.version)

    def invoke(self,reply,*,before=None,after=None,original=b'Fictional original'):
        self.channels=[Channel([before or self.version.encode()+b'\0']),Channel(reply),
                       Channel([after or self.version.encode()+b'\0'])]
        with patch('pathlib.Path.lstat',return_value=SimpleNamespace(st_mode=stat.S_IFSOCK|0o600)), \
             patch('socket.socket',side_effect=self.channels):
            return self.scanner(original,'text/csv')

    def test_clean_chunks_are_network_framed_and_no_path_is_sent(self):
        original=b'x'*70000
        self.assertEqual(self.invoke([b'stream:',b' OK\0'],original=original),'clean')
        self.assertEqual(self.channels[1].sent,[b'zINSTREAM\0',len(original[:65536]).to_bytes(4,'big')+original[:65536],
                                               len(original[65536:]).to_bytes(4,'big')+original[65536:],b'\0\0\0\0'])
        self.assertEqual(self.channels[0].sent,[b'zVERSION\0'])
        self.assertEqual(self.channels[2].sent,[b'zVERSION\0'])

    def test_found_becomes_blocked_without_exposing_signature_text(self):
        self.assertEqual(self.invoke([b'stream: Fictional.TestMarker.UNOFFICIAL FOUND\0']),'blocked')

    def test_error_empty_partial_multirecord_and_oversize_replies_never_clean(self):
        for reply in [[b'stream: ERROR\0'],[],[b'stream: OK'],[b'stream: OK\0extra\0'],
                      [b'x'*4097],[b'unknown: OK\0'],[b'stream: OK\0',b'additional']]:
            with self.subTest(reply_size=sum(map(len,reply))),self.assertRaises(ScannerUnavailable):
                self.invoke(reply)

    def test_before_and_after_version_drift_fail_closed(self):
        for changes in [{'before':b'ClamAV changed\0'},{'after':b'ClamAV changed\0'}]:
            with self.subTest(changes=list(changes)),self.assertRaises(ScannerUnavailable):
                self.invoke([b'stream: OK\0'],**changes)

    def test_socket_failures_are_generic(self):
        with patch('pathlib.Path.lstat',side_effect=OSError('private diagnostic')), \
             self.assertRaisesRegex(ScannerUnavailable,'^Scanner unavailable$'):
            self.scanner(b'Fictional','text/csv')

    def test_total_deadline_covers_all_commands_and_slow_replies(self):
        with patch('time.monotonic',side_effect=[0,100]), \
             patch('pathlib.Path.lstat',return_value=SimpleNamespace(st_mode=stat.S_IFSOCK|0o600)), \
             patch('socket.socket',return_value=Channel([b'stream: OK\0'])), \
             self.assertRaises(ScannerUnavailable):
            self.scanner(b'Fictional','text/csv')

    def test_insecure_or_non_socket_endpoint_is_rejected(self):
        with patch('pathlib.Path.lstat',return_value=SimpleNamespace(st_mode=stat.S_IFREG|0o600)), \
             self.assertRaises(ScannerUnavailable):
            self.scanner(b'Fictional','text/csv')

    def test_invalid_configuration_and_content_reject_before_network(self):
        for config in [{'socket_path':'relative','expected_version':self.version},
                       {'socket_path':self.root.name+'/s','expected_version':'ClamAV x\n'},
                       {'socket_path':self.root.name+'/s','expected_version':self.version,'timeout':float('nan')}]:
            with self.subTest(config=list(config)),self.assertRaises(ValueError): ClamdScanner(**config)
        for value in [b'',None,bytearray(b'x'),b'x'*(MAX_EVIDENCE_BYTES+1)]:
            with self.assertRaises(ValueError): self.scanner(value,'text/csv')
