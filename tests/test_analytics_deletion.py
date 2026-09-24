import sqlite3
from unittest.mock import patch
from test_inventory import app, client, part, post
from test_workspaces import tenant, make_platform, authenticated
from test_account_updates import google_flow
from test_auth import form


def test_self_delete_member_revokes_sessions_and_keeps_team(app):
    wid,uid,owner=tenant(app)
    with sqlite3.connect(app.config['DATABASE']) as db:
        mid=db.execute("INSERT INTO users(username,password,workspace_id,role) VALUES('member','hash',?,'member')",(wid,)).lastrowid
    member=authenticated(app,mid,'member-session')
    other=authenticated(app,mid,'other-device')
    assert post(member,'/account/delete',confirm_name='wrong').status_code==400
    assert post(member,'/account/delete',confirm_name='member').status_code==302
    assert other.get('/').status_code==302
    assert owner.get('/').status_code==200
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT active,deleted_at IS NOT NULL FROM users WHERE id=?',(mid,)).fetchone()==(0,1)
        assert db.execute('SELECT COUNT(*) FROM auth_sessions WHERE user_id=?',(mid,)).fetchone()[0]==0


def test_owner_deletion_guards_and_workspace_delete(app,client):
    make_platform(app)
    wid,uid,owner=tenant(app)
    otherwid,otheruid,other=tenant(app,'Other')
    part(owner,name='Retained inventory')
    assert post(owner,'/account/delete',confirm_name='Client A').status_code==400
    assert post(client,'/account/delete',confirm_name='admin').status_code==400
    assert post(client,'/workspace/delete',confirm_name='PCB Studios').status_code==400
    assert post(owner,'/workspace/delete',confirm_name='Other').status_code==400
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("INSERT INTO invitations VALUES('pending',?,'staff@example.com','member',9999999999,?)",(wid,uid))
    assert post(owner,'/workspace/delete',confirm_name='Client A').status_code==302
    assert owner.get('/').status_code==302
    assert other.get('/').status_code==200
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT active,deleted_at IS NOT NULL FROM workspaces WHERE id=?',(wid,)).fetchone()==(0,1)
        assert db.execute('SELECT COUNT(*) FROM invitations WHERE workspace_id=?',(wid,)).fetchone()[0]==0
    assert post(client,f'/management/workspaces/{wid}/restore').status_code==302
    restored=authenticated(app,uid,'restored-owner')
    assert b'Retained inventory' in restored.get('/').data


def test_members_cannot_delete_workspace_and_deletion_requires_recent_auth(app):
    wid,uid,c=tenant(app,role='member')
    assert post(c,'/workspace/delete',confirm_name='Client A').status_code==403
    assert c.post('/account/delete',data={'confirm_name':'Client A'}).status_code==400
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('UPDATE auth_sessions SET authenticated=0 WHERE user_id=?',(uid,))
    assert post(c,'/account/delete',confirm_name='Client A').location.endswith('/account/reauthenticate')


def test_attribution_google_signup_and_private_analytics(app,client):
    make_platform(app)
    app.config['TRUST_CLOUDFLARE_COUNTRY']=True
    c=app.test_client()
    c.get('/register?utm_source=Newsletter&utm_medium=email&utm_campaign=launch',headers={'Referer':'https://example.com/path?secret=private','CF-IPCountry':'US'})
    assert google_flow(app,c,{'sub':'analytics','email':'analytics@gmail.com','email_verified':True}).status_code==302
    with sqlite3.connect(app.config['DATABASE']) as db:
        result=db.execute("SELECT created,last_login,signup_method,signup_source,signup_medium,signup_campaign,signup_country FROM users WHERE google_sub='analytics'").fetchone()
        assert result[0] and result[1]
        assert result[2:]==('Google','Newsletter','email','launch','US')
    assert form(c,'/components/new',name='Client component',stock='2',price='1',price_mode='unit').status_code==302
    from inventory.analytics import inventory_totals
    with sqlite3.connect(app.config['DATABASE']) as db:
        wid=db.execute("SELECT workspace_id FROM users WHERE google_sub='analytics'").fetchone()[0]
    assert inventory_totals(app,wid)['components']==1
    assert c.get('/management/analytics').status_code==403
    assert app.test_client().get('/management/analytics').status_code==302
    page=client.get('/management/analytics')
    assert page.status_code==200
    for text in (b'Newsletter',b'analytics@gmail.com',b'Component types',b'US'):
        assert text in page.data
    assert b'secret=private' not in page.data


def test_referral_hostname_only_and_country_trust_gate(app):
    c=app.test_client()
    c.get('/login',headers={'Referer':'https://referral.example/private?token=secret','CF-IPCountry':'CA'})
    with c.session_transaction() as session:
        assert session['signup_attribution']['source']=='referral.example'
        assert session['signup_attribution']['country'] is None
    c.get('/register?utm_source=override')
    with c.session_transaction() as session:
        assert session['signup_attribution']['source']=='referral.example'
