import sqlite3
from unittest.mock import patch
from test_inventory import app,client,post
from test_settings_navigation import make_admin


def test_label_preview_error_is_inline_and_batch_lists_invalid_parts(client):
    post(client,'/components/new',name='Resistor Ω',stock=2,code='RΩ')
    post(client,'/components/new',name='Capacitor µ',stock=2,code='Cµ')
    response=client.post('/labels/pdf?preview=1&render=image',data={'csrf':'test','item_id':'1','mode':'barcode'})
    assert response.status_code==400 and 'ASCII' in response.json['error']
    response=client.get('/labels/pdf?render=image&item_id=1&mode=barcode')
    assert response.status_code==400 and b'aria-label="Sidebar"' not in response.data
    response=client.post('/labels/pdf',data={'csrf':'test','component_ids':['1','2'],'mode':'barcode'})
    assert response.status_code==400 and 'Resistor Ω'.encode() in response.data and 'Capacitor µ'.encode() in response.data
    assert client.get('/labels/pdf?render=image&item_id=1&mode=qr').status_code==200


def test_site_section_save_restore_and_stale_protection(app,client):
    make_admin(app)
    with sqlite3.connect(app.config['DATABASE']) as db:
        original=db.execute("SELECT value FROM site_settings WHERE key='about_text'").fetchone()[0]
        terms=db.execute("SELECT value FROM site_settings WHERE key='terms_text'").fetchone()[0]
    page=client.get('/management/site?section=about')
    import re
    version=re.search(rb'name="content_version" value="([a-f0-9]+)"',page.data).group(1).decode()
    assert post(client,'/management/site',section='about',content_version=version,about_text='Revised biography',terms_text='Unrelated injected edit').status_code==302
    assert post(client,'/management/site',section='about',content_version=version,about_text='Stale edit').status_code==409
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute("SELECT value FROM site_settings WHERE key='terms_text'").fetchone()[0]==terms
        revision=db.execute('SELECT MAX(id) FROM site_revisions').fetchone()[0]
    assert post(client,'/management/site',section='about',restore_revision=revision).status_code==302
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute("SELECT value FROM site_settings WHERE key='about_text'").fetchone()[0]==original


def test_private_feedback_note_never_notifies(app,client):
    make_admin(app)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("INSERT INTO feedback(kind,title,body,email,verified,subscribed,nonce) VALUES('Feedback','Example','Body','test@example.test',1,1,'nonce')")
    with patch('inventory.community.send_email') as mail:
        assert post(client,'/management/feedback',id=1,action='internal',internal_revision=0,internal_note='Private decision').status_code==302
        assert not mail.called
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT internal_note,revision,notified_revision FROM feedback').fetchone()==('Private decision',0,0)
    assert post(client,'/management/feedback',id=1,action='internal',internal_revision=0,internal_note='Stale note').status_code==409


def test_roadmap_reorder_preserves_visibility_and_guards_revision(app,client):
    make_admin(app)
    for name in ('First','Second'):
        post(client,'/management/roadmap',title=name,status='Planned',position=0,published='1')
    assert post(client,'/management/roadmap',action='move',id=1,revision=1,direction='up').status_code==302
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT title,published FROM roadmap ORDER BY position,id DESC').fetchall()==[('First',1),('Second',1)]
    assert post(client,'/management/roadmap',action='move',id=1,revision=1,direction='down').status_code==409


def test_storage_picker_omits_descendants_and_server_rejects_cycle(client):
    post(client,'/storage',name='Parent',kind='Cabinet')
    post(client,'/storage',name='Child',kind='Bin',parent_id=1)
    page=client.get('/storage').data.decode()
    parent_form=page.split('name="location_id" value="1"',1)[1].split('</form>',1)[0]
    assert 'value="2"' not in parent_form
    assert post(client,'/storage',location_id=1,name='Parent',kind='Cabinet',parent_id=2).status_code==400
