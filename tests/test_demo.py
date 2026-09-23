import sqlite3
import pytest
from test_inventory import app, client, part
def form(c, url, **data):
    c.get('/demo')
    with c.session_transaction() as session:
        token=session['csrf']
    return c.post(url,data={'csrf':token,**data})


def test_demo_sample_data_is_separate_and_readonly(app, client):
    part(client,name='Private customer part')
    c=app.test_client()
    assert b'value="demo"' in c.get('/demo').data
    assert b'/demo' in c.get('/login').data
    assert form(c,'/demo').status_code==302
    page=c.get('/')
    assert b'Private customer part' not in page.data
    assert b'ESP32' in page.data
    assert b'/account"' not in page.data
    for path in ('/components/1','/projects','/projects/1','/storage','/labels','/search?q=0603','/codes/1/qr'):
        assert c.get(path).status_code==200
    for path in ('/account','/management','/workspace/export','/uploads/test.pdf','/components/new'):
        assert c.get(path).status_code==403
    for path in ('/components/1/stock','/storage','/projects','/projects/1','/account/notifications','/management/registration','/account/google/link'):
        assert form(c,path,name='changed',quantity='1').status_code==403
    assert form(c,'/labels/pdf',component_ids='1',copies='1').status_code==200
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM components').fetchone()[0]==1
    assert form(c,'/demo/exit').location.endswith('/login')
    assert c.get('/').status_code==302


def test_demo_preserves_signed_in_workspace_and_csrf(app,client):
    part(client,name='Real inventory')
    assert client.post('/demo').status_code==400
    assert form(client,'/demo').status_code==302
    assert b'Real inventory' not in client.get('/').data
    assert form(client,'/demo/exit').status_code==302
    assert b'Real inventory' in client.get('/').data
