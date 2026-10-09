import sqlite3
from unittest.mock import patch
from test_inventory import app,client,post,part
from test_drawers import setup_cabinet,configure
from test_personal_settings_feedback import nav_keys


def test_layout_multiple_parts_colors_and_storage_count(app,client):
    with sqlite3.connect(app.config['DATABASE']) as db: db.execute("UPDATE users SET role='owner'")
    assert post(client,'/drawers',name='Organizer',columns=4,section_rows=3,stacks=3,color='#ab1234').status_code==302
    part(client,name='Resistor');part(client,name='Capacitor')
    assert post(client,'/drawers/1/assign',row=9,col=4,component_id=['1','2']).status_code==302
    page=client.get('/drawers/1').text
    assert 'data-label="I4"' in page and 'data-label="I5"' not in page
    assert 'Light up' not in page and 'Open drawer</button>' not in page
    assert '+1 more' in page
    assert post(client,'/drawers/1/color',row=9,col=4,color='#00ff11').status_code==302
    assert '--drawer-color:#00ff11' in client.get('/drawers/1').text
    assert post(client,'/drawers/1/color',row=9,col=4,reset='1',color='#ffffff').status_code==302
    assert post(client,'/drawers/1/appearance',name='Renamed',color='#112233').status_code==302
    storage=client.get('/storage').text
    assert 'Renamed' in storage and 'href="/drawers/1"' in storage
    assert 'href="/search?location_id=2"' not in storage
    assert '<span>Storage areas</span><strong>1</strong>' in client.get('/').text
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT COUNT(*) FROM cabinet_drawers').fetchone()[0]==36
        assert db.execute('SELECT COUNT(DISTINCT location_id) FROM components').fetchone()[0]==1
    # One invalid selection rolls back the whole assignment batch.
    assert post(client,'/drawers/1/assign',row=1,col=1,component_id=['1','999']).status_code==404
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT COUNT(DISTINCT location_id) FROM components').fetchone()[0]==1


def test_variable_section_gap_and_limits(app,client):
    with sqlite3.connect(app.config['DATABASE']) as db: db.execute("UPDATE users SET role='owner'")
    app.config['DEVICE_ENDPOINTS']={'1':['http://192.168.1.50']}
    post(client,'/drawers',name='Three',columns=2,section_rows=3,stacks=3)
    configure(client)
    captured=[]
    def device(c,m,p,payload=None):
        captured.append(payload)
        return dict(command_id=payload['command_id'],status='completed')
    with patch('inventory.drawers.device_request',side_effect=device):
        assert post(client,'/drawers/1/command',row=7,col=2,action='light').status_code==202
    assert captured[0]['position_mm']=={'x':50,'y':-250}
    assert 'Light up' in client.get('/drawers/1').text
    for columns,rows,stacks in [(0,8,2),(17,8,2),(16,16,8),(8,0,2),(8,8,9)]:
        assert post(client,'/drawers',name='Invalid',columns=columns,section_rows=rows,stacks=stacks).status_code==400
    assert post(client,'/drawers/1/color',row=1,col=1,color='red;bad').status_code==400


def test_storage_shortcut_opt_in_and_workspace_isolation(app,client):
    setup_cabinet(app,client)
    keys=nav_keys(client)
    assert 'storage:1:1' in keys and 'storage:1:2' not in keys
    nav=client.get('/').text.split('<nav aria-label="Sidebar">')[1].split('</nav>')[0]
    assert '/drawers/1' not in nav
    assert post(client,'/settings',palette='default',nav_order=keys,nav_visible=['storage:1:1']).status_code==302
    nav=client.get('/').text.split('<nav aria-label="Sidebar">')[1].split('</nav>')[0]
    assert '/drawers/1' in nav
    from inventory.workspaces import initialize_inventory
    initialize_inventory(app,2)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("INSERT INTO workspaces(id,name) VALUES(2,'Other')")
        db.execute('UPDATE users SET workspace_id=2')
    assert 'storage:1:1' not in nav_keys(client)
    assert '/drawers/1' not in client.get('/').text


def test_donation_uses_checkout_and_site_background(app,client):
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("INSERT INTO site_settings(key,value) VALUES('stripe_link','https://donate.stripe.com/example') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    page=client.get('/').text
    assert 'href="https://donate.stripe.com/example">♡ Donate' in page
    public=app.test_client().get('/welcome').text
    assert 'donation-widget' in public and 'Donate with Stripe' in public
    assert '<stripe-buy-button' not in public


def test_old_layout_survives_additive_migration():
    from inventory.drawers import migrate_drawers
    db=sqlite3.connect(':memory:')
    db.execute('CREATE TABLE locations(id INTEGER PRIMARY KEY)')
    db.execute("CREATE TABLE cabinets(id INTEGER PRIMARY KEY,name TEXT,location_id INTEGER,row_count INTEGER)")
    db.execute('INSERT INTO cabinets VALUES(1,\'Old\',1,16)')
    db.execute('CREATE TABLE cabinet_drawers(cabinet_id INTEGER,row INTEGER,col INTEGER,location_id INTEGER)')
    db.execute('INSERT INTO cabinet_drawers VALUES(1,16,8,129)')
    migrate_drawers(db);migrate_drawers(db)
    assert db.execute('SELECT row_count,column_count,section_rows,color FROM cabinets').fetchone()==(16,8,8,'#527aa3')
    assert db.execute('SELECT row,col,location_id,color FROM cabinet_drawers').fetchone()==(16,8,129,'')
