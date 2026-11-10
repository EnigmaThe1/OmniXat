"""Explicit loopback OAuth2 Proxy/ASGI fixture. No services start on import."""
from contextlib import ExitStack
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
from threading import Thread
import time
import tomllib

import httpx
import uvicorn

from qualification.keycloak_customer import CALLBACK, CLIENT


def loopback_socket():
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    return listener


class CustomerGateway:
    def __init__(self, app, provider):
        self.app, self.provider = app, provider
        # Only digests and verified metadata, never raw tokens, leave the observer.
        self.observed = []

    def __enter__(self):
        self.stack = ExitStack()
        try:
            self.start()
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *args):
        self.stack.close()

    def start(self):
        binary = Path(os.environ['OMNIXAT_OAUTH2_PROXY_BINARY']).resolve()
        version = subprocess.run([str(binary), '--version'], capture_output=True, text=True, check=True)
        if not version.stdout.startswith('oauth2-proxy v7.15.6 '):
            raise RuntimeError('Checksum-pinned OAuth2 Proxy 7.15.6 required')
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='omnixat-gateway-test-')))
        async def observed_app(scope, receive, send):
            if scope['type'] == 'http' and scope['path'].startswith('/v1/'):
                tokens = [v.decode() for k,v in scope['headers'] if k.lower()==b'x-forwarded-access-token']
                if len(tokens)==1:
                    verified = self.provider.verifier.verify(tokens[0])
                    self.observed.append((sha256(tokens[0].encode()).digest(), verified.issued_at, verified.subject))
            await self.app(scope, receive, send)
        listener = self.stack.enter_context(loopback_socket())
        port = listener.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(observed_app, access_log=False, log_level='critical',
                                                   lifespan='off', proxy_headers=False))
        thread = Thread(target=self.server.run, kwargs={'sockets':[listener]}, daemon=True)
        thread.start()
        def stop_app():
            self.server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError('Qualification ASGI server failed to stop')
        self.stack.callback(stop_app)
        deadline = time.monotonic()+10
        while not self.server.started:
            if not thread.is_alive() or time.monotonic()>=deadline:
                raise RuntimeError('Qualification ASGI readiness failed')
            time.sleep(0.05)
        with loopback_socket() as reservation:
            self.port = reservation.getsockname()[1]
        self.origin = 'https://workspace.example.test'
        self.network_origin = f'https://127.0.0.1:{self.port}'
        client_secret, cookie_secret = root/'client.secret', root/'cookie.secret'
        client_secret.write_text(self.provider.client_secret)
        cookie_secret.write_bytes(secrets.token_bytes(32))
        client_secret.chmod(0o600); cookie_secret.chmod(0o600)
        template = Path(__file__).resolve().parents[1]/'config/oauth2-proxy.customer.example.cfg'
        settings = tomllib.loads(template.read_text())
        # Environment bindings plus accelerated refresh; all template auth flags retained.
        settings.update(client_id=CLIENT, oidc_issuer_url=self.provider.issuer, redirect_url=CALLBACK,
            upstreams=[f'http://127.0.0.1:{port}/'], email_domains=['example.test'],
            client_secret_file=str(client_secret), cookie_secret_file=str(cookie_secret),
            cookie_refresh='5s', provider_ca_files=[str(self.provider.certificate_file)],
            https_address=f'127.0.0.1:{self.port}', http_address='127.0.0.1:0',
            tls_cert_file=str(self.provider.certificate_file), tls_key_file=str(self.provider.private_key_file),
            auth_logging=False, standard_logging=False)
        config = root/'gateway.cfg'
        config.write_text('\n'.join(f'{key} = {json.dumps(value)}' for key,value in settings.items()))
        config.chmod(0o600)
        log = self.stack.enter_context((root/'private-gateway.log').open('w+b'))
        environment = {key:os.environ[key] for key in ('PATH','LANG','LC_ALL','TZ') if key in os.environ}
        self.process = subprocess.Popen([str(binary),'--config='+str(config)], stdout=log,
                                        stderr=subprocess.STDOUT, env=environment)
        self.stack.callback(self.stop_proxy)
        with self.client() as client:
            deadline = time.monotonic()+20
            while True:
                if self.process.poll() is not None:
                    raise RuntimeError('Qualification gateway exited before readiness')
                try:
                    if client.get('/ping').status_code==200:
                        break
                except httpx.TransportError:
                    pass
                if time.monotonic()>=deadline:
                    raise RuntimeError('Qualification gateway readiness timed out')
                time.sleep(0.1)

    def stop_proxy(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=5)

    def client(self):
        return httpx.Client(base_url=self.network_origin, verify=self.provider.tls,
                            headers={'Host':'workspace.example.test'}, trust_env=False, timeout=5)
