"""Real Keycloak fixture: generated fictional account, isolated files, loopback TLS.

This is test infrastructure, not a production realm installer or login adapter.
No provider response, authorization code, token, password or client secret is logged.
"""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit
from uuid import uuid4
import base64
import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import tempfile
import time

import httpx
import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from omnixat_core.identity import AccessTokenVerifier

CLIENT = 'omnixat-customer-qualification'
AUDIENCE = 'omnixat-records'
CALLBACK = 'https://workspace.example.test/oauth2/callback'
REALM = 'omnixat-qualification'


def realm_document(subject, password, client_secret):
    """Fictional-only profile for the existing strict access-token verifier."""
    scopes = ['records:read', 'records:write']
    return {
        'realm': REALM, 'enabled': True, 'sslRequired': 'all',
        'registrationAllowed': False, 'resetPasswordAllowed': False,
        'bruteForceProtected': True, 'accessTokenLifespan': 180,
        'revokeRefreshToken': True, 'refreshTokenMaxReuse': 0,
        'clientScopes': [{'name': scope, 'protocol': 'openid-connect',
                          'attributes': {'include.in.token.scope': 'true'}} for scope in scopes],
        'clients': [{
            'clientId': CLIENT, 'enabled': True, 'protocol': 'openid-connect',
            'publicClient': False, 'secret': client_secret,
            'redirectUris': [CALLBACK], 'webOrigins': [],
            'standardFlowEnabled': True, 'implicitFlowEnabled': False,
            'directAccessGrantsEnabled': False, 'serviceAccountsEnabled': False,
            'fullScopeAllowed': False, 'defaultClientScopes': ['records:read'],
            'optionalClientScopes': ['records:write'],
            'attributes': {'pkce.code.challenge.method': 'S256',
                           'access.token.header.type.rfc9068': 'true',
                           'access.token.signed.response.alg': 'RS256'},
            'protocolMappers': [
                {'name': 'explicit-subject', 'protocol': 'openid-connect',
                 'protocolMapper': 'oidc-sub-mapper',
                 'config': {'access.token.claim': 'true', 'introspection.token.claim': 'true'}},
                {'name': 'record-api-audience', 'protocol': 'openid-connect',
                 'protocolMapper': 'oidc-audience-mapper',
                 'config': {'included.custom.audience': AUDIENCE,
                            'access.token.claim': 'true', 'id.token.claim': 'false'}},
                {'name': 'explicit-client-id', 'protocol': 'openid-connect',
                 'protocolMapper': 'oidc-hardcoded-claim-mapper',
                 'config': {'claim.name': 'client_id', 'claim.value': CLIENT,
                            'jsonType.label': 'String', 'access.token.claim': 'true',
                            'id.token.claim': 'false', 'userinfo.token.claim': 'false'}},
            ],
        }],
        'users': [{'id': subject, 'username': 'fictional-editor', 'enabled': True,
                   'email': 'fictional-editor@example.test', 'emailVerified': True,
                   'firstName': 'Fictional', 'lastName': 'Editor', 'requiredActions': [],
                   'credentials': [{'type': 'password', 'value': password, 'temporary': False}]}],
    }


class LoginForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = None
        self.fields = {}
        self.in_form = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form' and attrs.get('id') == 'kc-form-login':
            self.in_form = True
            self.action = attrs.get('action')
        if tag == 'input' and self.in_form and attrs.get('name') and attrs.get('type') == 'hidden':
            self.fields[attrs['name']] = attrs.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form':
            self.in_form = False


