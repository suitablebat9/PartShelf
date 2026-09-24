import json
import sqlite3
from unittest.mock import patch
from test_inventory import app, client, post, part
from test_community_projects import make_admin
from test_auth import form


def expire_freshness(app):
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('UPDATE auth_sessions SET authenticated=0')


def test_password_reauthentication_returns_to_requested_page(app,client):
    make_admin(app)
    expire_freshness(app)
    response=client.get('/management/site')
    assert response.location.endswith('/account/reauthenticate')
    response=post(client,'/account/reauthenticate',password='test-password-123')
    assert response.location=='/management/site'
    assert client.get(response.location).status_code==200


def test_google_reauthentication_preserves_destination_and_identity(app,client):
    make_admin(app)
    app.config.update(GOOGLE_CLIENT_ID='test',GOOGLE_CLIENT_SECRET='test',PUBLIC_URL='https://partshelf.example')
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE users SET google_sub='owner',email='owner@gmail.com',email_verified=1 WHERE id=1")
    expire_freshness(app)
    client.get('/management/site')
    google=app.extensions['authlib.integrations.flask_client'].create_client('google')
    for sub,expected in [('wrong',400),('owner',302)]:
        with patch.object(google,'authorize_redirect',return_value=app.redirect('/mock-google')):
            assert post(client,'/account/google/reauthenticate').status_code==302
        with patch.object(google,'authorize_access_token',return_value={'userinfo':{'sub':sub,'email':'owner@gmail.com','email_verified':True}}):
            response=client.get('/auth/google/callback')
        assert response.status_code==expected
    assert response.location=='/management/site'


def test_reauthentication_destination_survives_mfa(app,client):
    make_admin(app)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE users SET mfa_method='email',email='owner@example.com' WHERE id=1")
    expire_freshness(app)
    client.get('/management/site')
    with patch('inventory.auth.send_email'):
        result=post(client,'/account/reauthenticate',password='test-password-123')
    assert result.location=='/auth/verify'
    with sqlite3.connect(app.config['DATABASE']) as db:
        payload=json.loads(db.execute("SELECT payload FROM auth_challenges WHERE purpose='mfa_login'").fetchone()[0])
    assert payload['destination']=='/management/site'


def test_signin_destination_and_external_redirect_rejection(app,client):
    c=app.test_client()
    c.get('/projects')
    c.get('/login')
    assert form(c,'/login',username='admin',password='test-password-123').location=='/projects'
    for path in ['https://evil.test','//evil.test','/\\evil.test','/\nevil.test']:
        with c.session_transaction() as state:
            state['reauth_destination']=path
        assert form(c,'/account/reauthenticate',password='test-password-123').location=='/account'


def test_settings_public_session_and_removed_editors(app,client):
    make_admin(app)
    page=client.get('/settings')
    assert page.status_code==200 and b'Public site settings' in page.data
    sidebar=client.get('/').data.split(b'<nav aria-label="Sidebar">',1)[1].split(b'</nav>',1)[0]
    assert b'/account' not in sidebar and b'/management/site' not in sidebar
    for path in ['/support','/feedback']:
        page=client.get(path)
        assert b'aria-label="Sidebar"' in page.data and b'href="/login"' not in page.data
        assert b'Sign in' in app.test_client().get(path).data
    for path in ['/management/pages','/management/templates']:
        assert client.get(path).status_code==404
    # Old saved overrides are never executed or displayed after removal.
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('CREATE TABLE IF NOT EXISTS public_html(page TEXT PRIMARY KEY, html TEXT, revision INTEGER)')
        db.execute("INSERT OR REPLACE INTO public_html VALUES('welcome','obsolete override',1)")
    assert b'obsolete override' not in client.get('/welcome').data


def test_editable_promise_and_label_guide(app,client):
    assert post(client,'/management/site',no_paywall='Changed promise').status_code==403
    make_admin(app)
    assert post(client,'/management/site',no_paywall='Every feature stays free. <b>Thanks!</b>').status_code==302
    for path in ['/welcome','/support','/about']:
        assert b'Every feature stays free. &lt;b&gt;Thanks!&lt;/b&gt;' in app.test_client().get(path).data
    part(client)
    labels=client.get('/labels')
    assert b'/labels/help' in labels.data and b'Use {name}' not in labels.data
    assert client.get('/labels/help').status_code==200
    assert b'{name_id}' in client.get('/labels/help').data
