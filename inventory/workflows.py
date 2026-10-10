"""Workspace-scoped imports and batch actions, previewed before atomic writes."""
import csv
import hashlib
import io
import json
import os
import secrets
import time
from decimal import Decimal, ROUND_CEILING
from functools import wraps

from flask import Blueprint, abort, flash, g, redirect, render_template, request, Response, session, url_for

CSV_FIELDS = ('name','name_id','stock','unit','unit_price','category','storage','code','description','supplier','supplier_url','tags','size','resistance','capacitance','voltage','tolerance','attributes','low_stock','purchase_quantity','purchase_pack')
WRITE_ENDPOINTS = ('workflows.import_inventory','workflows.import_bom','workflows.confirm','workflows.bulk','workflows.duplicate','workflows.dismiss_setup')
DEMO_ENDPOINTS = WRITE_ENDPOINTS + ('workflows.csv_template','workflows.shopping_list','workflows.scan','workflows.help')


def csv_response(filename, headers, entries):
    def safe_cell(value):
        # Keep spreadsheet software from interpreting imported names as formulas.
        value = str(value if value is not None else '')
        return "'"+value if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t','\r','\n')) else value
    out = io.StringIO(newline='')
    writer = csv.writer(out)
    writer.writerow(headers)
    writer.writerows([[safe_cell(v) for v in row] for row in entries])
    return Response('\ufeff'+out.getvalue(), mimetype='text/csv', headers={'Content-Disposition':f'attachment; filename="{filename}"'})


def read_csv(upload, allowed, required):
    if not upload:
        raise ValueError('Choose a CSV file.')
    raw = upload.read(2*1024*1024+1)
    if len(raw)>2*1024*1024:
        raise ValueError('CSV files must be 2 MB or smaller.')
    try:
        text = raw.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(text, newline=''), strict=True)
        fields = reader.fieldnames or []
        if len(fields)!=len(set(fields)) or not set(required)<=set(fields) or set(fields)-set(allowed):
            raise ValueError('Use the template column names. Required: '+', '.join(required)+'. Unknown or duplicate columns are not accepted.')
        result=[]
        for line,row in enumerate(reader,2):
            if len(result)>=1000:
                raise ValueError('Import at most 1,000 rows at a time.')
            if None in row or None in row.values():
                raise ValueError(f'Row {line}: the number of values does not match the header.')
            if any('\x00' in value or len(value)>5000 for value in row.values()):
                raise ValueError(f'Row {line}: a field is too long or contains invalid characters.')
            if any(value.strip() for value in row.values()):
                result.append({key:value.strip() for key,value in row.items()})
        if not result:
            raise ValueError('The CSV has no component rows.')
        return result
    except (UnicodeDecodeError, csv.Error) as error:
        raise ValueError('Use a valid UTF-8 CSV file with comma-separated columns.') from error


