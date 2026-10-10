import sqlite3
from test_inventory import app, client, post
from test_workflows import upload, confirm


def test_unrecorded_and_explicit_zero_prices(app, client):
    post(client,'/components/new',name='Unknown',stock='2',unit_price='')
    post(client,'/components/new',name='Free',stock='2',unit_price='0')
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT price_recorded FROM components ORDER BY id').fetchall()==[(0,),(1,)]
    post(client,'/projects',name='Test')
    for component_id in (1,2):
        post(client,'/projects/1',component_id=component_id,quantity=3)
    for path in ('/projects/1','/projects/1/shopping-list'):
        assert b'1 part has no recorded price' in client.get(path).data
    post(client,'/components/1/edit',name='Unknown',stock='2',unit_price='0',version=1)
    assert b'Estimate incomplete' not in client.get('/projects/1').data


def test_csv_preserves_price_presence(app,client):
    confirm(client,upload(client,'/inventory/import','name,unit_price\nUnknown,\nFree,0\nPaid,1\n'))
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT price_recorded FROM components ORDER BY id').fetchall()==[(0,),(1,),(1,)]
