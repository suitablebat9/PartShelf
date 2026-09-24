"""Shared sample inventory with serialized writes and an automatic 48-hour reset."""
import fcntl
import sqlite3
import secrets
import time
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from flask import abort, g, redirect, render_template, request, session, url_for
from .migrations import migrate

RESET_SECONDS = 48 * 3600


def seed(db):
    db.executemany('INSERT INTO categories(id,name) VALUES(?,?)', [(1,'Resistors'),(2,'Capacitors'),(3,'Microcontrollers'),(4,'Connectors'),(5,'Regulators')])
    db.executemany('INSERT INTO locations(id,name,kind,parent_id) VALUES(?,?,?,?)', [(1,'Electronics lab','Room',None),(2,'Component cabinet','Cabinet',1),(3,'Passive components','Drawer',2),(4,'Development boards','Shelf',1),(5,'Connectors & power','Drawer',2)])
    samples = [
        ('10kΩ resistor','RES-10K-0603',1,3,250,'0.02','0603','10kΩ','','50V','1%'),
        ('1kΩ resistor','RES-1K-0805',1,3,120,'0.03','0805','1kΩ','','100V','1%'),
        ('220Ω resistor','RES-220-0603',1,3,8,'0.02','0603','220Ω','','50V','5%'),
        ('100nF ceramic capacitor','CAP-100N-0603',2,3,180,'0.04','0603','','100nF','50V','10%'),
        ('10µF ceramic capacitor','CAP-10U-0805',2,3,45,'0.12','0805','','10µF','25V','10%'),
        ('470µF electrolytic capacitor','CAP-470U',2,3,0,'0.35','Radial','','470µF','25V','20%'),
        ('ESP32 development board','DEV-ESP32',3,4,12,'5.90','Dev board','','','3.3V',''),
        ('USB-C connector','CON-USB-C',4,5,30,'0.65','USB-C','','','5V',''),
        ('3.3V regulator','REG-AMS1117',5,5,24,'0.18','SOT-223','','','3.3V',''),
        ('2×5 pin header','CON-HDR-2X5',4,5,60,'0.15','2.54mm','','','',''),
    ]
    for i, item in enumerate(samples,1):
        name, code, cat, loc, stock, price, size, resistance, capacitance, voltage, tolerance = item
        db.execute('INSERT INTO components(id,name,name_id,code,description,category_id,location_id,stock,unit_price,size,resistance,capacitance,voltage,tolerance,supplier,purchase_quantity,purchase_total,low_stock) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (i,name,code,code,'Sample component for the Partshelf demo.',cat,loc,stock,price,size,resistance,capacitance,voltage,tolerance,'Digi-Key' if i%2 else 'Mouser','100',str(Decimal(price)*100),'10'))
        db.execute('INSERT INTO movements(component_id,delta,reason) VALUES(?,?,?)',(i,stock,'Demo starting stock'))
    db.executemany('INSERT INTO tags(id,name) VALUES(?,?)',[(1,'Prototype'),(2,'SMD'),(3,'Power'),(4,'IoT')])
    db.executemany('INSERT INTO component_tags VALUES(?,?)',[(1,1),(1,2),(2,2),(3,2),(4,2),(5,3),(7,1),(7,4),(9,3)])
    db.executemany('INSERT INTO projects(id,name,description) VALUES(?,?,?)',[(1,'Wi-Fi environmental sensor','Prototype bill of materials with stock availability and cost estimates.'),(2,'Bench power supply','A sample project showing parts that still need to be purchased.')])
    db.executemany('INSERT INTO project_items VALUES(?,?,?)',[(1,1,4),(1,4,2),(1,7,1),(1,8,1),(2,6,2),(2,9,1),(2,10,2)])


def install_demo(app, schema):
    path = (Path(app.config['DATA_DIR']) / 'demo.sqlite3').resolve()
    upload_root = Path(app.config['DATA_DIR']) / 'demo' / 'uploads'
    upload_root.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix('.lock')

    def lock():
        handle = lock_path.open('a')
        fcntl.flock(handle, fcntl.LOCK_EX)
        return handle

    with lock() as handle, sqlite3.connect(path, timeout=30) as db:
        db.executescript(schema)
        migrate(db)
        db.execute('CREATE TABLE IF NOT EXISTS demo_state(id INTEGER PRIMARY KEY CHECK(id=1),reset_at INTEGER NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM components').fetchone():
            seed(db)
        db.execute('INSERT OR IGNORE INTO demo_state VALUES(1,?)',(int(time.time())+RESET_SECONDS,))
        db.commit()

    def reset_if_due():
        with sqlite3.connect(path, timeout=30) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            reset_at=db.execute('SELECT reset_at FROM demo_state WHERE id=1').fetchone()[0]
            expired=time.time()>=reset_at
            if expired:
                for table in ('stock_alerts','project_items','movements','component_tags','components','projects','tags','locations','categories'):
                    db.execute('DELETE FROM '+table)
                seed(db)
                reset_at=int(time.time())+RESET_SECONDS
                db.execute('UPDATE demo_state SET reset_at=? WHERE id=1',(reset_at,))
                for file in upload_root.iterdir():
                    if file.is_file() or file.is_symlink():
                        file.unlink()
            db.commit()
            if expired:
                db.execute('VACUUM')
        return reset_at

    def connect():
        conn = sqlite3.connect(path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

    @app.cli.command('reset-demo')
    def reset_demo_command():
        with lock():
            reset_if_due()

    @app.teardown_request
    def unlock_demo(error=None):
        # Close/rollback the inventory connection before another visitor can reset it.
        if getattr(g,'demo_lock',None):
            connection=g.pop('inventory_db',None)
            if connection is not None:
                connection.close()
            g.pop('demo_lock').close()

    @app.route('/demo', methods=['GET','POST'])
    def demo():
        if request.method=='POST':
            with lock():
                session['demo_generation']=reset_if_due()
            session['demo']=True
            return redirect(url_for('index'))
        return render_template('demo.html')

    @app.post('/demo/exit')
    def demo_exit():
        session.pop('demo',None)
        session.pop('demo_generation',None)
        return redirect(url_for('index') if session.get('sid') else url_for('login'))

    def protect():
        g.demo=False
        if not session.get('demo'):
            return
        public = {'login','logout','demo','demo_exit','manage.register','manage.verify_registration','manage.google_registration','manage.forgot_password','manage.reset_password','manage.accept_invite','auth.google_login','auth.google_callback','auth.passkey_options','auth.passkey_verify','auth.mfa_login'}
        if request.endpoint in public:
            if request.endpoint not in ('demo','demo_exit'):
                session.pop('demo',None)
                session.pop('demo_generation',None)
            return
        allowed={'index','component','edit_component','adjust_stock','storage','projects','project','consume','labels','labels_pdf','code_image','upload'}
        g.demo=True
        g.user={'id':0,'username':'demo','workspace_id':0,'role':'member','platform_admin':0}
        g.workspace={'id':0,'name':'Partshelf demo'}
        g.auth_session=None
        if request.endpoint not in allowed:
            abort(403, 'Create your own workspace to use account and administration settings.')
        g.demo_lock=lock()
        reset_at=reset_if_due()
        g.demo_reset=datetime.fromtimestamp(reset_at,timezone.utc).strftime('%b %d, %H:%M UTC')
        previous=session.get('demo_generation')
        session['demo_generation']=reset_at
        if previous is not None and previous!=reset_at:
            session['csrf']=secrets.token_hex(32)
        if request.method=='POST':
            if previous!=reset_at:
                abort(409,'The demo has reset. Reload the page before saving changes.')
            app.extensions['partshelf_auth']['limit']('demo-write:'+str(request.remote_addr),120,3600)
            with connect() as db:
                if request.endpoint=='edit_component' and not request.view_args.get('item_id') and db.execute('SELECT COUNT(*) FROM components').fetchone()[0]>=500:
                    raise ValueError('The demo is full. Create a workspace or wait for the next reset.')
                for endpoint,table,maximum in (('storage','locations',100),('projects','projects',100)):
                    if request.endpoint==endpoint and db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]>=maximum:
                        raise ValueError('The demo is full. Create a workspace or wait for the next reset.')

    return {'connect':connect,'protect':protect,'path':path}
