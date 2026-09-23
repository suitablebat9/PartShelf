"""Server-validated sessions, account linking, WebAuthn and optional MFA."""
import base64
import hashlib
import hmac
import io
import json
import re
import secrets
import time
from datetime import timedelta
from functools import wraps
from urllib.parse import urlsplit

import pyotp
import qrcode
from authlib.integrations.flask_client import OAuth
from cryptography.fernet import Fernet
from flask import Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash
from webauthn import generate_registration_options, generate_authentication_options, verify_registration_response, verify_authentication_response, options_to_json
from webauthn.helpers import bytes_to_base64url, base64url_to_bytes
from webauthn.helpers.structs import AuthenticatorSelectionCriteria, ResidentKeyRequirement, UserVerificationRequirement, PublicKeyCredentialDescriptor
from .mailer import mail_ready, send_email
from werkzeug.exceptions import Forbidden


class AccountUnavailable(Forbidden):
    def __init__(self, workspace=False):
        super().__init__()
        self.workspace = workspace


def install_auth(app, db):
    bp = Blueprint('auth', __name__)
    cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(('totp:'+app.secret_key).encode()).digest()))
    oauth = OAuth(app)
    google = oauth.register('google', client_id=app.config['GOOGLE_CLIENT_ID'], client_secret=app.config['GOOGLE_CLIENT_SECRET'],
                            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
                            client_kwargs={'scope': 'openid email', 'code_challenge_method': 'S256'})
    def digest(value):
        return hmac.new(app.secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()

    def limit(key, maximum=10, window=900):
        key = digest(key)
        now = int(time.time())
        db().execute('BEGIN IMMEDIATE')
        db().execute('DELETE FROM auth_limits WHERE started<?', (now-86400,))
        row = db().execute('SELECT * FROM auth_limits WHERE key=?', (key,)).fetchone()
        if row and row['started'] > now-window and row['count'] >= maximum:
            db().commit()
            abort(429, 'Too many attempts. Wait a few minutes and try again.')
        if not row or row['started'] <= now-window:
            db().execute('INSERT OR REPLACE INTO auth_limits VALUES(?,?,1)', (key, now))
        else:
            db().execute('UPDATE auth_limits SET count=count+1 WHERE key=?', (key,))
        db().commit()

    def owner():
        if not session.get('challenge_owner'):
            session['challenge_owner'] = secrets.token_urlsafe(32)
        return digest(session['challenge_owner'])

    def challenge(purpose, user_id=None, payload=None, code=None, ttl=600):
        token = secrets.token_urlsafe(32)
        db().execute('DELETE FROM auth_challenges WHERE expires<? OR (owner=? AND purpose=?)', (int(time.time()), owner(), purpose))
        db().execute('INSERT INTO auth_challenges(id,owner,purpose,user_id,payload,code_hash,expires) VALUES(?,?,?,?,?,?,?)',
                     (token, owner(), purpose, user_id, json.dumps(payload or {}), digest(token+':'+code) if code else None, int(time.time())+ttl))
        db().commit()
        session[purpose] = token
        return token

    def get_challenge(purpose):
        row = db().execute('SELECT * FROM auth_challenges WHERE id=? AND owner=? AND purpose=? AND expires>? AND attempts<5',
                           (session.get(purpose, ''), owner(), purpose, int(time.time()))).fetchone()
        if row is None:
            raise ValueError('This verification expired or has too many attempts. Start again.')
        return dict(row, payload=json.loads(row['payload']))

    def consume(purpose, code=None):
        db().execute('BEGIN IMMEDIATE')
        try:
            row = get_challenge(purpose)
            if code is not None:
                db().execute('UPDATE auth_challenges SET attempts=attempts+1 WHERE id=?', (row['id'],))
                if not row['code_hash'] or not hmac.compare_digest(row['code_hash'], digest(row['id']+':'+code.strip())):
                    db().commit()
                    raise ValueError('Incorrect verification code.')
            db().execute('DELETE FROM auth_challenges WHERE id=?', (row['id'],))
            db().commit()
            session.pop(purpose, None)
            return row
        except Exception:
            db().rollback()
            raise

    def user_by_id(user_id):
        user = db().execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        if not user:
            abort(401)
        if not db().execute('SELECT 1 FROM workspaces WHERE id=? AND active=1 AND deleted_at IS NULL', (user['workspace_id'],)).fetchone():
            raise AccountUnavailable(workspace=True)
        if not user['active'] or user['deleted_at']:
            raise AccountUnavailable()
        return user

    def authenticate():
        g.user = g.auth_session = None
        token = session.get('sid')
        if token:
            auth_session = db().execute('SELECT * FROM auth_sessions WHERE token_hash=? AND expires>?', (digest(token), int(time.time()))).fetchone()
            if auth_session:
                candidate = db().execute('SELECT u.* FROM users u JOIN workspaces w ON w.id=u.workspace_id WHERE u.id=? AND u.active=1 AND w.active=1 AND u.deleted_at IS NULL AND w.deleted_at IS NULL', (auth_session['user_id'],)).fetchone()
                if not candidate:
                    session.clear()
                    return
                g.user = candidate
                g.auth_session = auth_session
                session['user'] = g.user['username']
                return
        session.pop('user', None)
        session.pop('sid', None)

    def finish_login(user, remember=False):
        user = user_by_id(user['id'])
        if session.get('sid'):
            db().execute('DELETE FROM auth_sessions WHERE token_hash=?', (digest(session['sid']),))
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        db().execute('DELETE FROM auth_sessions WHERE expires<?', (now,))
        db().execute('INSERT INTO auth_sessions VALUES(?,?,?,?,?)', (digest(token), user['id'], now+(30*86400 if remember else 12*3600), now, int(remember)))
        db().commit()
        session.clear()
        session.update(sid=token, user=user['username'], csrf=secrets.token_hex(32))
        session.permanent = bool(remember)

    def recent(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not g.user:
                return redirect(url_for('login'))
            if not g.auth_session or g.auth_session['authenticated'] < time.time()-600:
                if request.is_json:
                    return jsonify(error='Sign in again from Account settings before changing security settings.'), 403
                flash('Sign in again to change security settings. Your remembered login can stay enabled.')
                return redirect(url_for('auth.reauthenticate'))
            return view(*args, **kwargs)
        return wrapped

    def revoke_others():
        db().execute('DELETE FROM auth_sessions WHERE user_id=? AND token_hash!=?', (g.user['id'], digest(session['sid'])))

    def totp_valid(user, code):
        if not user['totp_secret'] or not re.fullmatch(r'\d{6}', code):
            return False
        totp = pyotp.TOTP(cipher.decrypt(user['totp_secret'].encode()).decode())
        now = int(time.time())//30
        for step in (now, now-1, now+1):
            if step > user['totp_step'] and hmac.compare_digest(totp.at(step*30), code):
                changed = db().execute('UPDATE users SET totp_step=? WHERE id=? AND totp_step<?', (step, user['id'], step)).rowcount
                return changed == 1
        return False

    def recovery_valid(user, code):
        return db().execute('DELETE FROM recovery_codes WHERE user_id=? AND code_hash=?', (user['id'], digest(code.replace('-', '').strip().lower()))).rowcount == 1

    def start_login(user, remember=False, destination='/'):
        user = user_by_id(user['id'])
        if user['mfa_method']:
            payload = dict(remember=bool(remember), destination=destination)
            code = f'{secrets.randbelow(1000000):06d}' if user['mfa_method']=='email' else None
            challenge('mfa_login', user['id'], payload, code)
            if code:
                try:
                    limit('mfa-mail:'+str(user['id']), 5, 900)
                    send_email(user['email'], 'Your Partshelf sign-in code', f'Your sign-in code is {code}. It expires in 10 minutes. If this was not you, ignore this message.')
                except ValueError:
                    flash('Email delivery is unavailable. You can use a saved recovery code below.')
            return redirect(url_for('auth.mfa_login'))
        finish_login(user, remember)
        return redirect(destination)

    def login():
        if request.method=='POST':
            username = request.form.get('username','').strip()
            limit('password:'+username.casefold())
            limit('password-global:'+str(request.remote_addr), 100, 900)
            candidates = db().execute('SELECT * FROM users WHERE username=? COLLATE NOCASE OR email=? COLLATE NOCASE', (username, username)).fetchall()
            # Never pick arbitrarily if a legacy username collides with another account's email.
            user = candidates[0] if len(candidates) == 1 else None
            if user:
                limit('password-account:'+str(user['id']))
            if user and check_password_hash(user['password'], request.form.get('password','')):
                return start_login(user, request.form.get('remember')=='1')
            flash('Incorrect username, email, or password.', 'error')
        return render_template('login.html', google_ready=google_ready(), passkey_ready=passkey_ready())

    def logout():
        if session.get('sid'):
            db().execute('DELETE FROM auth_sessions WHERE token_hash=?', (digest(session['sid']),))
            db().commit()
        session.clear()
        return redirect(url_for('login'))

    def google_ready():
        return bool(app.config['GOOGLE_CLIENT_ID'] and app.config['GOOGLE_CLIENT_SECRET'] and app.config['PUBLIC_URL'].startswith('https://'))

    def passkey_ready():
        return bool(app.config['PUBLIC_URL'].startswith('https://'))

    @bp.route('/auth/verify', methods=['GET','POST'])
    def mfa_login():
        pending = get_challenge('mfa_login')
        user = user_by_id(pending['user_id'])
        if request.method=='POST':
            limit('mfa:'+str(user['id']), 10, 900)
            code = request.form.get('code','').strip()
            db().execute('BEGIN IMMEDIATE')
            pending = get_challenge('mfa_login')
            db().execute('UPDATE auth_challenges SET attempts=attempts+1 WHERE id=?', (pending['id'],))
            valid = recovery_valid(user, code)
            if not valid and user['mfa_method']=='totp':
                valid = totp_valid(user, code)
            if not valid and user['mfa_method']=='email':
                valid = bool(pending['code_hash']) and hmac.compare_digest(pending['code_hash'], digest(pending['id']+':'+code))
            if valid:
                db().execute('DELETE FROM auth_challenges WHERE id=?', (pending['id'],))
                db().commit()
                finish_login(user, pending['payload']['remember'])
                return redirect(pending['payload']['destination'])
            db().commit()
            flash('Incorrect code. Use your verification code or a recovery code.', 'error')
        return render_template('verify.html', method=user['mfa_method'])

    @bp.route('/account/reauthenticate', methods=['GET','POST'])
    def reauthenticate():
        if request.method=='POST':
            limit('reauth:'+str(g.user['id']))
            if check_password_hash(g.user['password'], request.form.get('password','')):
                return start_login(g.user, bool(g.auth_session['remember']), '/account')
            flash('Incorrect password.', 'error')
        return render_template('reauthenticate.html')

    @bp.get('/account')
    def account():
        return render_template('account.html', account=g.user, mail_ready=mail_ready(), google_ready=google_ready(), passkey_ready=passkey_ready(),
                               keys=db().execute('SELECT id,name,created FROM passkeys WHERE user_id=?', (g.user['id'],)).fetchall(),
                               recovery_count=db().execute('SELECT COUNT(*) FROM recovery_codes WHERE user_id=?', (g.user['id'],)).fetchone()[0])

    @bp.post('/account/sessions/revoke')
    @recent
    def revoke_sessions():
        revoke_others();db().commit();flash('Other devices have been signed out.')
        return redirect(url_for('auth.account'))

    @bp.post('/account/email/send')
    @recent
    def email_send():
        limit('verify-mail:'+str(g.user['id']), 5, 900)
        email = request.form.get('email','').strip().lower()
        if not re.fullmatch(r'[^\s@<>\r\n]+@[^\s@<>\r\n]+\.[^\s@<>\r\n]+', email) or len(email)>254:
            raise ValueError('Enter a valid email address.')
        code = f'{secrets.randbelow(1000000):06d}'
        challenge('verify_email', g.user['id'], {'email':email}, code)
        send_email(email, 'Verify your Partshelf email', f'Your email verification code is {code}. It expires in 10 minutes.')
        flash('Verification code sent. Enter it below.')
        return redirect(url_for('auth.account'))

    @bp.post('/account/email/verify')
    @recent
    def email_verify():
        pending = consume('verify_email', request.form.get('code',''))
        if pending['user_id'] != g.user['id']:
            abort(403)
        if db().execute('SELECT 1 FROM users WHERE username=? COLLATE NOCASE AND id!=?', (pending['payload']['email'], g.user['id'])).fetchone():
            raise ValueError('This email conflicts with an existing username. Contact support.')
        db().execute('UPDATE users SET email=?,email_verified=1 WHERE id=?', (pending['payload']['email'],g.user['id']))
        revoke_others();db().commit();flash('Email verified.')
        return redirect(url_for('auth.account'))

    @bp.post('/account/notifications')
    def notifications():
        enabled = request.form.get('enabled')=='1'
        if enabled and (not g.user['email_verified'] or not mail_ready()):
            raise ValueError('Verify your email and configure server email delivery first.')
        db().execute('UPDATE users SET low_stock_email=? WHERE id=?', (int(enabled),g.user['id']))
        if not enabled:
            inventory = app.extensions['inventory_db']()
            inventory.execute('DELETE FROM stock_alerts WHERE user_id=?', (g.user['id'],))
            inventory.commit()
        db().commit();flash('Notification preference saved.')
        return redirect(url_for('auth.account'))

    @bp.post('/account/totp/start')
    @recent
    def totp_start():
        challenge('totp_setup', g.user['id'], {'secret':cipher.encrypt(pyotp.random_base32().encode()).decode()})
        return redirect(url_for('auth.totp_setup'))

    @bp.get('/account/totp/setup')
    @recent
    def totp_setup():
        get_challenge('totp_setup')
        return render_template('totp_setup.html')

    @bp.get('/account/totp/qr')
    @recent
    def totp_qr():
        pending = get_challenge('totp_setup')
        secret = cipher.decrypt(pending['payload']['secret'].encode()).decode()
        uri = pyotp.TOTP(secret).provisioning_uri(name=g.user['username'],issuer_name='PCB Studios Partshelf')
        out=io.BytesIO();qrcode.make(uri).save(out,format='PNG');out.seek(0)
        return send_file(out,mimetype='image/png')

    def enable_mfa(method, secret=None, step=-1):
        codes = [secrets.token_hex(8) for _ in range(10)]
        db().execute('UPDATE users SET mfa_method=?,totp_secret=?,totp_step=? WHERE id=?', (method,secret,step,g.user['id']))
        db().execute('DELETE FROM recovery_codes WHERE user_id=?', (g.user['id'],))
        db().executemany('INSERT INTO recovery_codes VALUES(?,?)', [(g.user['id'],digest(c)) for c in codes])
        revoke_others();db().commit()
        return render_template('recovery_codes.html', codes=codes)

    @bp.post('/account/totp/confirm')
    @recent
    def totp_confirm():
        limit('totp-setup:'+str(g.user['id']), 10, 900)
        pending = get_challenge('totp_setup')
        secret = pending['payload']['secret']
        totp = pyotp.TOTP(cipher.decrypt(secret.encode()).decode())
        code = request.form.get('code','').strip()
        now=int(time.time())//30
        matched=next((step for step in (now,now-1,now+1) if hmac.compare_digest(totp.at(step*30),code)),None)
        if matched is None:
            raise ValueError('Incorrect authenticator code. Return to setup and try again.')
        consume('totp_setup')
        return enable_mfa('totp',secret,matched)

    @bp.post('/account/mfa/email')
    @recent
    def enable_email_mfa():
        if not g.user['email_verified'] or not mail_ready():
            raise ValueError('Verify your email and configure server email delivery first.')
        return enable_mfa('email')

    @bp.post('/account/mfa/disable')
    @recent
    def disable_mfa():
        db().execute("UPDATE users SET mfa_method='',totp_secret=NULL,totp_step=-1 WHERE id=?",(g.user['id'],))
        db().execute('DELETE FROM recovery_codes WHERE user_id=?',(g.user['id'],))
        revoke_others();db().commit();flash('Two-step verification disabled.')
        return redirect(url_for('auth.account'))

    def origin():
        if not passkey_ready():
            raise ValueError('Set the server PUBLIC_URL to the HTTPS address before using passkeys.')
        return app.config['PUBLIC_URL']

    @bp.post('/auth/passkey/options')
    def passkey_options():
        limit('passkey-start:'+str(request.remote_addr),60,900)
        challenge_bytes=secrets.token_bytes(32)
        challenge('passkey_login', payload={'challenge':bytes_to_base64url(challenge_bytes),'remember':bool((request.get_json() or {}).get('remember'))}, ttl=300)
        options=generate_authentication_options(rp_id=urlsplit(origin()).hostname,challenge=challenge_bytes,user_verification=UserVerificationRequirement.REQUIRED)
        return jsonify(json.loads(options_to_json(options)))

    @bp.post('/auth/passkey/verify')
    def passkey_verify():
        limit('passkey-verify:'+str(request.remote_addr),60,900)
        pending=consume('passkey_login')
        credential=(request.get_json() or {}).get('credential',{})
        key=db().execute('SELECT * FROM passkeys WHERE id=?',(credential.get('id',''),)).fetchone()
        if not key:
            raise ValueError('Passkey sign-in failed.')
        try:
            verified=verify_authentication_response(credential=credential,expected_challenge=base64url_to_bytes(pending['payload']['challenge']),
                expected_rp_id=urlsplit(origin()).hostname,expected_origin=origin(),credential_public_key=key['public_key'],credential_current_sign_count=key['sign_count'],require_user_verification=True)
        except Exception:
            raise ValueError('Passkey sign-in failed. Try again from your registered device.') from None
        updated=db().execute('UPDATE passkeys SET sign_count=? WHERE id=? AND sign_count=?',(verified.new_sign_count,key['id'],key['sign_count'])).rowcount
        if updated!=1:
            db().rollback();raise ValueError('Passkey changed during sign-in. Try again.')
        db().commit()
        # Apply optional account MFA consistently to password, Google, and passkey logins.
        response=start_login(user_by_id(key['user_id']), pending['payload']['remember'])
        return jsonify(redirect=response.location)

    @bp.post('/account/passkey/options')
    @recent
    def register_options():
        limit('passkey-register:'+str(g.user['id']),10,900)
        if db().execute('SELECT COUNT(*) FROM passkeys WHERE user_id=?',(g.user['id'],)).fetchone()[0]>=20:
            raise ValueError('Remove an unused passkey before adding another.')
        challenge_bytes=secrets.token_bytes(32)
        challenge('passkey_register',g.user['id'],{'challenge':bytes_to_base64url(challenge_bytes)},ttl=300)
        credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(row['id'])) for row in db().execute('SELECT id FROM passkeys WHERE user_id=?',(g.user['id'],))]
        options=generate_registration_options(rp_id=urlsplit(origin()).hostname,rp_name='PCB Studios Partshelf',user_id=hashlib.sha256(('user:'+str(g.user['id'])+app.secret_key).encode()).digest(),
            user_name=g.user['username'],challenge=challenge_bytes,exclude_credentials=credentials,
            authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.REQUIRED,user_verification=UserVerificationRequirement.REQUIRED))
        return jsonify(json.loads(options_to_json(options)))

    @bp.post('/account/passkey/verify')
    @recent
    def register_verify():
        pending=consume('passkey_register')
        if pending['user_id']!=g.user['id']:
            abort(403)
        data=request.get_json() or {}
        try:
            verified=verify_registration_response(credential=data.get('credential',{}),expected_challenge=base64url_to_bytes(pending['payload']['challenge']),
                expected_rp_id=urlsplit(origin()).hostname,expected_origin=origin(),require_user_verification=True)
        except Exception:
            raise ValueError('Could not verify this passkey. Try enrollment again.') from None
        name=str(data.get('name','Passkey')).strip()[:80] or 'Passkey'
        db().execute('INSERT INTO passkeys VALUES(?,?,?,?,?,?)',(bytes_to_base64url(verified.credential_id),g.user['id'],verified.credential_public_key,verified.sign_count,name,int(time.time())))
        db().commit();return jsonify(redirect='/account')

    @bp.post('/account/passkey/remove')
    @recent
    def passkey_remove():
        db().execute('DELETE FROM passkeys WHERE id=? AND user_id=?',(request.form.get('key_id',''),g.user['id']))
        revoke_others();db().commit();flash('Passkey removed.')
        return redirect(url_for('auth.account'))

    @bp.post('/auth/google')
    def google_login():
        if not google_ready():
            raise ValueError('Google sign-in has not been configured on this server.')
        mode = 'signup' if request.form.get('mode') == 'signup' else 'login'
        if mode == 'signup' and db().execute("SELECT value FROM site_settings WHERE key='registration_enabled'").fetchone()[0] != '1':
            raise ValueError('Public registration is currently closed.')
        limit('google-start:'+str(request.remote_addr), 30, 900)
        challenge('google_flow',payload={'mode':mode,'remember':request.form.get('remember')=='1'})
        return google.authorize_redirect(app.config['PUBLIC_URL']+'/auth/google/callback',prompt='select_account')

    @bp.post('/account/google/link')
    @recent
    def google_link():
        if not google_ready():
            raise ValueError('Google sign-in has not been configured on this server.')
        challenge('google_flow',g.user['id'],{'mode':'link','sid':digest(session['sid'])})
        return google.authorize_redirect(app.config['PUBLIC_URL']+'/auth/google/callback',prompt='select_account')

    @bp.get('/auth/google/callback')
    def google_callback():
        pending=consume('google_flow')
        try:
            token=google.authorize_access_token()
            identity=token['userinfo']
            if not identity.get('sub') or identity.get('email_verified') is not True:
                raise ValueError()
        except Exception:
            raise ValueError('Google sign-in could not be verified. Start again from the sign-in page.') from None
        # Existing accounts must be linked explicitly; never merge by matching email.
        if pending['payload']['mode']=='link':
            if not g.user or pending['user_id']!=g.user['id'] or pending['payload']['sid']!=digest(session.get('sid','')):
                abort(403)
            if g.auth_session['authenticated'] < time.time()-600:
                raise ValueError('Sign in again before linking Google.')
            db().execute('UPDATE users SET google_sub=? WHERE id=?',(identity['sub'],g.user['id']))
            revoke_others();db().commit();flash('Google account linked. You can use it to sign in next time.')
            return redirect(url_for('auth.account'))
        user=db().execute('SELECT * FROM users WHERE google_sub=?',(identity['sub'],)).fetchone()
        if not user and pending['payload']['mode'] == 'signup':
            if db().execute("SELECT value FROM site_settings WHERE key='registration_enabled'").fetchone()[0] != '1':
                raise ValueError('Public registration is currently closed.')
            email = str(identity.get('email', '')).strip().lower()
            if len(email) > 254 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', email):
                raise ValueError('Google did not return a valid verified email.')
            if db().execute('SELECT 1 FROM users WHERE email=? COLLATE NOCASE OR username=? COLLATE NOCASE', (email, email)).fetchone():
                raise ValueError('This email already has an account. Sign in with your password and link Google in Account & security.')
            challenge('google_registration', payload={'email':email, 'sub':identity['sub']})
            return redirect(url_for('manage.google_registration'))
        if not user:
            raise ValueError('This Google account is not linked. Sign in with your existing account, then link Google in Account settings.')
        return start_login(user,pending['payload']['remember'])

    @bp.post('/account/google/unlink')
    @recent
    def google_unlink():
        db().execute('UPDATE users SET google_sub=NULL WHERE id=?',(g.user['id'],))
        revoke_others();db().commit();flash('Google account unlinked.')
        return redirect(url_for('auth.account'))

    app.config.update(PERMANENT_SESSION_LIFETIME=timedelta(days=30),SESSION_REFRESH_EACH_REQUEST=False)
    app.register_blueprint(bp)
    app.extensions['partshelf_auth']={'authenticate':authenticate,'login':login,'logout':logout,'finish_login':finish_login,'digest':digest,'limit':limit,'challenge':challenge,'consume':consume,'get_challenge':get_challenge,'recent':recent}
    return app.extensions['partshelf_auth']