class KeycloakFixture:
    """Explicit context manager; no listener or network request on import."""
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
        configured_home = os.environ.get('OMNIXAT_KEYCLOAK_HOME')
        if not configured_home:
            raise RuntimeError('Set OMNIXAT_KEYCLOAK_HOME to a disposable verified installation')
        source = Path(configured_home).resolve()
        if not (source/'bin/kc.sh').is_file():
            raise RuntimeError('A checksum-verified Keycloak 26.8.2 installation is required')
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='omnixat-keycloak-test-')))
        self.subject = str(uuid4())
        self.password = secrets.token_urlsafe(32)
        self.client_secret = secrets.token_urlsafe(32)
        home = root/'keycloak'
        shutil.copytree(source, home)
        imports = home/'data/import'
        imports.mkdir(parents=True, exist_ok=True)
        realm_file = imports/(REALM+'-realm.json')
        realm_file.write_text(json.dumps(realm_document(self.subject, self.password, self.client_secret)))
        realm_file.chmod(0o600)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'OmniXAT fictional loopback test')])
        now = datetime.now(timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                       .public_key(key.public_key()).serial_number(x509.random_serial_number())
                       .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(hours=1))
                       .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip_address('127.0.0.1'))]), critical=False)
                       .sign(key, hashes.SHA256()))
        cert, private = root/'tls.pem', root/'tls-key.pem'
        cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
        private.chmod(0o600)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        self.origin = f'https://127.0.0.1:{port}'
        self.issuer = self.origin+'/realms/'+REALM
        log = self.stack.enter_context((root/'private-startup.log').open('w+b'))
        # Give the provider no ambient DSN, GitHub credential, proxy or JVM hook.
        environment = {name: os.environ[name] for name in ('PATH', 'JAVA_HOME', 'LANG', 'LC_ALL', 'TZ')
                       if name in os.environ}
        environment['JAVA_OPTS_KC_HEAP'] = '-Xms128m -Xmx512m'
        self.process = subprocess.Popen([
            str(home/'bin/kc.sh'), 'start-dev', '--http-enabled=false', '--http-host=127.0.0.1',
            '--https-port='+str(port), '--hostname='+self.origin, '--hostname-strict=true',
            '--https-certificate-file='+str(cert), '--https-certificate-key-file='+str(private),
            '--cache=local', '--import-realm', '--log-level=warn',
        ], stdout=log, stderr=subprocess.STDOUT, env=environment)
        self.stack.callback(self.stop)
        self.tls = ssl.create_default_context(cafile=str(cert))
        with self.client() as client:
            deadline = time.monotonic()+120
            while True:
                if self.process.poll() is not None:
                    raise RuntimeError('Disposable Keycloak exited before readiness')
                try:
                    response = client.get(self.issuer+'/.well-known/openid-configuration')
                    if response.status_code == 200:
                        metadata = response.json()
                        if metadata['issuer'] != self.issuer:
                            raise RuntimeError('Fixture issuer mismatch')
                        break
                except httpx.TransportError:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError('Disposable Keycloak readiness timed out')
                time.sleep(0.2)
            response = client.get(self.issuer+'/protocol/openid-connect/certs')
            response.raise_for_status()
            keys = response.json()['keys']
        # Explicit trust installation only inside this operator-controlled fixture.
        # Production factories never discover or automatically approve these keys.
        self.public_keys = {item['kid']: jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(item))
                            for item in keys if item.get('alg') == 'RS256' and item.get('use') == 'sig'}
        self.verifier = AccessTokenVerifier(issuer=self.issuer, audience=AUDIENCE, public_keys=self.public_keys)

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def client(self):
        return httpx.Client(verify=self.tls, trust_env=False, follow_redirects=False, timeout=5)

    def authorization(self, *, challenge=True, scope='openid records:read records:write'):
        verifier, nonce, state = (secrets.token_urlsafe(32) for _ in range(3))
        params = {'client_id': CLIENT, 'redirect_uri': CALLBACK, 'response_type': 'code',
                  'scope': scope, 'state': state, 'nonce': nonce}
        if challenge:
            params.update(code_challenge=base64.urlsafe_b64encode(sha256(verifier.encode()).digest()).rstrip(b'=').decode(),
                          code_challenge_method='S256')
        with self.client() as client:
            response = client.get(self.issuer+'/protocol/openid-connect/auth', params=params)
            if not challenge:
                return response
            form = LoginForm()
            form.feed(response.text)
            action = urljoin(str(response.url), form.action or '')
            if response.status_code != 200 or not form.action or not action.startswith(self.issuer+'/'):
                raise RuntimeError('Expected a same-realm login form')
            response = client.post(action, data=form.fields | {'username': 'fictional-editor', 'password': self.password})
            for _ in range(10):
                location = response.headers.get('location', '')
                if location.startswith(CALLBACK+'?'):
                    query = parse_qs(urlsplit(location).query)
                    if query.get('state') != [state] or query.get('iss') != [self.issuer] or len(query.get('code', [])) != 1:
                        raise RuntimeError('Authorization response binding failed')
                    return query['code'][0], verifier, nonce
                if response.status_code not in (302, 303) or not location.startswith(self.issuer+'/'):
                    raise RuntimeError('Expected a bounded same-realm authorization redirect')
                response = client.get(location)
        raise RuntimeError('Authorization redirect limit exceeded')

    def exchange(self, code, verifier):
        with self.client() as client:
            return client.post(self.issuer+'/protocol/openid-connect/token', data={
                'grant_type': 'authorization_code', 'client_id': CLIENT, 'client_secret': self.client_secret,
                'redirect_uri': CALLBACK, 'code': code, 'code_verifier': verifier,
            })

    def login(self, *, scope='openid records:read records:write'):
        code, verifier, nonce = self.authorization(scope=scope)
        response = self.exchange(code, verifier)
        if response.status_code != 200:
            raise RuntimeError('Authorization code exchange failed')
        tokens = response.json()
        # ID tokens are validated for the fixture callback only, never accepted by the API.
        kid = jwt.get_unverified_header(tokens['id_token'])['kid']
        identity = jwt.decode(tokens['id_token'], self.public_keys[kid], algorithms=['RS256'],
                              issuer=self.issuer, audience=CLIENT)
        if identity.get('nonce') != nonce or identity.get('sub') != self.subject:
            raise RuntimeError('ID token callback binding failed')
        return tokens
