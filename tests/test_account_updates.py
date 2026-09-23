import re
import sqlite3
from unittest.mock import patch

from test_inventory import app, client, post, part
from test_auth import form
from test_workspaces import tenant, make_platform, authenticated
from werkzeug.security import generate_password_hash


def test_login_with_username_or_email_case_insensitive(app):
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE users SET email='owner@example.com',email_verified=1 WHERE id=1")
    for identifier in ('admin', 'ADMIN', 'owner@example.com', 'OWNER@EXAMPLE.COM'):
        c = app.test_client()
        assert form(c, '/login', username=identifier, password='test-password-123').status_code == 302
        assert c.get('/account').status_code == 200
    c = app.test_client()
    assert b'Incorrect username, email, or password.' in form(c, '/login', username='owner@example.com', password='wrong').data
    assert c.get('/account').status_code == 302


def test_ambiguous_legacy_username_email_fails_closed(app):
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE users SET email='other@example.com' WHERE id=1")
        db.execute('INSERT INTO users(username,password) VALUES(?,?)', ('other@example.com', generate_password_hash('other-password')))
    c = app.test_client()
    assert form(c, '/login', username='other@example.com', password='test-password-123').status_code == 200
    assert c.get('/account').status_code == 302


def test_auth_pages_have_no_sidebar_even_when_already_signed_in(client, app):
    assert b'<aside' not in app.test_client().get('/login').data
    assert b'<aside' not in client.get('/login').data
    assert b'<aside' not in app.test_client().get('/register').data
    assert b'<aside' in client.get('/').data


def test_missing_email_cannot_register(app):
    app.config.update(PUBLIC_URL='https://inventory.example.com',SMTP_HOST='smtp.test',SMTP_USERNAME='sender',SMTP_PASSWORD='test')
    c = app.test_client()
    with patch('inventory.management.send_email') as send:
        response = form(c, '/register', workspace_name='Client', username='new', password='password', password_confirm='password')
        assert response.status_code == 400
        send.assert_not_called()
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 1


def test_suspended_workspace_has_support_page_after_valid_login(app):
    wid, uid, c = tenant(app)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('UPDATE workspaces SET active=0 WHERE id=?', (wid,))
    c = app.test_client()
    result = form(c, '/login', username='Client A', password='password-123')
    assert result.status_code == 403
    assert b'Workspace suspended' in result.data
    assert b'mailto:support@pcb-studios.com' in result.data
    assert b'<aside' not in result.data
    wrong = form(c, '/login', username='Client A', password='wrong')
    assert b'Workspace suspended' not in wrong.data


def test_workspace_trash_restore_keeps_data_and_revokes_access(app, client):
    make_platform(app)
    wid, uid, owner = tenant(app)
    part(owner, name='Keep me')
    assert post(owner, f'/management/workspaces/{wid}/delete', confirm_name='Client A').status_code == 403
    assert post(client, f'/management/workspaces/{wid}/delete', confirm_name='wrong').status_code == 400
    assert post(client, '/management/workspaces/1/delete', confirm_name='PCB Studios').status_code == 400
    assert post(client, f'/management/workspaces/{wid}/delete', confirm_name='Client A').status_code == 302
    assert owner.get('/').status_code == 302
    assert client.get(f'/management/workspaces/{wid}').status_code == 404
    assert post(client, f'/management/workspaces/{wid}/status', active='1').status_code == 404
    assert b'Workspace Trash' in client.get('/management').data
    assert post(client, f'/management/workspaces/{wid}/restore').status_code == 302
    owner = authenticated(app, uid, 'restored-session')
    assert b'Keep me' in owner.get('/').data


def test_user_trash_guards_and_restore(app, client):
    make_platform(app)
    wid, ownerid, owner = tenant(app)
    with sqlite3.connect(app.config['DATABASE']) as db:
        uid = db.execute("INSERT INTO users(username,password,workspace_id,role) VALUES(?,?,?,'member')", ('staff',generate_password_hash('password-123'),wid)).lastrowid
    staff = authenticated(app, uid, 'staff-deletable')
    assert post(owner, f'/management/workspaces/{wid}/members/{uid}/delete', confirm_name='staff').status_code == 403
    assert post(client, f'/management/workspaces/{wid}/members/{ownerid}/delete', confirm_name='Client A').status_code == 400
    assert post(client, f'/management/workspaces/1/members/{uid}/delete', confirm_name='staff').status_code == 404
    assert post(client, f'/management/workspaces/{wid}/members/{uid}/delete', confirm_name='staff').status_code == 302
    assert staff.get('/').status_code == 302
    assert b'User Trash' in client.get(f'/management/workspaces/{wid}').data
    assert post(client, f'/management/workspaces/{wid}/members/{uid}', role='owner', active='1').status_code == 404
    assert post(client, f'/management/workspaces/{wid}/members/{uid}/restore').status_code == 302
    assert staff.get('/').status_code == 302  # cannot reuse old session


def google_flow(app, c, identity):
    app.config.update(GOOGLE_CLIENT_ID='client',GOOGLE_CLIENT_SECRET='secret',PUBLIC_URL='https://inventory.example.com')
    google = app.extensions['authlib.integrations.flask_client'].create_client('google')
    with patch.object(google, 'authorize_redirect', return_value=app.redirect('/mock-google')):
        assert form(c, '/auth/google', mode='signup').status_code == 302
    with patch.object(google, 'authorize_access_token', return_value={'userinfo':identity}):
        return c.get('/auth/google/callback')