def install_workflows(app, db, number, safe_url, location_options):
    bp=Blueprint('workflows',__name__)
    def editor(view):
        @wraps(view)
        def wrapped(*args,**kwargs):
            if not g.user or g.user['role']=='viewer': abort(403)
            return view(*args,**kwargs)
        return wrapped

    def one(sql,args=()):
        row=db().execute(sql,args).fetchone()
        if row is None: abort(404)
        return row

    def tags(value):
        names=list(dict.fromkeys(v.strip().casefold() for v in value.split(',') if v.strip()))
        if len(names)>30 or any(len(t)>60 for t in names):
            raise ValueError('Use up to 30 tags of at most 60 characters.')
        return names

    def capacity(extra=0):
        limit=500 if g.demo else int(os.environ.get('MAX_WORKSPACE_COMPONENTS','100000'))
        if db().execute('SELECT COUNT(*) FROM components').fetchone()[0]+extra>limit:
            raise ValueError('This import would exceed the workspace component limit.')

    def inventory_plan(raw):
        capacity(len(raw))
        locations={l['path']:l['id'] for l in location_options()}
        identifiers={r['name_id'] for r in db().execute('SELECT name_id FROM components')}
        codes={r['code'] for r in db().execute('SELECT code FROM components')}
        result=[]
        for line,row in enumerate(raw,2):
            try:
                name=row.get('name','')
                name_id=row.get('name_id') or name
                code=row.get('code') or name_id
                if not name or len(name)>200 or len(name_id)>200 or len(code.encode())>512:
                    raise ValueError('Enter a name/internal part number of at most 200 characters and a scan identifier of at most 512 bytes.')
                if name_id in identifiers or code in codes:
                    raise ValueError('Duplicate internal part number or scan identifier. Existing components are never overwritten.')
                identifiers.add(name_id);codes.add(code)
                stock=number(row.get('stock') or '0')
                price=number(row.get('unit_price') or '0').quantize(Decimal('0.000001'))
                qty=number(row['purchase_quantity'],Decimal('0.000001')) if row.get('purchase_quantity') else stock if stock else None
                total=number(price*qty) if qty is not None else None
                location=row.get('storage','')
                if location and location not in locations:
                    raise ValueError('Storage path not found. Create it in Storage areas, then use its full path separated by / with spaces.')
                values=dict(price_recorded=int(bool(row.get('unit_price'))),name=name,name_id=name_id,code=code,stock=float(stock),unit=row.get('unit') or 'pcs',unit_price=str(price),location_id=locations.get(location),purchase_quantity=str(qty) if qty is not None else None,purchase_total=str(total) if total is not None else None,price_mode='unit',purchase_pack=str(number(row.get('purchase_pack') or '1',Decimal('0.000001'))),low_stock=str(number(row['low_stock'])) if row.get('low_stock') else None)
                for field in ('description','supplier','attributes','size','resistance','capacitance','voltage','tolerance'):
                    values[field]=row.get(field,'')
                values['supplier_url']=safe_url(row.get('supplier_url',''))
                category=row.get('category','')
                if len(category)>120: raise ValueError('Category names must be at most 120 characters.')
                result.append(dict(values=values,category=category,tags=tags(row.get('tags','')),storage=location))
            except ValueError as error:
                raise ValueError(f'Row {line}: {error}') from error
        return result

    def bom_plan(raw,project_id,mode):
        one('SELECT id FROM projects WHERE id=?',(project_id,))
        if mode not in ('merge','replace'): raise ValueError('Choose how to import quantities.')
        grouped={}
        for line,row in enumerate(raw,2):
            item=db().execute('SELECT id,name FROM components WHERE name_id=?',(row['name_id'],)).fetchone()
            if not item: raise ValueError(f"Row {line}: internal part number {row['name_id']} was not found. Import or create that component first.")
            qty=number(row['quantity'],Decimal('0.000001'))
            grouped.setdefault(item['id'],dict(id=item['id'],name=item['name'],name_id=row['name_id'],quantity=Decimal(0)))['quantity']+=qty
        existing=[dict(r) for r in db().execute('SELECT component_id,quantity FROM project_items WHERE project_id=? ORDER BY component_id',(project_id,))]
        current={r['component_id']:r['quantity'] for r in existing}
        for item in grouped.values():
            item['quantity']=float(number(item['quantity'],Decimal('0.000001')))
            item['current']=current.get(item['id'],0)
        return dict(items=list(grouped.values()),existing=existing,mode=mode,project_id=project_id)

    def actor():
        return hashlib.sha256((str(g.user['id'])+':'+session['csrf']).encode()).hexdigest()

    def stage(kind, source, plan, destination):
        token=secrets.token_urlsafe(32)
        db().execute('DELETE FROM workflow_previews WHERE expires<?',(int(time.time()),))
        # Keep only the latest preview per signed-in browser.
        db().execute('DELETE FROM workflow_previews WHERE actor=?',(actor(),))
        db().execute('INSERT INTO workflow_previews(token,actor,kind,payload,expires) VALUES(?,?,?,?,?)',(token,actor(),kind,json.dumps(dict(source=source,plan=plan,destination=destination)),int(time.time())+1800))
        db().commit()
        return redirect(url_for('workflows.confirm',token=token))

    @bp.get('/imports/template/<kind>.csv')
    def csv_template(kind):
        if kind=='inventory':
            example={field:'' for field in CSV_FIELDS}
            example.update(name='10k resistor',name_id='R-10K-0603',stock='100',unit='pcs',unit_price='0.02',category='Resistors',resistance='10 kΩ',size='0603',purchase_pack='100',purchase_quantity='100',tags='resistor, passive')
            return csv_response('partshelf-inventory-template.csv',CSV_FIELDS,[[example[f] for f in CSV_FIELDS]])
        if kind=='bom': return csv_response('partshelf-bom-template.csv',('name_id','quantity'),[('R-10K-0603',4)])
        abort(404)

    @bp.route('/inventory/import',methods=['GET','POST'])
    @editor
    def import_inventory():
        error=None
        if request.method=='POST':
            try:
                raw=read_csv(request.files.get('file'),CSV_FIELDS,('name',))
                return stage('inventory',raw,inventory_plan(raw),url_for('index'))
            except ValueError as exc: error=str(exc)
        return render_template('import_csv.html',kind='inventory',error=error,project=None),400 if error else 200

    @bp.route('/projects/<int:project_id>/import',methods=['GET','POST'])
    @editor
    def import_bom(project_id):
        project=one('SELECT * FROM projects WHERE id=?',(project_id,))
        error=None
        if request.method=='POST':
            try:
                raw=read_csv(request.files.get('file'),('name_id','quantity'),('name_id','quantity'))
                mode=request.form.get('mode','merge')
                return stage('bom',raw,bom_plan(raw,project_id,mode),url_for('project',project_id=project_id))
            except ValueError as exc: error=str(exc)
        return render_template('import_csv.html',kind='bom',error=error,project=project),400 if error else 200

    def bulk_plan(source):
        ids=source['ids']
        if not ids or len(ids)>500 or not all(str(i).isdigit() for i in ids): raise ValueError('Select between 1 and 500 components.')
        items=[dict(r) for r in db().execute('SELECT id,name,stock,unit,version,location_id FROM components WHERE id IN ('+','.join('?' for _ in ids)+') ORDER BY id',ids)]
        if len(items)!=len(ids): raise ValueError('A selected component no longer exists in this workspace.')
        action=source['action']
        if action not in ('move','tag_add','tag_remove','stock_add','stock_remove'): raise ValueError('Choose a bulk action.')
        plan=dict(items=items,action=action)
        if action=='move':
            location=source.get('location_id')
            if location: one('SELECT id FROM locations WHERE id=?',(location,))
            plan['location_id']=int(location) if location else None
            plan['location_name']=next((l['path'] for l in location_options() if l['id']==plan['location_id']),'Unassigned')
        elif action.startswith('tag_'):
            plan['tags']=tags(source.get('tags',''))
            if not plan['tags']: raise ValueError('Enter at least one tag.')
            for item in items:
                current={r['name'] for r in db().execute('SELECT t.name FROM tags t JOIN component_tags ct ON ct.tag_id=t.id WHERE ct.component_id=?',(item['id'],))}
                item['tags']=sorted(current)
                if action=='tag_add' and len(current|set(plan['tags']))>30: raise ValueError('One of these parts would have more than 30 tags.')
        else:
            qty=number(source.get('quantity',''),Decimal('0.000001'))
            plan['quantity']=str(qty)
            plan['reason']=source.get('reason','').strip()[:500] or 'Bulk stock adjustment'
            for item in items:
                result=Decimal(str(item['stock']))+(qty if action=='stock_add' else -qty)
                if result<0: raise ValueError(f"Not enough stock for {item['name']}. Nothing was changed.")
                item['result']=float(number(result))
        return plan

    @bp.post('/inventory/bulk')
    @editor
    def bulk():
        source={key:request.form.get(key,'') for key in ('action','location_id','tags','quantity','reason')}
        source['ids']=list(dict.fromkeys(request.form.getlist('component_ids')))
        try:
            return stage('bulk',source,bulk_plan(source),url_for('index'))
        except ValueError as error:
            flash(str(error),'error')
            return redirect(url_for('index'))

    def assign_tags(component_id,names,remove=False):
        for name in names:
            if remove:
                db().execute('DELETE FROM component_tags WHERE component_id=? AND tag_id IN (SELECT id FROM tags WHERE name=?)',(component_id,name))
            else:
                db().execute('INSERT OR IGNORE INTO tags(name) VALUES(?)',(name,))
                tag_id=one('SELECT id FROM tags WHERE name=?',(name,))['id']
                db().execute('INSERT OR IGNORE INTO component_tags VALUES(?,?)',(component_id,tag_id))

    @bp.route('/tools/confirm/<token>',methods=['GET','POST'])
    @editor
    def confirm(token):
        if request.method=='POST': db().execute('BEGIN IMMEDIATE')
        staged=one('SELECT * FROM workflow_previews WHERE token=? AND actor=? AND expires>?',(token,actor(),int(time.time())))
        payload=json.loads(staged['payload']);plan=payload['plan'];kind=staged['kind']
        if request.method=='POST':
            try:
                if request.form.get('confirmed')!='yes': raise ValueError('Confirm the preview before applying it.')
                fresh=inventory_plan(payload['source']) if kind=='inventory' else bom_plan(payload['source'],plan['project_id'],plan['mode']) if kind=='bom' else bulk_plan(payload['source'])
                if fresh!=plan: raise ValueError('The selected data changed after this preview. Cancel and preview again before applying.')
                if kind=='inventory':
                    for item in plan:
                        values=dict(item['values']);category=item['category']
                        if category:
                            db().execute('INSERT OR IGNORE INTO categories(name) VALUES(?)',(category,))
                            values['category_id']=one('SELECT id FROM categories WHERE name=?',(category,))['id']
                        component_id=db().execute('INSERT INTO components('+','.join(values)+') VALUES('+','.join('?' for _ in values)+')',tuple(values.values())).lastrowid
                        assign_tags(component_id,item['tags'])
                        if values['stock']: db().execute('INSERT INTO movements(component_id,delta,reason) VALUES(?,?,?)',(component_id,values['stock'],'CSV import by '+g.user['username']))
                elif kind=='bom':
                    if plan['mode']=='replace': db().execute('DELETE FROM project_items WHERE project_id=?',(plan['project_id'],))
                    for item in plan['items']:
                        db().execute('INSERT INTO project_items VALUES(?,?,?) ON CONFLICT(project_id,component_id) DO UPDATE SET quantity=excluded.quantity',(plan['project_id'],item['id'],item['quantity']))
                else:
                    for item in plan['items']:
                        action=plan['action']
                        if action=='move': db().execute('UPDATE components SET location_id=?,version=version+1 WHERE id=?',(plan['location_id'],item['id']))
                        elif action.startswith('tag_'):
                            assign_tags(item['id'],plan['tags'],action=='tag_remove')
                            db().execute('UPDATE components SET version=version+1 WHERE id=?',(item['id'],))
                        else:
                            db().execute('UPDATE components SET stock=?,version=version+1 WHERE id=?',(item['result'],item['id']))
                            db().execute('INSERT INTO movements(component_id,delta,reason) VALUES(?,?,?)',(item['id'],item['result']-item['stock'],plan['reason']))
                db().execute('DELETE FROM workflow_previews WHERE token=?',(token,))
                db().commit()
            except ValueError as error:
                db().rollback()
                return render_template('workflow_preview.html',kind=kind,plan=plan,token=token,destination=payload['destination'],error=str(error)),409
            flash('Import applied.' if kind in ('inventory','bom') else 'Selected components updated.')
            return redirect(payload['destination'])
        return render_template('workflow_preview.html',kind=kind,plan=plan,token=token,destination=payload['destination'])

    @bp.post('/projects/<int:project_id>/duplicate')
    @editor
    def duplicate(project_id):
        db().execute('BEGIN IMMEDIATE')
        project=one('SELECT * FROM projects WHERE id=?',(project_id,))
        if db().execute('SELECT COUNT(*) FROM projects').fetchone()[0]>=(100 if g.demo else 10000): raise ValueError('Workspace project limit reached.')
        name=request.form.get('name','').strip() or project['name'][:140]+' (copy)'
        if len(name)>150: raise ValueError('Use a project name of at most 150 characters.')
        new_id=db().execute('INSERT INTO projects(name,description) VALUES(?,?)',(name,project['description'])).lastrowid
        db().execute('INSERT INTO project_items SELECT ?,component_id,quantity FROM project_items WHERE project_id=?',(new_id,project_id))
        db().commit();flash('Project duplicated. Stock and build history were not copied or changed.')
        return redirect(url_for('project',project_id=new_id))

    @bp.get('/projects/<int:project_id>/shopping-list')
    def shopping_list(project_id):
        project=one('SELECT * FROM projects WHERE id=?',(project_id,))
        builds=number(request.args.get('builds','1'),1)
        if builds>10000 or builds!=builds.to_integral_value(): raise ValueError('Choose a whole number of builds from 1 to 10,000.')
        items=[]
        for row in db().execute('SELECT c.*,i.quantity FROM components c JOIN project_items i ON i.component_id=c.id WHERE i.project_id=? ORDER BY c.supplier COLLATE NOCASE,c.name',(project_id,)):
            shortage=max(Decimal(0),Decimal(str(row['quantity']))*builds-Decimal(str(row['stock'])))
            if not shortage: continue
            pack=Decimal(row['purchase_pack']);price=Decimal(row['unit_price'])
            packs=(shortage/pack).to_integral_value(rounding=ROUND_CEILING)
            items.append(dict(row,shortage=shortage,packs=packs,purchase_units=packs*pack,exact_cost=shortage*price,pack_cost=packs*pack*price))
        if request.args.get('download')=='csv':
            headers=('supplier','name','name_id','shortage','unit','unit_price_usd','exact_cost_usd','packs','units_per_pack','purchase_units','package_cost_usd','supplier_url')
            return csv_response(f'partshelf-project-{project_id}-shopping.csv',headers,[[i['supplier'],i['name'],i['name_id'],i['shortage'],i['unit'],i['unit_price'],i['exact_cost'],i['packs'],i['purchase_pack'],i['purchase_units'],i['pack_cost'],i['supplier_url']] for i in items])
        return render_template('shopping_list.html',project=project,items=items,builds=int(builds),total=sum(i['pack_cost'] for i in items))

    @bp.post('/help/dismiss-setup')
    @editor
    def dismiss_setup():
        db().execute("INSERT OR REPLACE INTO workspace_milestones(key) VALUES('setup_hidden')")
        db().commit()
        return redirect(url_for('index'))

    @bp.get('/scan')
    def scan(): return render_template('scan.html')

    @bp.get('/help')
    def help(): return render_template('help.html')

    app.register_blueprint(bp)
