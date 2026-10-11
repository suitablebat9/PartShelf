import io
import sqlite3
from PIL import Image
from test_inventory import app, client, post


def test_product_supplier_and_manual_override(app, client):
    post(client,'/components/new',name='Auto',stock='1',supplier_url='https://www.mouser.com/product/123')
    post(client,'/components/new',name='Manual',stock='1',supplier_url='https://www.mouser.com/product/123',supplier='Local shop',supplier_manual='1')
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT supplier FROM components ORDER BY id').fetchall()==[('Mouser',),('Local shop',)]


def test_storage_creation_return_context_and_filter_drawers(app, client):
    with sqlite3.connect(app.config['DATABASE']) as db: db.execute("UPDATE users SET role='owner' WHERE id=1")
    post(client,'/drawers',name='Organizer',columns='2',section_rows='2',stacks='1')
    with sqlite3.connect(app.config['DATABASE']) as db:
        lid=db.execute('SELECT location_id FROM cabinet_drawers LIMIT 1').fetchone()[0]
    back='/drawers/1?slot=1-1'
    page=client.get('/components/new',query_string={'location_id':lid,'back':back})
    assert page.status_code==200 and b'Back</a>' in page.data and back.encode() in page.data
    response=post(client,'/components/new',name='In drawer',stock=1,location_id=lid,back=back)
    assert response.location==back
    response=post(client,'/components/new',name='Safe return',stock=1,back='//evil.example')
    assert response.location.startswith('/components/')
    page=client.get('/search',query_string={'location_id':lid})
    assert b'Back to drawers' in page.data and b'id="overview-bar" hidden' in page.data
    import re
    select=re.search(rb'<select name="location_id" aria-label="Storage">(.*?)</select>',page.data).group(1)
    assert select.count(b'(current drawer)')==1
    assert select.count(b'<option')==3


def test_organizer_photo_validation_and_persistence(app, client):
    with sqlite3.connect(app.config['DATABASE']) as db: db.execute("UPDATE users SET role='owner' WHERE id=1")
    post(client,'/drawers',name='Organizer',columns='2',section_rows='2',stacks='1')
    bad=client.post('/drawers/1/appearance',data={'csrf':'test','name':'Organizer','color':'#123456','image':(io.BytesIO(b'<script>bad</script>'),'photo.png')})
    assert bad.status_code==400
    photo=io.BytesIO();Image.new('RGB',(4,4),'blue').save(photo,format='PNG');photo.seek(0)
    good=client.post('/drawers/1/appearance',data={'csrf':'test','name':'Organizer','color':'#123456','image':(photo,'photo.png')})
    assert good.status_code==302
    with sqlite3.connect(app.config['DATABASE']) as db:
        path=db.execute('SELECT image FROM cabinets').fetchone()[0]
    assert path.startswith('/uploads/') and client.get(path).status_code==200
    assert path.encode() in client.get('/drawers/1').data


def test_drawer_photo_and_existing_component_move(app, client):
    with sqlite3.connect(app.config['DATABASE']) as db: db.execute("UPDATE users SET role='owner' WHERE id=1")
    post(client,'/drawers',name='Organizer',columns=2,section_rows=2,stacks=1)
    post(client,'/components/new',name='Move me',stock=2)
    photo=io.BytesIO();Image.new('RGB',(4,4),'green').save(photo,format='PNG');photo.seek(0)
    response=client.post('/drawers/1/color',data={'csrf':'test','row':'1','col':'1','color':'#123456','image':(photo,'photo.png')})
    assert response.status_code==302
    with sqlite3.connect(app.config['DATABASE']) as db:
        lid,path=db.execute('SELECT location_id,image FROM cabinet_drawers WHERE row=1 AND col=1').fetchone()
    assert path.encode() in client.get('/drawers/1').data
    assert b'Move me' in client.get(f'/storage/{lid}/add').data
    response=post(client,'/inventory/bulk',action='move',location_id=str(lid),component_ids=['1'])
    assert '/tools/confirm/' in response.location
    response=post(client,response.location,confirmed='yes')
    assert response.status_code==302 and response.location==f'/search?location_id={lid}'
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT location_id FROM components WHERE id=1').fetchone()[0]==lid