def test_verified_google_signup_creates_workspace_and_session(app):
    c = app.test_client()
    response = google_flow(app, c, {'sub':'new-google','email':'new@gmail.com','email_verified':True})
    assert response.location.endswith('/')
    assert c.get('/account').status_code == 200
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute("SELECT email,email_verified,google_sub,platform_admin,workspace_id,password FROM users WHERE email='new@gmail.com'").fetchone() == ('new@gmail.com',1,'new-google',0,2,'')
        assert db.execute('SELECT COUNT(*) FROM workspaces').fetchone()[0] == 2
    assert google_flow(app,c,{'sub':'new-google','email':'new@gmail.com','email_verified':True}).status_code == 302
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT COUNT(*) FROM workspaces').fetchone()[0] == 2
    assert form(c,'/account/google/unlink').status_code == 400


def test_google_link_verified_email_keeps_workspace_and_mfa(app):
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE users SET email='existing@gmail.com',email_verified=1,mfa_method='totp' WHERE id=1")
    c=app.test_client()
    response=google_flow(app,c,{'sub':'auto-linked','email':'EXISTING@gmail.com','email_verified':True})
    assert response.location.endswith('/auth/verify')
    assert c.get('/').status_code == 302
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT google_sub,workspace_id FROM users WHERE id=1').fetchone()==('auto-linked',1)
        assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0]==1


def test_google_link_rejects_unverified_collisions_and_non_hosted_emails(app):
    for email,verified,sub,identity in [
        ('existing@gmail.com',0,None,{'sub':'unknown','email':'existing@gmail.com','email_verified':True}),
        ('existing@gmail.com',1,'different',{'sub':'unknown','email':'existing@gmail.com','email_verified':True}),
        ('existing@example.com',1,None,{'sub':'unknown','email':'existing@example.com','email_verified':True}),
    ]:
        with sqlite3.connect(app.config['DATABASE']) as db:
            db.execute('UPDATE users SET email=?,email_verified=?,google_sub=? WHERE id=1',(email,verified,sub))
        assert google_flow(app,app.test_client(),identity).status_code==400
    assert google_flow(app,app.test_client(),{'sub':'unknown','email':'existing@example.com','email_verified':True,'hd':'example.com'}).status_code==302
    assert google_flow(app,app.test_client(),{'sub':'bad','email':'new@gmail.com','email_verified':False}).status_code==400


def test_google_respects_closed_registration_and_suspension(app):
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE users SET email='existing@gmail.com',email_verified=1 WHERE id=1")
        db.execute("UPDATE site_settings SET value='0' WHERE key='registration_enabled'")
    assert google_flow(app,app.test_client(),{'sub':'new','email':'new@gmail.com','email_verified':True}).status_code==400
    assert google_flow(app,app.test_client(),{'sub':'existing','email':'existing@gmail.com','email_verified':True}).status_code==302
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('UPDATE workspaces SET active=0 WHERE id=1')
    assert google_flow(app,app.test_client(),{'sub':'existing','email':'existing@gmail.com','email_verified':True}).status_code==403


def test_sender_envelope_does_not_use_smtp_username(app):
    from inventory.mailer import send_email
    app.config.update(SMTP_HOST='smtp.gmail.com',SMTP_PORT=587,SMTP_USERNAME='primary@example.com',SMTP_PASSWORD='test')
    with app.app_context(), patch('inventory.mailer.smtplib.SMTP') as smtp:
        send_email('recipient@example.com','Subject','Body')
        kwargs = smtp.return_value.send_message.call_args.kwargs
        assert kwargs == {'from_addr':'no-reply@pcb-studios.com','to_addrs':['recipient@example.com']}
        assert 'PCB Studios' in smtp.return_value.send_message.call_args.args[0]['From']

def test_google_only_account_reauth_and_wrong_identity(app):
    c=app.test_client()
    google_flow(app,c,{'sub':'owner-sub','email':'owner@gmail.com','email_verified':True})
    google=app.extensions['authlib.integrations.flask_client'].create_client('google')
    for subject,expected in (('different',400),('owner-sub',302)):
        with patch.object(google,'authorize_redirect',return_value=app.redirect('/mock-google')):
            assert form(c,'/account/google/reauthenticate').status_code==302
        with patch.object(google,'authorize_access_token',return_value={'userinfo':{'sub':subject,'email':'owner@gmail.com','email_verified':True}}):
            response=c.get('/auth/google/callback')
            assert response.status_code==expected
            if expected==302:
                assert response.location.endswith('/account')


def test_google_username_collision_and_capacity(app,monkeypatch):
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE users SET username='new' WHERE id=1")
    assert google_flow(app,app.test_client(),{'sub':'new','email':'new@gmail.com','email_verified':True}).status_code==302
    with sqlite3.connect(app.config['DATABASE']) as db:
        username=db.execute("SELECT username FROM users WHERE google_sub='new'").fetchone()[0]
        assert username!='new' and username.startswith('new-')
    monkeypatch.setenv('MAX_WORKSPACES','2')
    assert google_flow(app,app.test_client(),{'sub':'other','email':'other@gmail.com','email_verified':True}).status_code==400
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT COUNT(*) FROM workspaces').fetchone()[0]==2
