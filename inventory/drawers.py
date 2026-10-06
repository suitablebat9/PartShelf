"""Workspace-scoped XY cabinets and explicitly authorized device transport."""
import base64
import hashlib
import json
import math
import os
import uuid
from urllib.parse import urlsplit
import requests
from cryptography.fernet import Fernet
from flask import Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request


def migrate_drawers(db):
    db.execute('''CREATE TABLE IF NOT EXISTS cabinets(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, location_id INTEGER NOT NULL REFERENCES locations(id),
        row_count INTEGER NOT NULL DEFAULT 16, section_gap REAL NOT NULL DEFAULT 0,
        endpoint TEXT NOT NULL DEFAULT '', api_key TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 0,
        x_origin REAL NOT NULL DEFAULT 0, y_origin REAL NOT NULL DEFAULT 0,
        x_pitch REAL NOT NULL DEFAULT 40, y_pitch REAL NOT NULL DEFAULT 40,
        servo_closed INTEGER NOT NULL DEFAULT 0, servo_open INTEGER NOT NULL DEFAULT 90,
        light_seconds INTEGER NOT NULL DEFAULT 15)''')
    db.execute('''CREATE TABLE IF NOT EXISTS cabinet_drawers(
        cabinet_id INTEGER NOT NULL REFERENCES cabinets(id), row INTEGER NOT NULL, col INTEGER NOT NULL,
        location_id INTEGER UNIQUE NOT NULL REFERENCES locations(id), PRIMARY KEY(cabinet_id,row,col))''')
    db.execute('''CREATE TABLE IF NOT EXISTS cabinet_commands(
        id TEXT PRIMARY KEY, cabinet_id INTEGER NOT NULL REFERENCES cabinets(id), action TEXT NOT NULL,
        row INTEGER, col INTEGER, status TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
        actor INTEGER NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS one_cabinet_command ON cabinet_commands(cabinet_id) WHERE active=1')


def normalized_endpoint(value):
    p = urlsplit(value)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ('', '/'):
        raise ValueError('Use an HTTP or HTTPS device address without a path or credentials.')
    _ = p.port
    return value.rstrip('/')


def allowed_endpoints():
    # Operator grants each workspace specific destinations; public registrants cannot probe the LAN.
    mapping = current_app.config.get('DEVICE_ENDPOINTS', {})
    return [normalized_endpoint(v) for v in mapping.get(str(g.workspace['id']), [])]


def cipher():
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(current_app.secret_key.encode()).digest()))


def device_request(cabinet, method, path, payload=None):
    if cabinet['endpoint'] not in allowed_endpoints():
        raise ValueError('This device address has not been authorized for your workspace.')
    key = cipher().decrypt(cabinet['api_key'].encode()).decode()
    with requests.Session() as session:
        session.trust_env = False
        response = session.request(method, cabinet['endpoint'] + path, json=payload,
                                   headers={'Authorization': 'Bearer ' + key}, timeout=(3, 5),
                                   allow_redirects=False, stream=True)
        try:
            if response.status_code not in (200, 202):
                raise ValueError('Device did not acknowledge the command.')
            data = bytearray()
            for chunk in response.iter_content(1024):
                data.extend(chunk)
                if len(data) > 8192:
                    raise ValueError('Device response is too large.')
            return json.loads(data)
        finally:
            response.close()


def install_drawers(app, db):
    app.config.setdefault('DEVICE_ENDPOINTS', json.loads(os.environ.get('PARTSHELF_DEVICE_ENDPOINTS', '{}')))
    bp = Blueprint('drawers', __name__)

    def access(configure=False):
        if g.demo:
            abort(403, 'Device controls are unavailable in the public demo.')
        if request.method == 'POST' and (g.user['role'] == 'viewer' or configure and g.user['role'] not in ('owner', 'admin')):
            abort(403)

    def cabinet(cid):
        row = db().execute('SELECT * FROM cabinets WHERE id=?', (cid,)).fetchone()
        if row is None: abort(404)
        return row

    def command_result(cid, result):
        if not isinstance(result, dict) or result.get('command_id') != cid or result.get('status') not in ('accepted', 'running', 'completed', 'failed'):
            raise ValueError('Invalid device acknowledgment.')
        status = result['status']
        db().execute('UPDATE cabinet_commands SET status=?,active=?,updated=CURRENT_TIMESTAMP WHERE id=? AND active=1',
                     (status, int(status not in ('completed', 'failed')), cid))
        db().commit()
        return status

    @bp.route('/drawers', methods=['GET', 'POST'])
    def index():
        access(configure=True)
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            if not name or len(name) > 100: raise ValueError('Enter a cabinet name of up to 100 characters.')
            db().execute('BEGIN IMMEDIATE')
            if db().execute('SELECT COUNT(*) FROM cabinets').fetchone()[0] >= 20:
                raise ValueError('Up to 20 cabinets are supported per workspace.')
            row_count = int(request.form.get('rows', '16'))
            if row_count not in (8,16): raise ValueError('Choose one or two stacked sections.')
            loc = db().execute("INSERT INTO locations(name,kind) VALUES(?,'Cabinet')", (name,)).lastrowid
            cid = db().execute('INSERT INTO cabinets(name,location_id,row_count) VALUES(?,?,?)', (name, loc,row_count)).lastrowid
            for row in range(1, row_count+1):
                for col in range(1, 9):
                    lid = db().execute("INSERT INTO locations(name,kind,parent_id) VALUES(?,'Drawer',?)", (f'{chr(64+row)}{col}', loc)).lastrowid
                    db().execute('INSERT INTO cabinet_drawers VALUES(?,?,?,?)', (cid, row, col, lid))
            db().commit()
            return redirect(f'/drawers/{cid}')
        return render_template('drawers.html', cabinets=db().execute('SELECT * FROM cabinets ORDER BY name').fetchall())

    @bp.get('/drawers/<int:cid>')
    def detail(cid):
        access()
        item = cabinet(cid)
        slots = []
        for slot in db().execute('SELECT * FROM cabinet_drawers WHERE cabinet_id=? ORDER BY row,col', (cid,)):
            slots.append(dict(slot, label=f'{chr(64+slot["row"])}{slot["col"]}', parts=[dict(p) for p in db().execute('SELECT id,name,name_id,stock,unit FROM components WHERE location_id=? ORDER BY name', (slot['location_id'],))]))
        active = db().execute('SELECT * FROM cabinet_commands WHERE cabinet_id=? AND active=1', (cid,)).fetchone()
        history = db().execute('SELECT * FROM cabinet_commands WHERE cabinet_id=? ORDER BY created DESC,rowid DESC LIMIT 10', (cid,)).fetchall()
        return render_template('drawer_cabinet.html', cabinet=item, slots=slots, active=active, history=history,
            endpoints=allowed_endpoints(), components=db().execute('SELECT id,name,name_id FROM components ORDER BY name').fetchall())

    @bp.post('/drawers/<int:cid>/settings')
    def settings(cid):
        access(configure=True)
        item = cabinet(cid)
        endpoint = request.form.get('endpoint', '')
        if endpoint and endpoint not in allowed_endpoints(): raise ValueError('Choose an authorized device address.')
        key = request.form.get('api_key', '')
        if key and (len(key) < 16 or len(key) > 256 or any(ord(c) < 33 or ord(c) > 126 for c in key)):
            raise ValueError('Use a device API key of 16–256 printable characters without spaces.')
        encrypted = cipher().encrypt(key.encode()).decode() if key else item['api_key']
        if endpoint != item['endpoint'] and not key: encrypted = ''
        enabled = request.form.get('enabled') == '1'
        if enabled and (not endpoint or not encrypted): raise ValueError('Set the device address and API key before enabling controls.')
        values = []
        for field in ('x_origin', 'y_origin', 'x_pitch', 'y_pitch', 'section_gap'):
            v = float(request.form.get(field, 'nan'))
            if not math.isfinite(v) or abs(v) > 10000 or field.endswith('pitch') and v == 0:
                raise ValueError('Enter finite positions and nonzero spacing within ±10,000 mm.')
            values.append(v)
        for field, low, high in [('servo_closed',0,180),('servo_open',0,180),('light_seconds',1,120)]:
            v = int(request.form.get(field, '-1'))
            if not low <= v <= high: raise ValueError('Check servo angles (0–180°) and light duration (1–120 seconds).')
            values.append(v)
        db().execute('BEGIN IMMEDIATE')
        if db().execute('SELECT 1 FROM cabinet_commands WHERE cabinet_id=? AND active=1', (cid,)).fetchone():
            abort(409, 'Resolve the active command before changing device settings.')
        if endpoint and db().execute('SELECT 1 FROM cabinets WHERE endpoint=? AND id!=?', (endpoint,cid)).fetchone():
            raise ValueError('This controller is already assigned to a cabinet.')
        db().execute('UPDATE cabinets SET endpoint=?,api_key=?,enabled=?,x_origin=?,y_origin=?,x_pitch=?,y_pitch=?,section_gap=?,servo_closed=?,servo_open=?,light_seconds=? WHERE id=?',
                     (endpoint,encrypted,int(enabled),*values,cid))
        db().commit(); flash('Cabinet settings saved.')
        return redirect(f'/drawers/{cid}')

    @bp.post('/drawers/<int:cid>/assign')
    def assign(cid):
        access(); cabinet(cid)
        slot = db().execute('SELECT * FROM cabinet_drawers WHERE cabinet_id=? AND row=? AND col=?', (cid,request.form.get('row'),request.form.get('col'))).fetchone()
        if not slot: abort(404)
        component_id = request.form.get('component_id')
        if request.form.get('remove') == '1':
            changed = db().execute('UPDATE components SET location_id=NULL,version=version+1 WHERE id=? AND location_id=?', (component_id,slot['location_id'])).rowcount
        else:
            changed = db().execute('UPDATE components SET location_id=?,version=version+1 WHERE id=?', (slot['location_id'],component_id)).rowcount
        if not changed: abort(404)
        db().commit()
        return redirect(f'/drawers/{cid}?slot={slot["row"]}-{slot["col"]}')

    @bp.post('/drawers/<int:cid>/command')
    def send(cid):
        access()
        action = request.form.get('action')
        if action not in ('light','open'): abort(400)
        if action == 'open' and request.form.get('confirmed') != '1': abort(400)
        db().execute('BEGIN IMMEDIATE')
        item = cabinet(cid)
        slot = db().execute('SELECT * FROM cabinet_drawers WHERE cabinet_id=? AND row=? AND col=?', (cid, request.form.get('row'),request.form.get('col'))).fetchone()
        if not slot: abort(404)
        if not item['enabled'] or item['endpoint'] not in allowed_endpoints(): abort(409, 'Device controls are not configured and enabled.')
        if db().execute('SELECT 1 FROM cabinet_commands WHERE cabinet_id=? AND active=1', (cid,)).fetchone(): abort(409, 'A command is already active. Check its status first.')
        command_id = str(uuid.uuid4())
        payload = dict(protocol='partshelf-drawers-v1', command_id=command_id, action=action,
            drawer=dict(row=slot['row'],column=slot['col'],label=f'{chr(64+slot["row"])}{slot["col"]}'),
            position_mm=dict(x=item['x_origin']+(slot['col']-1)*item['x_pitch'],y=item['y_origin']+(slot['row']-1)*item['y_pitch']+(item['section_gap'] if slot['row']>8 else 0)),
            servo=dict(closed_degrees=item['servo_closed'],open_degrees=item['servo_open']),light_seconds=item['light_seconds'])
        db().execute('INSERT INTO cabinet_commands(id,cabinet_id,action,row,col,status,actor) VALUES(?,?,?,?,?,?,?)',
                     (command_id,cid,action,slot['row'],slot['col'],'sending',g.user['id']))
        db().commit()
        try:
            status = command_result(command_id, device_request(item,'POST','/api/commands',payload))
        except (requests.RequestException, ValueError):
            status = 'unknown'
            db().execute("UPDATE cabinet_commands SET status='unknown',updated=CURRENT_TIMESTAMP WHERE id=? AND active=1", (command_id,));db().commit()
        return jsonify(command_id=command_id,status=status), 202

    @bp.get('/drawers/<int:cid>/status/<command_id>')
    def status(cid, command_id):
        access(); item = cabinet(cid)
        command = db().execute('SELECT * FROM cabinet_commands WHERE cabinet_id=? AND id=?', (cid,command_id)).fetchone()
        if not command: abort(404)
        state = command['status']
        if command['active']:
            try: state = command_result(command_id,device_request(item,'GET','/api/commands/'+command_id))
            except (requests.RequestException, ValueError): state = 'unknown'
        return jsonify(command_id=command_id,status=state)

    @bp.post('/drawers/<int:cid>/resolve')
    def resolve(cid):
        access(configure=True); cabinet(cid)
        if request.form.get('confirmed') != '1': abort(400)
        db().execute("UPDATE cabinet_commands SET status='manually resolved',active=0,updated=CURRENT_TIMESTAMP WHERE cabinet_id=? AND id=? AND active=1", (cid,request.form.get('command_id')))
        db().commit();flash('Command cleared. No request was sent to the device.')
        return redirect(f'/drawers/{cid}')

    app.register_blueprint(bp)
