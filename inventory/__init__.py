import io
import os
import secrets
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

import barcode
import qrcode
from flask import Flask, abort, flash, g, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS locations(id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, parent_id INTEGER REFERENCES locations(id), UNIQUE(name,parent_id));
CREATE TABLE IF NOT EXISTS components(id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_id TEXT UNIQUE NOT NULL, description TEXT NOT NULL DEFAULT '', category_id INTEGER REFERENCES categories(id), location_id INTEGER REFERENCES locations(id), stock REAL NOT NULL CHECK(stock>=0), unit TEXT NOT NULL DEFAULT 'pcs', unit_price TEXT NOT NULL DEFAULT '0', supplier TEXT NOT NULL DEFAULT '', supplier_url TEXT NOT NULL DEFAULT '', datasheet TEXT NOT NULL DEFAULT '', image TEXT NOT NULL DEFAULT '', code TEXT UNIQUE NOT NULL, attributes TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS movements(id INTEGER PRIMARY KEY, component_id INTEGER NOT NULL REFERENCES components(id), delta REAL NOT NULL, reason TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS project_items(project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE, component_id INTEGER REFERENCES components(id), quantity REAL NOT NULL CHECK(quantity>0), PRIMARY KEY(project_id,component_id));
'''


def create_app(test_config=None):
    app = Flask(__name__)
    data = Path(os.environ.get('INVENTORY_DATA', str(Path.cwd() / 'data')))
    app.config.update(DATA_DIR=data, DATABASE=str(data / 'inventory.db'), MAX_CONTENT_LENGTH=12*1024*1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE') == '1')
    if test_config:
        app.config.update(test_config)
    data = Path(app.config['DATA_DIR'])
    data.mkdir(parents=True, exist_ok=True)
    (data / 'uploads').mkdir(exist_ok=True)
    key = data / 'secret.key'
    if not key.exists():
        try:
            with key.open('x') as f:
                f.write(secrets.token_hex(32))
            key.chmod(0o600)
        except FileExistsError:
            pass
    app.secret_key = key.read_text()

    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(app.config['DATABASE'], timeout=30)
            g.db.row_factory = sqlite3.Row
            g.db.execute('PRAGMA foreign_keys=ON')
        return g.db

    with app.app_context():
        db().execute('PRAGMA journal_mode=WAL')
        db().executescript(SCHEMA)
        db().commit()
        g.pop('db').close()

    @app.teardown_appcontext
    def close_db(error=None):
        if 'db' in g:
            g.db.close()

    def rows(sql, args=()):
        return db().execute(sql, args).fetchall()

    def one(sql, args=()):
        row = db().execute(sql, args).fetchone()
        if row is None:
            abort(404)
        return row

    def number(value, minimum=0):
        try:
            result = Decimal(str(value))
            if not result.is_finite() or result < minimum or result > Decimal('1000000000'):
                raise ValueError('Number is outside the supported range.')
            return result
        except (InvalidOperation, TypeError):
            raise ValueError('Enter a valid number.')

    def safe_url(value):
        if value and urlsplit(value).scheme not in ('http', 'https'):
            raise ValueError('Links must start with https:// or http://.')
        return value

    def csrf():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_hex(32)
        return session['csrf']

    app.jinja_env.globals['csrf'] = csrf
    app.jinja_env.filters['money'] = lambda v: f'{Decimal(str(v)):,.2f}'
    app.jinja_env.filters['qty'] = lambda v: f'{float(v):g}'

    @app.before_request
    def protect():
        if request.endpoint == 'static':
            return
        if request.method == 'POST' and not secrets.compare_digest(session.get('csrf', ''), request.form.get('csrf', '!')):
            abort(400, 'Invalid form token. Reload the page and try again.')
        if request.endpoint not in ('login', 'static') and not session.get('user'):
            return redirect(url_for('login'))

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(ValueError)
    def invalid(error):
        return render_template('error.html', message=str(error)), 400

    @app.errorhandler(sqlite3.IntegrityError)
    def conflict(error):
        return render_template('error.html', message='That identifier already exists, or the selected record is still in use. Return to the form and check your values.'), 409

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            user = db().execute('SELECT * FROM users WHERE username=?', (request.form['username'],)).fetchone()
            if user and check_password_hash(user['password'], request.form['password']):
                session.clear()
                session['user'] = user['username']
                return redirect(url_for('index'))
            flash('Incorrect username or password.', 'error')
        return render_template('login.html')

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    def location_options():
        locations = rows('SELECT * FROM locations ORDER BY name')
        by_id = {r['id']: r for r in locations}
        def path(row):
            names = [row['name']]
            while row['parent_id']:
                row = by_id[row['parent_id']]
                names.insert(0, row['name'])
            return ' / '.join(names)
        return sorted([dict(r, path=path(r)) for r in locations], key=lambda r: r['path'])

    @app.get('/')
    @app.get('/search')
    def index():
        clauses, params = [], []
        q = request.args.get('q', '').strip()
        if q:
            clauses.append('(c.name LIKE ? OR c.name_id LIKE ? OR c.description LIKE ? OR c.code LIKE ? OR c.attributes LIKE ?)')
            params.extend(['%' + q + '%'] * 5)
        for field in ('category_id', 'location_id'):
            if request.args.get(field):
                clauses.append('c.' + field + '=?')
                params.append(request.args[field])
        if request.args.get('supplier'):
            clauses.append('c.supplier=?')
            params.append(request.args['supplier'])
        if request.args.get('stock') == 'in':
            clauses.append('c.stock>0')
        elif request.args.get('stock') == 'out':
            clauses.append('c.stock=0')
        sort = {'name': 'c.name COLLATE NOCASE', 'stock_asc': 'c.stock', 'stock_desc': 'c.stock DESC', 'price': 'CAST(c.unit_price AS REAL)', 'new': 'c.id DESC'}.get(request.args.get('sort'), 'c.name COLLATE NOCASE')
        query = 'SELECT c.*,cat.name AS category,l.name AS location FROM components c LEFT JOIN categories cat ON cat.id=c.category_id LEFT JOIN locations l ON l.id=c.location_id'
        items = rows(query + (' WHERE ' + ' AND '.join(clauses) if clauses else '') + ' ORDER BY ' + sort, params)
        all_items = rows('SELECT stock,unit_price FROM components')
        return render_template('inventory.html', items=items, categories=rows('SELECT * FROM categories ORDER BY name'), locations=location_options(), suppliers=rows("SELECT DISTINCT supplier FROM components WHERE supplier!='' ORDER BY supplier"), total=len(all_items), empty=sum(r['stock']==0 for r in all_items), value=sum(Decimal(str(r['stock']))*Decimal(r['unit_price']) for r in all_items))

    def uploaded(field, current):
        file = request.files.get(field)
        if not file or not file.filename:
            return current
        ext = Path(secure_filename(file.filename)).suffix.lower()
        raw = file.read()
        if field == 'image':
            from PIL import Image, UnidentifiedImageError
            try:
                image = Image.open(io.BytesIO(raw))
                image.verify()
                if image.format not in ('PNG', 'JPEG', 'WEBP', 'GIF'):
                    raise ValueError('Use a PNG, JPEG, WebP, or GIF image.')
                ext = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp', 'GIF': '.gif'}[image.format]
            except (UnidentifiedImageError, OSError):
                raise ValueError('The image file is invalid.')
        elif ext != '.pdf' or not raw.startswith(b'%PDF-'):
            raise ValueError('Datasheet uploads must be PDF files.')
        name = secrets.token_hex(16) + ext
        (data / 'uploads' / name).write_bytes(raw)
        return '/uploads/' + name

    @app.route('/components/new', methods=['GET', 'POST'])
    @app.route('/components/<int:item_id>/edit', methods=['GET', 'POST'])
    def edit_component(item_id=None):
        item = dict(one('SELECT * FROM components WHERE id=?', (item_id,))) if item_id else {}
        if request.method == 'POST':
            f = request.form
            name = f.get('name', '').strip()
            if not name:
                raise ValueError('Name is required.')
            stock = number(f.get('stock', '0'))
            price = number(f.get('price', '0'))
            if f.get('price_mode') == 'purchase':
                quantity = number(f.get('purchase_quantity', '0'))
                if quantity <= 0:
                    raise ValueError('Purchase quantity must be greater than zero.')
                price /= quantity
            db().execute('BEGIN IMMEDIATE')
            category = f.get('category', '').strip()
            category_id = None
            if category:
                db().execute('INSERT OR IGNORE INTO categories(name) VALUES(?)', (category,))
                category_id = one('SELECT id FROM categories WHERE name=?', (category,))['id']
            values = dict(name=name, name_id=f.get('name_id', '').strip() or name, stock=float(stock), unit=f.get('unit', '').strip() or 'pcs', unit_price=str(price.quantize(Decimal('0.000001'))), description=f.get('description', '').strip(), category_id=category_id, location_id=f.get('location_id') or None, supplier=f.get('supplier', '').strip(), supplier_url=safe_url(f.get('supplier_url', '').strip()), attributes=f.get('attributes', '').strip(), code=f.get('code', '').strip() or item.get('code') or 'PART-' + secrets.token_hex(5).upper())
            if len(values['code'].encode('utf-8')) > 512:
                raise ValueError('Scan identifiers must be 512 bytes or fewer for printable codes.')
            for field in ('image', 'datasheet'):
                url = f.get(field + '_url', '').strip()
                current = item.get(field, '')
                values[field] = uploaded(field, current if url == current else safe_url(url))
            if item_id:
                result = db().execute('UPDATE components SET ' + ','.join(k+'=?' for k in values) + ',version=version+1 WHERE id=? AND version=?', (*values.values(), item_id, f.get('version')))
                if result.rowcount != 1:
                    db().rollback()
                    abort(409, 'Another device changed this component. Reload before saving.')
                delta = float(stock) - item['stock']
            else:
                result = db().execute('INSERT INTO components(' + ','.join(values) + ') VALUES(' + ','.join('?' for _ in values) + ')', tuple(values.values()))
                item_id = result.lastrowid
                delta = float(stock)
            if delta:
                db().execute('INSERT INTO movements(component_id,delta,reason) VALUES(?,?,?)', (item_id, delta, 'Component saved by ' + session['user']))
            db().commit()
            flash('Component saved.')
            return redirect(url_for('component', item_id=item_id))
        if item.get('category_id'):
            item['category'] = one('SELECT name FROM categories WHERE id=?', (item['category_id'],))['name']
        return render_template('component_form.html', item=item, categories=rows('SELECT * FROM categories ORDER BY name'), locations=location_options())

    @app.get('/components/<int:item_id>')
    def component(item_id):
        return render_template('component.html', item=one('SELECT c.*,cat.name AS category,l.name AS location FROM components c LEFT JOIN categories cat ON cat.id=c.category_id LEFT JOIN locations l ON l.id=c.location_id WHERE c.id=?', (item_id,)), movements=rows('SELECT * FROM movements WHERE component_id=? ORDER BY id DESC LIMIT 50', (item_id,)))

    @app.post('/components/<int:item_id>/stock')
    def adjust_stock(item_id):
        magnitude = number(request.form.get('quantity', '0'))
        delta = float(magnitude) * (-1 if request.form.get('direction') == 'remove' else 1)
        db().execute('BEGIN IMMEDIATE')
        item = one('SELECT stock FROM components WHERE id=?', (item_id,))
        if item['stock'] + delta < 0:
            raise ValueError('Not enough stock for that adjustment.')
        db().execute('UPDATE components SET stock=stock+?,version=version+1 WHERE id=?', (delta, item_id))
        db().execute('INSERT INTO movements(component_id,delta,reason) VALUES(?,?,?)', (item_id, delta, request.form.get('reason', '').strip() or 'Manual adjustment'))
        db().commit()
        return redirect(url_for('component', item_id=item_id))

    @app.route('/storage', methods=['GET', 'POST'])
    def storage():
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            if not name:
                raise ValueError('Storage name is required.')
            kind = request.form.get('kind')
            if kind not in ('Room', 'Closet', 'Cabinet', 'Drawer', 'Shelf', 'Bin', 'Other'):
                raise ValueError('Choose a storage type.')
            db().execute('INSERT INTO locations(name,kind,parent_id) VALUES(?,?,?)', (name, kind, request.form.get('parent_id') or None))
            db().commit()
            return redirect(url_for('storage'))
        return render_template('storage.html', locations=location_options())

    @app.route('/projects', methods=['GET', 'POST'])
    def projects():
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            if not name:
                raise ValueError('Project name is required.')
            result = db().execute('INSERT INTO projects(name,description) VALUES(?,?)', (name, request.form.get('description', '')))
            db().commit()
            return redirect(url_for('project', project_id=result.lastrowid))
        return render_template('projects.html', projects=rows('SELECT p.*,COUNT(i.component_id) AS lines FROM projects p LEFT JOIN project_items i ON i.project_id=p.id GROUP BY p.id ORDER BY p.id DESC'))

    @app.route('/projects/<int:project_id>', methods=['GET', 'POST'])
    def project(project_id):
        project = one('SELECT * FROM projects WHERE id=?', (project_id,))
        if request.method == 'POST':
            quantity = number(request.form.get('quantity', '0'))
            if quantity == 0:
                db().execute('DELETE FROM project_items WHERE project_id=? AND component_id=?', (project_id, request.form['component_id']))
            else:
                db().execute('INSERT INTO project_items(project_id,component_id,quantity) VALUES(?,?,?) ON CONFLICT(project_id,component_id) DO UPDATE SET quantity=excluded.quantity', (project_id, request.form['component_id'], float(quantity)))
            db().commit()
            return redirect(url_for('project', project_id=project_id))
        items = [dict(r) for r in rows('SELECT c.*,i.quantity FROM project_items i JOIN components c ON c.id=i.component_id WHERE i.project_id=? ORDER BY c.name', (project_id,))]
        for row in items:
            row['shortage'] = max(0, row['quantity']-row['stock'])
            row['cost'] = Decimal(str(row['quantity'])) * Decimal(row['unit_price'])
            row['buy_cost'] = Decimal(str(row['shortage'])) * Decimal(row['unit_price'])
        return render_template('project.html', project=project, items=items, components=rows('SELECT id,name,name_id FROM components ORDER BY name'), total=sum(r['cost'] for r in items), buy=sum(r['buy_cost'] for r in items))

    @app.post('/projects/<int:project_id>/consume')
    def consume(project_id):
        db().execute('BEGIN IMMEDIATE')
        one('SELECT id FROM projects WHERE id=?', (project_id,))
        items = rows('SELECT c.id,c.stock,i.quantity FROM project_items i JOIN components c ON c.id=i.component_id WHERE project_id=?', (project_id,))
        if not items or any(r['stock'] < r['quantity'] for r in items):
            raise ValueError('Every project part must be in stock before building.')
        for row in items:
            db().execute('UPDATE components SET stock=stock-?,version=version+1 WHERE id=?', (row['quantity'], row['id']))
            db().execute('INSERT INTO movements(component_id,delta,reason) VALUES(?,?,?)', (row['id'], -row['quantity'], 'Built project #' + str(project_id)))
        db().commit()
        flash('Parts deducted for one build. The project list is saved for reuse.')
        return redirect(url_for('project', project_id=project_id))

    @app.get('/labels')
    def labels():
        items = rows('SELECT * FROM components ORDER BY name')
        selected = next((r for r in items if str(r['id']) == request.args.get('item_id')), items[0] if items else None)
        width = number(request.args.get('width', '3.5'), Decimal('0.5'))
        height = number(request.args.get('height', '1.5'), Decimal('0.5'))
        size = number(request.args.get('size', '14'), 6)
        if width > 12 or height > 12 or size > 72:
            raise ValueError('Labels support 0.5–12 inches and text sizes of 6–72 points.')
        mode = request.args.get('mode', 'qr')
        font = request.args.get('font', 'sans-serif')
        if mode not in ('qr', 'barcode', 'none') or font not in ('sans-serif', 'serif', 'monospace'):
            raise ValueError('Invalid label options.')
        return render_template('labels.html', items=items, selected=selected, width=width, height=height, size=size, mode=mode, font=font, label_text=request.args.get('text', selected['name'] + ('\n' + selected['name_id'] if selected['name_id'] != selected['name'] else '') if selected else ''), copies=min(100, max(1, int(request.args.get('copies', '1')))))

    @app.get('/codes/<int:item_id>/<mode>')
    def code_image(item_id, mode):
        item = one('SELECT code FROM components WHERE id=?', (item_id,))
        out = io.BytesIO()
        if mode == 'qr':
            qrcode.make(item['code']).save(out, format='PNG')
            mime = 'image/png'
        elif mode == 'barcode':
            if any(ord(c)>127 for c in item['code']):
                raise ValueError('Code 128 requires an ASCII identifier. Use QR for Unicode.')
            barcode.get('code128', item['code']).write(out, {'write_text': False, 'quiet_zone': 3})
            mime = 'image/svg+xml'
        else:
            abort(404)
        out.seek(0)
        return send_file(out, mimetype=mime)

    @app.get('/uploads/<name>')
    def upload(name):
        if name != secure_filename(name):
            abort(404)
        path = data / 'uploads' / name
        if not path.is_file():
            abort(404)
        return send_file(path, as_attachment=path.suffix == '.pdf')

    @app.cli.command('create-user')
    def create_user():
        import click
        username = click.prompt('Username')
        password = click.prompt('Password', hide_input=True, confirmation_prompt=True)
        if len(password) < 8:
            raise click.ClickException('Use at least 8 characters.')
        db().execute('INSERT INTO users(username,password) VALUES(?,?)', (username, generate_password_hash(password)))
        db().commit()
        click.echo('User created.')

    return app
