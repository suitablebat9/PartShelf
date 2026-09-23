"""A separate, read-only sample inventory. No demo user exists in the account registry."""
import sqlite3
from decimal import Decimal
from pathlib import Path
from flask import abort, g, redirect, render_template, request, session, url_for
from .migrations import migrate


def install_demo(app, schema):
    path = (Path(app.config['DATA_DIR']) / 'demo.sqlite3').resolve()
    with sqlite3.connect(path, timeout=30) as db:
        db.executescript(schema)
        migrate(db)
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM components').fetchone():
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
        db.commit()

    def connect():
        conn = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        return conn

    @app.route('/demo', methods=['GET','POST'])
    def demo():
        if request.method=='POST':
            session['demo']=True
            return redirect(url_for('index'))
        return render_template('demo.html')

    @app.post('/demo/exit')
    def demo_exit():
        session.pop('demo',None)
        return redirect(url_for('index') if session.get('sid') else url_for('login'))

    def protect():
        g.demo=False
        if not session.get('demo'):
            return
        # Leaving the demo for authentication must never carry the synthetic identity.
        public = {'login','logout','demo','demo_exit','manage.register','manage.verify_registration','manage.google_registration','manage.forgot_password','manage.reset_password','manage.accept_invite','auth.google_login','auth.google_callback','auth.passkey_options','auth.passkey_verify','auth.mfa_login'}
        if request.endpoint in public:
            if request.endpoint not in ('demo','demo_exit'):
                session.pop('demo',None)
            return
        allowed={'index','component','storage','projects','project','labels','labels_pdf','code_image'}
        g.demo=True
        g.user={'id':0,'username':'demo','workspace_id':0,'role':'viewer','platform_admin':0}
        g.workspace={'id':0,'name':'Partshelf demo'}
        g.auth_session=None
        if request.endpoint not in allowed or (request.method not in ('GET','HEAD') and not (request.method=='POST' and request.endpoint=='labels_pdf')):
            abort(403, 'This demo is read-only. Create a workspace to save your own inventory.')

    return {'connect':connect,'protect':protect}
