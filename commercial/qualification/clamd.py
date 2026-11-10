"""Explicit real ClamAV daemon with a harmless synthetic test signature only."""
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import os
import socket
import subprocess
import tempfile
import time


class ClamdFixture:
    marker=b'OmniXAT_Fictional_Scanner_Qualification_Marker'
    def __enter__(self):
        self.stack=ExitStack()
        try:
            self.start(); return self
        except BaseException:
            self.stack.close(); raise

    def __exit__(self,*args): self.stack.close()

    def start(self):
        binary=os.environ.get('OMNIXAT_CLAMD_BINARY','/usr/sbin/clamd')
        root=Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='omnixat-clamd-')))
        self.socket_path=root/'clamd.sock'
        database=root/'db'; database.mkdir()
        signature='OmniXAT-Fictional-Marker:0:*:'+self.marker.hex()+'\n'
        (database/'fictional.ndb').write_text(signature)
        config=root/'clamd.conf'
        config.write_text(f'''Foreground yes
LocalSocket {self.socket_path}
LocalSocketMode 600
FixStaleSocket yes
DatabaseDirectory {database}
TemporaryDirectory {root}
PidFile {root/'clamd.pid'}
LogFile {root/'private-clamd.log'}
LogClean no
LogVerbose no
SelfCheck 0
MaxThreads 2
MaxQueue 4
StreamMaxLength 20M
MaxFileSize 20M
MaxScanSize 40M
MaxScanTime 10000
AlertExceedsMax yes
AlertEncrypted yes
ReadTimeout 5
CommandReadTimeout 5
''')
        output=self.stack.enter_context((root/'private-startup.log').open('w+b'))
        environment={k:os.environ[k] for k in ('PATH','LANG','LC_ALL','TZ') if k in os.environ}
        self.process=subprocess.Popen([binary,'--config-file='+str(config)],stdout=output,
                                      stderr=subprocess.STDOUT,env=environment)
        self.stack.callback(self.stop)
        deadline=time.monotonic()+20
        while True:
            if self.process.poll() is not None:
                output.flush()
                # Startup contains only generated test paths; no records/credentials.
                diagnostics=(root/'private-startup.log').read_text(errors='replace').replace(str(root),'<fixture>')
                raise RuntimeError('Disposable ClamAV startup failed: '+diagnostics[-1000:])
            try:
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as channel:
                    channel.settimeout(2); channel.connect(str(self.socket_path)); channel.sendall(b'zVERSION\0')
                    response=bytearray()
                    while True:
                        chunk=channel.recv(1024)
                        if not chunk: break
                        response.extend(chunk)
                        if len(response)>1024: raise RuntimeError('Invalid fixture scanner version')
                if response.startswith(b'ClamAV ') and response.endswith(b'\0'):
                    self.expected_version=response[:-1].decode('ascii'); break
            except OSError:
                pass
            if time.monotonic()>=deadline: raise RuntimeError('Disposable ClamAV readiness timed out')
            time.sleep(0.1)
        # Explicit test trust only. Production config must be operator-qualified.
        self.policy_version='qualification-'+sha256((signature+self.expected_version).encode()).hexdigest()[:24]

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=5)
