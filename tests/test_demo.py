import sqlite3
import pytest
from test_inventory import app, client, part
def form(c, url, **data):
    c.get('/demo')
    with c.session_transaction() as session:
        token=session['csrf']
    return c.post(url,data={'csrf':token,**data})


def test_demo_sample_data_is_separate_and_editable(app, client):
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
    for path in ('/account','/management','/workspace/export','/management/analytics'):
        assert c.get(path).status_code==403
    for path in ('/account/notifications','/management/registration','/account/google/link','/account/delete','/workspace/delete'):
        assert form(c,path,name='changed',quantity='1').status_code==403
    assert c.get('/components/new').status_code==200
    assert c.get('/uploads/test.pdf').status_code==404
    assert form(c,'/components/new',name='Visitor part',stock='5',price='0.50',price_mode='unit').status_code==302
    assert form(c,'/components/1/stock',quantity='2',direction='add').status_code==302
    assert b'Visitor part' in c.get('/').data
    other=app.test_client()
    form(other,'/demo')
    assert b'Visitor part' in other.get('/').data
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


def test_demo_resets_after_48_hours_and_rejects_stale_writes(app,client,monkeypatch):
    import time
    from pathlib import Path
    part(client,name='Keep real data')
    c=app.test_client()
    form(c,'/demo')
    form(c,'/components/new',name='Disposable part',stock='1',price='1',price_mode='unit')
    upload=Path(app.config['DATA_DIR'])/'demo'/'uploads'/'test.pdf'
    upload.write_bytes(b'%PDF-test')
    path=Path(app.config['DATA_DIR'])/'demo.sqlite3'
    with sqlite3.connect(path) as db:
        reset_at=db.execute('SELECT reset_at FROM demo_state').fetchone()[0]
        assert 47*3600<reset_at-time.time()<=48*3600
    monkeypatch.setattr('inventory.demo.time.time',lambda: reset_at+1)
    assert form(c,'/components/1/stock',quantity='3').status_code==409
    assert b'Disposable part' not in c.get('/').data
    assert not upload.exists()
    from test_workspaces import authenticated
    restored=authenticated(app,1,'after-reset')
    assert b'Keep real data' in restored.get('/').data
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM components').fetchone()[0]==10
        assert db.execute('SELECT stock FROM components WHERE id=1').fetchone()[0]==250
    assert app.test_cli_runner().invoke(args=['reset-demo']).exit_code==0
