import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from omnixat_core.private_config import private_file


class PrivateConfigTests(unittest.TestCase):
    def setUp(self):
        self.root = TemporaryDirectory(); self.addCleanup(self.root.cleanup)
        self.path = Path(self.root.name)/'fictional-config'
        self.path.write_bytes(b' fictional configuration\n'); self.path.chmod(0o600)

    def test_private_regular_file_and_exact_size_limit(self):
        self.assertEqual(private_file(self.path),'fictional configuration')
        self.path.write_bytes(b'x'*65536)
        self.assertEqual(len(private_file(self.path)),65536)
        self.path.write_bytes(b'x'*65537)
        with self.assertRaises(ValueError): private_file(self.path)

    def test_empty_whitespace_and_invalid_encoding(self):
        for content in [b'',b' \n\t',b'\xff']:
            self.path.write_bytes(content)
            with self.assertRaises(ValueError): private_file(self.path)

    def test_symlink_is_never_followed(self):
        link = self.path.with_name('link'); link.symlink_to(self.path)
        with self.assertRaises(OSError): private_file(link)

    def test_fifo_and_directory_are_rejected_without_blocking(self):
        fifo = self.path.with_name('fifo'); os.mkfifo(fifo,0o600)
        for path in [fifo,self.path.parent]:
            with self.assertRaises(ValueError): private_file(path)

    def test_opened_file_permissions_and_owner_are_required(self):
        self.path.chmod(0o640)
        with self.assertRaises(ValueError): private_file(self.path)
        self.path.chmod(0o600)
        with patch('omnixat_core.private_config.os.geteuid',return_value=os.geteuid()+1):
            with self.assertRaises(ValueError): private_file(self.path)

    def test_path_replacement_cannot_redirect_read(self):
        original_open = os.open
        replacement = self.path.with_name('replacement')
        replacement.write_text('different configuration'); replacement.chmod(0o600)
        def swap(path,flags):
            descriptor = original_open(path,flags)
            os.replace(replacement,path)
            return descriptor
        with patch('omnixat_core.private_config.os.open',side_effect=swap):
            self.assertEqual(private_file(self.path),'fictional configuration')

    def test_descriptor_closed_on_decode_failure(self):
        original_open = os.open; opened=[]
        def capture(path,flags):
            descriptor=original_open(path,flags); opened.append(descriptor); return descriptor
        self.path.write_bytes(b'\xff')
        with patch('omnixat_core.private_config.os.open',side_effect=capture):
            with self.assertRaises(ValueError): private_file(self.path)
        with self.assertRaises(OSError): os.fstat(opened[0])
