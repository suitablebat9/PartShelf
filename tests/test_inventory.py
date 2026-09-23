import io
import sqlite3
import pytest
from werkzeug.security import generate_password_hash
from inventory import create_app


@pytest.fixture
def app(tmp_path):
    app = create_app({'TESTING': True, 'DATA_DIR': tmp_path, 'DATABASE': str(tmp_path/'test.db')})
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('INSERT INTO users(username,password) VALUES(?,?)', ('admin', generate_password_hash('test-password-123')))
    return app


@pytest.fixture
def client(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session['user'] = 'admin'
        session['csrf'] = 'test'
    return client


def post(client, url, **data):
    return client.post(url, data={'csrf': 'test', **data})


def part(client, **kwargs):
    return post(client, '/components/new', **({'name': '10k resistor', 'stock': '20', 'price': '2', 'price_mode': 'purchase', 'purchase_quantity': '10', 'category': 'Resistors', 'supplier': 'Mouser', 'attributes': '0603 1%', **kwargs}))


def test_auth_csrf_and_login(app):
    c = app.test_client()
    assert c.get('/').status_code == 302
    assert c.post('/components/new', data={'name': 'bad'}).status_code == 400
    c.get('/login')
    with c.session_transaction() as s:
        token = s['csrf']
    response = c.post('/login', data={'csrf': token, 'username': 'admin', 'password': 'test-password-123'})
    assert response.status_code == 302
    assert c.get('/').status_code == 200


def test_component_prices_search_categories_and_conflicts(client, app):
    assert part(client).status_code == 302
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT name_id,unit_price FROM components').fetchone() == ('10k resistor', '0.200000')
        assert db.execute('SELECT COUNT(*) FROM categories').fetchone()[0] == 1
    assert b'10k resistor' in client.get('/search?q=0603&supplier=Mouser&stock=in').data
    assert b'No matching components' in client.get('/search?q=nothing').data
    assert part(client, name='Second', category='resistors').status_code == 302
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT COUNT(*) FROM categories').fetchone()[0] == 1
    assert post(client, '/components/1/stock', quantity='5', direction='add').status_code == 302
    assert post(client, '/components/1/edit', name='Overwrite', stock='2', price='1', version='1').status_code == 409
    assert post(client, '/components/1/stock', quantity='30', direction='remove').status_code == 400


def test_storage_project_costs_and_atomic_consumption(client, app):
    post(client, '/storage', name='Workshop', kind='Room')
    post(client, '/storage', name='Cabinet', kind='Cabinet', parent_id='1')
    assert b'Workshop / Cabinet' in client.get('/storage').data
    part(client, location_id='2')
    part(client, name='Regulator', stock='1', price='5', price_mode='unit')
    post(client, '/projects', name='Sensor', description='Test build')
    post(client, '/projects/1', component_id='1', quantity='4')
    post(client, '/projects/1', component_id='2', quantity='2')
    page = client.get('/projects/1')
    assert page.status_code == 200
    assert b'10.80' in page.data
    assert b'5.00' in page.data
    assert post(client, '/projects/1/consume').status_code == 400
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT stock FROM components WHERE id=1').fetchone()[0] == 20
    post(client, '/components/2/stock', quantity='1', direction='add')
    assert post(client, '/projects/1/consume').status_code == 302
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT stock FROM components ORDER BY id').fetchall() == [(16,), (0,)]
    post(client, '/projects/1', component_id='2', quantity='0')
    assert b'Regulator</a>' not in client.get('/projects/1').data


def test_labels_uploads_and_input_validation(client):
    part(client)
    for mode in ['qr', 'barcode', 'none']:
        assert client.get('/labels?mode='+mode+'&width=1.5&height=3.5&text=Custom').status_code == 200
    assert client.get('/codes/1/qr').content_type.startswith('image/png')
    assert client.get('/codes/1/barcode').content_type.startswith('image/svg+xml')
    assert client.get('/labels?font=evil').status_code == 400
    assert part(client, name='Bad', stock='NaN').status_code == 400
    assert part(client, name='Bad', supplier_url='javascript:alert(1)').status_code == 400
    assert part(client, name='Bad', datasheet=(io.BytesIO(b'bad'), 'file.pdf')).status_code == 400
    assert part(client, name='Good', datasheet=(io.BytesIO(b'%PDF-1.4\n'), 'file.pdf')).status_code == 302
    for path in ['/', '/search', '/components/1', '/components/1/edit', '/components/new', '/storage', '/projects', '/labels']:
        assert client.get(path).status_code == 200


def test_multi_device_shared_data(client, app):
    part(client)
    other = app.test_client()
    with other.session_transaction() as s:
        s['user'] = 'admin'
        s['csrf'] = 'test'
    post(other, '/components/1/stock', quantity='3', direction='remove')
    assert b'17' in client.get('/components/1').data


@pytest.mark.parametrize('password,accepted', [('1234567', False), ('12345678', True)])
def test_create_user_password_minimum(app, password, accepted):
    from werkzeug.security import check_password_hash
    result = app.test_cli_runner().invoke(args=['create-user'], input=f'new-user\n{password}\n{password}\n')
    assert (result.exit_code == 0) == accepted
    with sqlite3.connect(app.config['DATABASE']) as db:
        row = db.execute('SELECT password FROM users WHERE username=?', ('new-user',)).fetchone()
    if accepted:
        assert row is not None and check_password_hash(row[0], password)
    else:
        assert row is None
        assert 'at least 8 characters' in result.output


@pytest.mark.parametrize('password,accepted', [('1234567', False), ('12345678', True)])
def test_manage_user_password_minimum(app, monkeypatch, password, accepted):
    from scripts import manage_user
    from werkzeug.security import check_password_hash
    # manage_user uses the standard inventory.db filename.
    database = app.config['DATA_DIR'] / 'inventory.db'
    with sqlite3.connect(app.config['DATABASE']) as source, sqlite3.connect(database) as target:
        source.backup(target)
    monkeypatch.setenv('INVENTORY_DATA', str(app.config['DATA_DIR']))
    monkeypatch.setattr('builtins.input', lambda prompt: 'new-user')
    monkeypatch.setattr(manage_user.getpass, 'getpass', lambda prompt: password)
    if accepted:
        manage_user.main()
    else:
        with pytest.raises(SystemExit, match='at least 8 characters'):
            manage_user.main()
    with sqlite3.connect(database) as db:
        row = db.execute('SELECT password FROM users WHERE username=?', ('new-user',)).fetchone()
    if accepted:
        assert row is not None and check_password_hash(row[0], password)
    else:
        assert row is None


def test_inline_storage_tags_specs_and_identifier(client, app):
    response = part(client, name='Precision resistor', name_id='R-10K', tags='audio, prototype, AUDIO', create_storage='1', new_location_name='Drawer A', new_location_kind='Drawer', size='0603', resistance='10 kΩ', tolerance='1%')
    assert response.status_code == 302
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT code,purchase_quantity,purchase_total FROM components').fetchone() == ('R-10K', '10', '2')
        assert db.execute('SELECT name,kind FROM locations').fetchone() == ('Drawer A', 'Drawer')
        assert db.execute('SELECT COUNT(*) FROM component_tags').fetchone()[0] == 2
    assert b'Precision resistor' in client.get('/search?tag=audio&tag=prototype&size=0603&resistance=10').data
    assert b'No matching components' in client.get('/search?tag=audio&tag=missing').data
    assert b'Precision resistor' in client.get('/search?q=prototype').data
    assert b'Precision resistor' in client.get('/search?q=10+k%CE%A9').data
    form = client.get('/components/new').data
    assert b'<option value="Mouser">' in form
    assert b'<option value="Resistors">' in form


def test_inline_storage_rollback_on_duplicate_identifier(client, app):
    part(client, name_id='DUP')
    response = part(client, name='Duplicate', name_id='DUP', create_storage='1', new_location_name='Must not persist', new_location_kind='Bin')
    assert response.status_code == 409
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT COUNT(*) FROM locations').fetchone()[0] == 0


def test_purchase_quantity_persists_after_stock_use(client, app):
    assert part(client, price_mode='purchase', purchase_total='12', purchase_quantity='100', stock='100').status_code == 302
    post(client, '/components/1/stock', quantity='75', direction='remove')
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT stock,purchase_quantity,purchase_total,unit_price FROM components').fetchone() == (25, '100', '12', '0.120000')
    assert b'value="100"' in client.get('/components/1/edit').data
    assert post(client, '/components/1/edit', name='10k resistor', stock='25', price_mode='unit', unit_price='.15', purchase_quantity='100', version='2').status_code == 302
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT purchase_total,unit_price FROM components').fetchone() == ('15.00', '0.150000')


def test_new_purchase_defaults_to_starting_stock(client, app):
    assert part(client, purchase_quantity='', stock='50', purchase_total='10').status_code == 302
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT purchase_quantity,unit_price FROM components').fetchone() == ('50', '0.200000')
    assert part(client, name='Invalid', purchase_quantity='0').status_code == 400


def test_bulk_label_pdf_and_preview(client):
    from pypdf import PdfReader
    part(client, name='Resistor', name_id='R10K', resistance='10 kΩ')
    part(client, name='Capacitor', name_id='C100N', capacitance='100 nF')
    options = dict(component_ids=['1','2'], item_id='1', width='3.5', height='1.5', mode='qr', font='sans-serif', size='14', copies='2', text='{name}\n{name_id}\n{resistance}{capacitance}')
    result = post(client, '/labels/pdf', **options)
    assert result.status_code == 200 and result.mimetype == 'application/pdf'
    pdf = PdfReader(io.BytesIO(result.data))
    assert len(pdf.pages) == 4
    assert float(pdf.pages[0].mediabox.width) == 252
    assert float(pdf.pages[0].mediabox.height) == 108
    import unicodedata
    text = unicodedata.normalize('NFKC', '\n'.join(page.extract_text() for page in pdf.pages))
    assert 'Resistor' in text and 'Capacitor' in text and '10 kΩ' in text and '100 nF' in text
    assert 'attachment' in result.headers['Content-Disposition']
    preview = post(client, '/labels/pdf?preview=1', **options)
    assert len(PdfReader(io.BytesIO(preview.data)).pages) == 1
    assert 'inline' in preview.headers['Content-Disposition']
    assert preview.headers['X-Frame-Options'] == 'SAMEORIGIN'
    image_preview = post(client, '/labels/pdf?preview=1&render=image', **options)
    assert image_preview.status_code == 200
    assert b'data:image/png;base64,iVBOR' in image_preview.data
    assert post(client, '/labels/pdf', mode='none').status_code == 400
    assert post(client, '/labels/pdf', component_ids=['999']).status_code == 400
    assert post(client, '/labels/pdf', component_ids=['1'], copies='1.5').status_code == 400
    assert post(client, '/labels/pdf', component_ids=['1'], mode='barcode').status_code == 200


def test_label_browser_line_endings():
    from inventory.label_pdf import settings
    assert settings({'text': '{name}\r\n{name_id}\rnext'})['text'] == '{name}\n{name_id}\nnext'
