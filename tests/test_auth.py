import base64
import hashlib
import io
import json
import secrets
import sqlite3
import time
from unittest.mock import patch

import cbor2
import pyotp
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from flask import template_rendered
from webauthn.helpers import bytes_to_base64url as b64
from test_inventory import app, client, part, post


def form(c, url, **data):
    c.get('/login')
    with c.session_transaction() as s:
        token=s['csrf']
    return c.post(url,data={'csrf':token,**data})


def api(c,url,**data):
    with c.session_transaction() as s:
        token=s['csrf']
    return c.post(url,json=data,headers={'X-CSRF-Token':token})


def signin(c,remember=''):
    return form(c,'/login',username='admin',password='test-password-123',remember=remember)


def test_remember_cookie_expiry_revocation(app):
    c=app.test_client()
    response=signin(c,'1')
    assert response.status_code==302
    assert 'Expires=' in response.headers['Set-Cookie']
    assert 'HttpOnly' in response.headers['Set-Cookie'] and 'SameSite=Lax' in response.headers['Set-Cookie']
    with c.session_transaction() as s:
        old=dict(s)
    with sqlite3.connect(app.config['DATABASE']) as db:
        expiry,remember=db.execute('SELECT expires,remember FROM auth_sessions').fetchone()
        assert 29*86400 < expiry-time.time() <= 30*86400 and remember==1
    form(c,'/logout')
    with c.session_transaction() as s:
        s.update(old)
    assert c.get('/account').status_code==302
    response=signin(c)
    assert 'Expires=' not in response.headers['Set-Cookie']
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('UPDATE auth_sessions SET expires=0')
    assert c.get('/account').status_code==302


def test_legacy_username_cookie_not_authenticated(app):
    c=app.test_client()
    with c.session_transaction() as s:
        s['user']='admin'
    assert c.get('/account').status_code==302


def test_security_changes_require_recent_login(client,app):
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('UPDATE auth_sessions SET authenticated=0')
    result=post(client,'/account/totp/start')
    assert result.status_code==302 and '/reauthenticate' in result.location
    assert api(client,'/account/passkey/options').status_code==403


def test_totp_enrollment_login_replay_and_recovery(client,app):
    post(client,'/account/totp/start')
    with sqlite3.connect(app.config['DATABASE']) as db:
        payload=json.loads(db.execute("SELECT payload FROM auth_challenges WHERE purpose='totp_setup'").fetchone()[0])
    cipher=Fernet(base64.urlsafe_b64encode(hashlib.sha256(('totp:'+app.secret_key).encode()).digest()))
    secret=cipher.decrypt(payload['secret'].encode()).decode()
    captured=[]
    def capture(sender,template,context,**extra):
        captured.append(context)
    with template_rendered.connected_to(capture,app):
        result=post(client,'/account/totp/confirm',code=pyotp.TOTP(secret).now())
    assert result.status_code==200
    recovery=captured[0]['codes'][0]
    with client.session_transaction() as s:
        assert secret not in str(dict(s)) and recovery not in str(dict(s))
    c=app.test_client();assert '/auth/verify' in signin(c,'1').location
    assert c.get('/account').status_code==302
    assert form(c,'/auth/verify',code='000000').status_code==200
    assert c.get('/account').status_code==302
    # Enrollment code cannot be replayed as a login factor.
    assert form(c,'/auth/verify',code=pyotp.TOTP(secret).now()).status_code==200
    assert c.get('/account').status_code==302
    assert form(c,'/auth/verify',code=recovery).status_code==302
    assert c.get('/account').status_code==200
    another=app.test_client();signin(another)
    form(another,'/auth/verify',code=recovery)
    assert another.get('/account').status_code==302


def test_email_verification_mfa_and_notifications(client,app):
    app.config.update(SMTP_HOST='smtp.gmail.com',SMTP_USERNAME='sender',SMTP_PASSWORD='test')
    with patch('inventory.auth.send_email') as send:
        assert post(client,'/account/email/send',email='person@example.com').status_code==302
        code=send.call_args.args[2].split(' is ')[1].split('.')[0]
    assert post(client,'/account/email/verify',code='wrong').status_code==400
    assert post(client,'/account/email/verify',code=code).status_code==302
    assert post(client,'/account/email/verify',code=code).status_code==400
    assert post(client,'/account/mfa/email').status_code==200
    c=app.test_client()
    with patch('inventory.auth.send_email') as send:
        assert '/auth/verify' in signin(c).location
        code=send.call_args.args[2].split(' is ')[1].split('.')[0]
    assert c.get('/').status_code==302
    assert form(c,'/auth/verify',code=code).status_code==302
    assert c.get('/account').status_code==200
    assert form(c,'/account/notifications',enabled='1').status_code==302


