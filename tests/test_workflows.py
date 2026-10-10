import csv
import io
import json
import sqlite3
import time
from test_inventory import app, client, part, post
from test_workspaces import tenant, authenticated
from inventory.workspaces import connect_inventory
from scripts.publish_workflows_roadmap import publish


def upload(client,path,text,**extra):
    return client.post(path,data=dict(csrf='test',file=(io.BytesIO(text.encode('utf-8-sig')),'parts.csv'),**extra))


def confirm(client,response):
    assert response.status_code==302
    assert response.location.startswith('/tools/confirm/')
    page=client.get(response.location)
    assert page.status_code==200
    return post(client,response.location,confirmed='yes')


def test_inventory_csv_preview_atomic_commit_and_replay(app,client):
    post(client,'/storage',name='Lab',kind='Room')
    response=upload(client,'/inventory/import','name,name_id,stock,unit_price,category,storage,tags,purchase_pack\nResistor,R1,100,.02,Resistors,Lab,"passive, resistor",100\nCapacitor,C1,0,.15,Capacitors,,,1\n')
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT COUNT(*) FROM components').fetchone()[0]==0
    assert confirm(client,response).status_code==302
    assert post(client,response.location,confirmed='yes').status_code==404
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT name_id,stock,purchase_total FROM components ORDER BY id').fetchall()==[('R1',100,'2.000000'),('C1',0,None)]
        assert db.execute('SELECT COUNT(*) FROM tags').fetchone()[0]==2
        assert db.execute('SELECT COUNT(*) FROM movements').fetchone()[0]==1


def test_import_rejects_all_rows_on_duplicate_bad_headers_or_values(app,client):
    part(client,name='Existing',name_id='R1')
    for text in ('name,name_id\nNew,R2\nDuplicate,R1\n','name,unknown\nNew,x\n','name,stock\nNew,NaN\n','name,storage\nNew,Missing\n','name,name\nOne,Two\n','name,supplier_url\nNew,javascript:alert(1)\n'):
        assert upload(client,'/inventory/import',text).status_code==400
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT COUNT(*) FROM components').fetchone()[0]==1
    too_many='name\n'+'\n'.join('Part'+str(i) for i in range(1001))
    assert upload(client,'/inventory/import',too_many).status_code==400


def test_import_rechecks_uniqueness_and_expiry(app,client):
    response=upload(client,'/inventory/import','name,name_id\nImported,R1\n')
    part(client,name='Created meanwhile',name_id='R1')
    assert post(client,response.location,confirmed='yes').status_code==409
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT COUNT(*) FROM components').fetchone()[0]==1
        db.execute('UPDATE workflow_previews SET expires=0')
    assert post(client,response.location,confirmed='yes').status_code==404


def test_bom_merge_replace_duplicate_rows_and_no_stock_change(app,client):
    part(client,name='Resistor',name_id='R1');part(client,name='Capacitor',name_id='C1')
    post(client,'/projects',name='Sensor')
    post(client,'/projects/1',component_id='2',quantity='8')
    response=upload(client,'/projects/1/import','name_id,quantity\nR1,2\nR1,3\n',mode='merge')
    assert confirm(client,response).status_code==302
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT quantity FROM project_items ORDER BY component_id').fetchall()==[(5,),(8,)]
    response=upload(client,'/projects/1/import','name_id,quantity\nC1,1\n',mode='replace')
    assert confirm(client,response).status_code==302
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT component_id,quantity FROM project_items').fetchall()==[(2,1)]
        assert db.execute('SELECT stock FROM components').fetchall()==[(20,),(20,)]
    assert upload(client,'/projects/1/import','name_id,quantity\nMissing,1\n').status_code==400


def test_bom_rejects_concurrent_project_change(app,client):
    part(client,name_id='R1');post(client,'/projects',name='Build')
    response=upload(client,'/projects/1/import','name_id,quantity\nR1,5\n')
    post(client,'/projects/1',component_id='1',quantity='2')
    assert post(client,response.location,confirmed='yes').status_code==409


def test_bulk_stock_atomic_stale_and_tag_move(app,client):
    part(client,name='One',stock='10');part(client,name='Two',stock='3')
    failed=post(client,'/inventory/bulk',component_ids=['1','2'],action='stock_remove',quantity='4')
    assert failed.location.endswith('/search') or failed.location=='/'
    with sqlite3.connect(app.config['DATABASE']) as db: assert db.execute('SELECT stock FROM components').fetchall()==[(10,),(3,)]
    response=post(client,'/inventory/bulk',component_ids=['1','2'],action='stock_add',quantity='2',reason='Delivery')
    assert confirm(client,response).status_code==302
    with sqlite3.connect(app.config['DATABASE']) as db: assert db.execute('SELECT stock FROM components').fetchall()==[(12,),(5,)]
    response=post(client,'/inventory/bulk',component_ids=['1','2'],action='tag_add',tags='passive, new')
    assert confirm(client,response).status_code==302
    response=post(client,'/inventory/bulk',component_ids=['1','2'],action='tag_remove',tags='new')
    assert confirm(client,response).status_code==302
    post(client,'/storage',name='Box',kind='Bin')
    response=post(client,'/inventory/bulk',component_ids=['1','2'],action='move',location_id='1')
    assert confirm(client,response).status_code==302
    response=post(client,'/inventory/bulk',component_ids=['1','2'],action='stock_add',quantity='2')
    post(client,'/components/1/stock',quantity='1',direction='add')
    assert post(client,response.location,confirmed='yes').status_code==409
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT stock,location_id FROM components').fetchall()==[(13,1),(5,1)]
        assert db.execute('SELECT COUNT(*) FROM component_tags').fetchone()[0]==2


