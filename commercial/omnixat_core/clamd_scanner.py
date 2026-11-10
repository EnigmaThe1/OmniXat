"""Bounded INSTREAM client for a server-selected private ClamAV Unix socket."""
import re
import socket
import stat
import time
from pathlib import Path

from .evidence_intake import MAX_EVIDENCE_BYTES


class ScannerUnavailable(Exception):
    """No trustworthy scanner result; never treat transport errors as clean."""


class ClamdScanner:
    def __init__(self, socket_path, *, expected_version, timeout=30):
        self.path = Path(socket_path)
        if not self.path.is_absolute() or len(str(self.path).encode())>100:
            raise ValueError('Explicit short absolute Unix socket path required')
        if (not isinstance(expected_version,str) or not expected_version.startswith('ClamAV ')
                or not 1 <= len(expected_version)<=512 or any(ord(c)<32 or ord(c)>126 for c in expected_version)):
            raise ValueError('Qualified daemon version response required')
        if type(timeout) not in (int,float) or not 0 < timeout <= 60:
            raise ValueError('Bounded scanner timeout required')
        self.expected_version, self.timeout = expected_version, timeout

    def _exchange(self, command, content, deadline):
        # No TCP, arbitrary host, path scan, daemon reload or shell command surface.
        parent, endpoint = self.path.parent.stat(), self.path.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_mode & 0o007 or not stat.S_ISSOCK(endpoint.st_mode):
            raise ScannerUnavailable('Private scanner socket required')
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as channel:
            def budget():
                remaining = deadline-time.monotonic()
                if remaining<=0:
                    raise ScannerUnavailable('Scanner deadline exceeded')
                channel.settimeout(remaining)
            budget(); channel.connect(str(self.path))
            budget(); channel.sendall(b'z'+command+b'\0')
            if content is not None:
                for offset in range(0,len(content),65536):
                    chunk=content[offset:offset+65536]
                    budget(); channel.sendall(len(chunk).to_bytes(4,'big')+chunk)
                budget(); channel.sendall(b'\0\0\0\0')
            reply=bytearray()
            while True:
                budget(); chunk=channel.recv(1024)
                if not chunk:
                    break
                reply.extend(chunk)
                if len(reply)>4096:
                    raise ScannerUnavailable('Scanner reply too large')
            if not reply.endswith(b'\0') or b'\0' in reply[:-1]:
                raise ScannerUnavailable('Invalid scanner reply')
            return bytes(reply[:-1])

    def __call__(self, original, media_type):
        if not isinstance(original,bytes) or not 1<=len(original)<=MAX_EVIDENCE_BYTES:
            raise ValueError('Bounded original bytes required')
        deadline=time.monotonic()+self.timeout
        try:
            before=self._exchange(b'VERSION',None,deadline)
            if before!=self.expected_version.encode('ascii'):
                raise ScannerUnavailable('Scanner policy drift')
            result=self._exchange(b'INSTREAM',original,deadline)
            if self._exchange(b'VERSION',None,deadline)!=before:
                raise ScannerUnavailable('Scanner policy drift')
            if result==b'stream: OK':
                return 'clean'
            if re.fullmatch(rb'stream: [\x20-\x7e]{1,512} FOUND',result):
                return 'blocked'
            raise ScannerUnavailable('Scanner returned no supported decision')
        except (OSError,UnicodeError):
            raise ScannerUnavailable('Scanner unavailable') from None