def test_mfa_attempt_limit_and_json_csrf(client,app):
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE users SET mfa_method='email',email='test@example.com',email_verified=1")
    c=app.test_client()
    with patch('inventory.auth.send_email'):
        signin(c)
    for _ in range(5):
        assert form(c,'/auth/verify',code='wrong').status_code==200
    assert form(c,'/auth/verify',code='wrong').status_code==400
    assert c.post('/auth/passkey/options',json={}).status_code==400


def create_credential(options,origin='https://inventory.test'):
    private=ec.generate_private_key(ec.SECP256R1());public=private.public_key().public_numbers()
    cose={1:2,3:-7,-1:1,-2:public.x.to_bytes(32,'big'),-3:public.y.to_bytes(32,'big')}
    credential_id=secrets.token_bytes(32)
    auth_data=hashlib.sha256(b'inventory.test').digest()+b'\x45'+bytes(4)+bytes(16)+len(credential_id).to_bytes(2,'big')+credential_id+cbor2.dumps(cose)
    client_data=json.dumps({'type':'webauthn.create','challenge':options['challenge'],'origin':origin}).encode()
    credential={'id':b64(credential_id),'rawId':b64(credential_id),'type':'public-key','response':{'clientDataJSON':b64(client_data),'attestationObject':b64(cbor2.dumps({'fmt':'none','authData':auth_data,'attStmt':{}}))}}
    return private,credential


def assertion(private,credential_id,options,origin='https://inventory.test',uv=True):
    client_data=json.dumps({'type':'webauthn.get','challenge':options['challenge'],'origin':origin}).encode()
    auth_data=hashlib.sha256(b'inventory.test').digest()+bytes([5 if uv else 1])+(1).to_bytes(4,'big')
    signature=private.sign(auth_data+hashlib.sha256(client_data).digest(),ec.ECDSA(hashes.SHA256()))
    return {'id':credential_id,'rawId':credential_id,'type':'public-key','response':{'clientDataJSON':b64(client_data),'authenticatorData':b64(auth_data),'signature':b64(signature)}}


def test_passkey_registration_authentication_origin_and_replay(client,app):
    app.config['PUBLIC_URL']='https://inventory.test'
    options=api(client,'/account/passkey/options').json
    private,credential=create_credential(options)
    assert api(client,'/account/passkey/verify',credential=credential,name='Test key').status_code==200
    assert api(client,'/account/passkey/verify',credential=credential).status_code==400
    c=app.test_client();c.get('/login')
    options=api(c,'/auth/passkey/options',remember=True).json
    bad=assertion(private,credential['id'],options,origin='https://evil.test')
    assert api(c,'/auth/passkey/verify',credential=bad).status_code==400
    options=api(c,'/auth/passkey/options').json
    bad=assertion(private,credential['id'],options,uv=False)
    assert api(c,'/auth/passkey/verify',credential=bad).status_code==400
    options=api(c,'/auth/passkey/options',remember=True).json
    good=assertion(private,credential['id'],options)
    assert api(c,'/auth/passkey/verify',credential=good).json['redirect']=='/'
    assert c.get('/account').status_code==200
    assert api(c,'/auth/passkey/verify',credential=good).status_code==400


