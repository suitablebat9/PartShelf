import sqlite3
import pytest
from test_inventory import app, client, part, post
from inventory.label_pdf import settings


def test_parent_storage_scope_and_relocation(app, client):
    post(client, '/storage', name='Lab', kind='Room')
    post(client, '/storage', name='Cabinet', kind='Cabinet', parent_id='1')
    post(client, '/storage', name='Drawer', kind='Drawer', parent_id='2')
    part(client, location_id='3')
    assert b'1 matching component' in client.get('/search?location_id=1').data
    assert b'0 matching components' in client.get('/search?location_id=1&location_scope=only').data
    assert post(client, '/storage', location_id='1', name='Lab', kind='Room', parent_id='3').status_code == 400
    assert post(client, '/storage', location_id='3', name='Moved drawer', kind='Drawer', parent_id='1').status_code == 302
    assert b'Lab / Moved drawer' in client.get('/components/1').data
    assert b'0 matching components' in client.get('/search?location_id=2').data


def test_low_stock_numeric_threshold_and_no_threshold(client):
    part(client, name='Low resistor', stock='2', low_stock='10')
    part(client, name='Plenty', stock='20', low_stock='3')
    part(client, name='Empty', stock='0')
    page=client.get('/search?stock=low').data
    assert b'1 matching component' in page and b'Low resistor' in page
    assert b'2 matching components' in client.get('/search?stock=restock').data


def test_basic_part_without_purchase_details_and_context(client):
    assert post(client, '/components/new', name='Basic part', stock='0').status_code == 302
    page=client.get('/components/1?back=/search%3Fq%3DBasic').data
    assert b'href="/search?q=Basic"' in page and b'$0.00' in page
    page=client.get('/components/1?back=https://evil.example/').data
    assert b'https://evil.example' not in page


def test_multiple_builds_shortage_and_idempotent_undo(app,client):
    part(client, stock='10')
    post(client, '/projects', name='Build test')
    post(client, '/projects/1', component_id='1', quantity='3')
    assert post(client, '/projects/1/consume', build_count='2').status_code == 302
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT stock FROM components').fetchone()[0] == 4
    response=client.post('/projects/1/consume',data=dict(csrf='test',build_count='2'),follow_redirects=True)
    assert b'Cannot build yet' in response.data
    assert post(client, '/projects/1/builds/1/undo').status_code == 302
    assert post(client, '/projects/1/builds/1/undo').status_code == 302
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT stock FROM components').fetchone()[0] == 10
        assert db.execute('SELECT COUNT(*) FROM project_builds').fetchone()[0] == 1
    assert post(client, '/projects/1/consume', build_count='1.5').status_code == 400


def test_undo_cannot_restore_deleted_part_into_reused_id(app,client):
    part(client, stock='10')
    post(client, '/projects', name='Build')
    post(client, '/projects/1', component_id='1', quantity='1')
    post(client, '/projects/1/consume')
    post(client, '/components/1/delete', version='2', confirm='delete')
    part(client, name='Replacement',stock='5')
    response=client.post('/projects/1/builds/1/undo',data=dict(csrf='test'),follow_redirects=True)
    assert b'Cannot undo' in response.data
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT stock FROM components').fetchone()[0] == 5


def test_viewer_cannot_rename_storage_or_undo(app,client):
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE users SET role='viewer'")
    assert post(client, '/storage', location_id='1', name='Changed',kind='Room').status_code==403
    assert post(client, '/projects/1/builds/1/undo').status_code==403


def test_mm_dimensions_produce_same_physical_label():
    inches=settings(dict(width='3',height='1',margin_top='0.1'))
    metric=settings(dict(dimension_unit='mm',width='76.2',height='25.4',margin_top='2.54'))
    assert inches==metric
    with pytest.raises(ValueError):
        settings(dict(dimension_unit='mm',width='2'))


def test_page_titles_and_empty_roadmap(client):
    assert b'<title>Label studio' in client.get('/labels').data
    page=client.get('/roadmap').data
    assert b'Roadmap coming soon' in page and b'Updates will appear here.' not in page