def test_project_duplicate_shopping_pack_math_and_csv_safety(app,client):
    part(client,name='=Danger',name_id='R1',stock='8',price_mode='unit',unit_price='.02',purchase_pack='100',supplier='@Supplier',supplier_url='https://example.com/r')
    post(client,'/projects',name='Prototype')
    post(client,'/projects/1',component_id='1',quantity='20')
    duplicate=post(client,'/projects/1/duplicate')
    assert duplicate.location.endswith('/projects/2')
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT quantity FROM project_items WHERE project_id=2').fetchone()[0]==20
        assert db.execute('SELECT stock FROM components').fetchone()[0]==8
        assert db.execute('SELECT COUNT(*) FROM project_builds').fetchone()[0]==0
    page=client.get('/projects/1/shopping-list?builds=2')
    assert page.status_code==200 and b'$2.00' in page.data
    response=client.get('/projects/1/shopping-list?builds=2&download=csv')
    row=list(csv.DictReader(io.StringIO(response.data.decode('utf-8-sig'))))[0]
    assert row['shortage']=='32.0' and row['packs']=='1' and row['purchase_units']=='100'
    assert row['name']=="'=Danger" and row['supplier']=="'@Supplier"
    assert client.get('/projects/1/shopping-list?builds=1.5').status_code==400


def test_workflow_permissions_workspace_session_isolation(app,client):
    response=upload(client,'/inventory/import','name\nPrivate\n')
    wid,uid,other=tenant(app)
    assert other.get(response.location).status_code==404
    assert post(other,response.location,confirmed='yes').status_code==404
    assert post(other,'/projects/1/duplicate').status_code==404
    assert other.get('/projects/1/shopping-list').status_code==404
    with sqlite3.connect(app.config['DATABASE']) as db: db.execute("UPDATE users SET role='viewer' WHERE id=1")
    for path in ('/inventory/import','/projects/1/import',response.location): assert client.get(path).status_code==403
    for path in ('/inventory/bulk','/projects/1/duplicate',response.location): assert post(client,path).status_code==403
    with sqlite3.connect(app.config['DATABASE']) as db: db.execute("UPDATE users SET role='member' WHERE id=1")
    with client.session_transaction() as s: s['csrf']='new-browser'
    assert client.get(response.location).status_code==404


def test_templates_scanner_help_and_checklist(app,client):
    template=client.get('/imports/template/inventory.csv')
    assert template.status_code==200 and 'attachment' in template.headers['Content-Disposition']
    scan=client.get('/scan')
    assert b'vendor/zxing-browser-0.1.5.min.js' in scan.data and 'blob:' in scan.headers['Content-Security-Policy']
    assert client.get('/help').status_code==200
    assert b'0 of 4 complete' in client.get('/').data
    part(client);post(client,'/storage',name='Shelf',kind='Shelf');post(client,'/projects',name='Build')
    assert b'3 of 4 complete' in client.get('/').data
    assert post(client,'/labels/pdf',component_ids='1',copies='1').status_code==200
    assert b'Workspace setup' not in client.get('/').data


def test_roadmap_publisher_idempotent_and_preserves_manual_edits(app):
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("INSERT INTO roadmap(title,status) VALUES('My plan','Planned')");db.commit()
        assert publish(db)==6
        db.execute("UPDATE roadmap SET title='Edited release title' WHERE id=2");db.commit()
        assert publish(db)==0
        assert db.execute('SELECT COUNT(*) FROM roadmap').fetchone()[0]==7
        assert db.execute("SELECT status FROM roadmap WHERE title='My plan'").fetchone()[0]=='Planned'


def test_demo_workflows_stay_in_demo(app,client):
    from test_demo import form
    demo=app.test_client();form(demo,'/demo')
    for path in ('/inventory/import','/projects/1/import','/projects/1/shopping-list','/scan','/help'):
        assert demo.get(path).status_code==200
    with demo.session_transaction() as session: csrf=session['csrf']
    response=demo.post('/inventory/bulk',data=dict(csrf=csrf,component_ids='1',action='stock_add',quantity='1'))
    assert demo.post(response.location,data=dict(csrf=csrf,confirmed='yes')).status_code==302
    with sqlite3.connect(app.config['DATABASE']) as db: assert db.execute('SELECT COUNT(*) FROM components').fetchone()[0]==0