def test_google_does_not_allow_unlinked_accounts(client,app):
    # The OAuth library validates signature/issuer/audience/nonce; app links only stable subjects.
    from flask import session
    app.config.update(GOOGLE_CLIENT_ID='client',GOOGLE_CLIENT_SECRET='secret',PUBLIC_URL='https://inventory.test')
    google=app.extensions['authlib.integrations.flask_client'].create_client('google')
    with patch.object(google,'authorize_redirect',return_value=app.redirect('/mock-google')):
        assert post(client,'/auth/google').status_code==302
    with patch.object(google,'authorize_access_token',return_value={'userinfo':{'sub':'unknown','email_verified':True,'email':'admin@example.com'}}):
        assert client.get('/auth/google/callback').status_code==400
    with patch.object(google,'authorize_redirect',return_value=app.redirect('/mock-google')):
        post(client,'/account/google/link')
    with patch.object(google,'authorize_access_token',return_value={'userinfo':{'sub':'known','email_verified':True}}):
        assert client.get('/auth/google/callback').status_code==302
    c=app.test_client()
    with patch.object(google,'authorize_redirect',return_value=app.redirect('/mock-google')):
        form(c,'/auth/google',remember='1')
    with patch.object(google,'authorize_access_token',return_value={'userinfo':{'sub':'known','email_verified':True}}):
        assert c.get('/auth/google/callback').status_code==302
        assert c.get('/account').status_code==200


def test_stock_mail_optin_dedup_restock_and_retry(client,app):
    from inventory.mailer import deliver_stock_alerts
    part(client,low_stock='25')
    app.config.update(SMTP_HOST='smtp.gmail.com',SMTP_USERNAME='test',SMTP_PASSWORD='test',PUBLIC_URL='https://inventory.test')
    with app.app_context(), sqlite3.connect(app.config['DATABASE']) as db:
        db.row_factory=sqlite3.Row
        with patch('inventory.mailer.send_email') as send:
            assert deliver_stock_alerts(db)==(0,0)
            db.execute("UPDATE users SET email='person@example.com',email_verified=1,low_stock_email=1");db.commit()
            assert deliver_stock_alerts(db)==(1,0)
            assert deliver_stock_alerts(db)==(0,0)
            assert send.call_count==1
            db.execute('UPDATE components SET stock=50');db.commit()
            deliver_stock_alerts(db)
            db.execute('UPDATE components SET stock=10');db.commit()
            assert deliver_stock_alerts(db)==(1,0)
            db.execute('DELETE FROM stock_alerts');db.commit()
        with patch('inventory.mailer.send_email',side_effect=ValueError('offline')):
            assert deliver_stock_alerts(db)==(0,1)
            assert deliver_stock_alerts(db)==(0,0)


def test_challenges_expire_and_are_bound_to_browser(client,app):
    app.config['PUBLIC_URL']='https://inventory.test'
    options=api(client,'/account/passkey/options').json
    _,credential=create_credential(options)
    other=app.test_client();signin(other)
    assert api(other,'/account/passkey/verify',credential=credential).status_code==400
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('UPDATE auth_challenges SET expires=0')
    assert api(client,'/account/passkey/verify',credential=credential).status_code==400


def test_google_unverified_identity_rejected(client,app):
    app.config.update(GOOGLE_CLIENT_ID='client',GOOGLE_CLIENT_SECRET='secret',PUBLIC_URL='https://inventory.test')
    google=app.extensions['authlib.integrations.flask_client'].create_client('google')
    with patch.object(google,'authorize_redirect',return_value=app.redirect('/mock-google')):
        post(client,'/account/google/link')
    with patch.object(google,'authorize_access_token',return_value={'userinfo':{'sub':'known','email_verified':False}}):
        assert client.get('/auth/google/callback').status_code==400
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT google_sub FROM users').fetchone()[0] is None


def test_remember_cookie_secure_when_https_configured(app):
    app.config['SESSION_COOKIE_SECURE']=True
    c=app.test_client()
    result=signin(c,'1')
    assert '; Secure;' in result.headers['Set-Cookie']


def test_email_transport_uses_tls_and_business_sender(app):
    from inventory.mailer import send_email
    app.config.update(SMTP_HOST='smtp.gmail.com',SMTP_PORT=587,SMTP_USERNAME='owner@example.com',SMTP_PASSWORD='app-password')
    with app.app_context(), patch('inventory.mailer.smtplib.SMTP') as smtp:
        send_email('receiver@example.com','Subject','Body')
        connection=smtp.return_value.__enter__.return_value
        # starttls is called on the original client (the same object for real SMTP).
        smtp.return_value.starttls.assert_called_once()
        smtp.return_value.login.assert_called_once_with('owner@example.com','app-password')
        message=smtp.return_value.send_message.call_args.args[0]
        assert 'no-reply@pcb-studios.com' in message['From']
        assert message['Reply-To']=='support@pcb-studios.com'
