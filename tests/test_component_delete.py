import sqlite3
from test_inventory import app,client,post,part


def test_delete_confirmation_and_related_rows(app,client):
    part(client,tags='SMD')
    part(client,name='Keep me')
    post(client,'/projects',name='Build')
    post(client,'/components/1/project',project_id=1,quantity=2)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('INSERT INTO stock_alerts(user_id,component_id) VALUES(1,1)')
    assert b'Delete component' in client.get('/components/1').data
    assert b'Delete component' in client.get('/components/1/edit').data
    page=client.get('/components/1/delete')
    assert page.status_code==200 and b'Build' in page.data
    assert post(client,'/components/1/delete',version=1).status_code==400
    assert client.post('/components/1/delete',data={'version':1,'confirm':'delete'}).status_code==400
    assert post(client,'/components/1/delete',version=1,confirm='delete').status_code==302
    assert client.get('/components/1').status_code==404
    assert client.get('/components/2').status_code==200
    with sqlite3.connect(app.config['DATABASE']) as db:
        for table in ('stock_alerts','movements','component_tags','project_items'):
            assert db.execute('SELECT COUNT(*) FROM '+table+' WHERE component_id=1').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM projects').fetchone()[0]==1


def test_delete_blocks_stale_confirmation_and_viewer(app,client):
    part(client)
    post(client,'/components/1/stock',direction='add',quantity=1)
    assert post(client,'/components/1/delete',version=1,confirm='delete').status_code==409
    assert client.get('/components/1').status_code==200
    with sqlite3.connect(app.config['DATABASE']) as db: db.execute("UPDATE users SET role='viewer'")
    assert b'Delete component' not in client.get('/components/1').data
    assert client.get('/components/1/delete').status_code==403
    assert post(client,'/components/1/delete',version=2,confirm='delete').status_code==403


def test_delete_is_workspace_scoped(app,client):
    part(client)
    from test_workspaces import tenant
    _,_,other=tenant(app)
    assert other.get('/components/1/delete').status_code==404
    assert client.get('/components/1').status_code==200


def test_demo_deletion_does_not_touch_real_inventory(app,client):
    part(client)
    demo=app.test_client();demo.get('/demo')
    with demo.session_transaction() as session: token=session['csrf']
    demo.post('/demo',data={'csrf':token})
    assert demo.get('/components/1/delete').status_code==200
    assert demo.post('/components/1/delete',data={'csrf':token,'version':1,'confirm':'delete'}).status_code==302
    assert demo.get('/components/1').status_code==404
    assert client.get('/components/1').status_code==200
