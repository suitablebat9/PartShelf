"""Public roadmap and platform administration."""
from flask import abort, flash, redirect, render_template, request, url_for

STATES=('Planned','In progress','Released')

def install_roadmap(app,bp,db,admin,auth):
    with app.app_context():
        db().execute("CREATE TABLE IF NOT EXISTS roadmap(id INTEGER PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'Planned',position INTEGER NOT NULL DEFAULT 0,published INTEGER NOT NULL DEFAULT 1,revision INTEGER NOT NULL DEFAULT 1)")
        db().commit()

    @bp.get('/roadmap')
    def roadmap():
        return render_template('roadmap.html',states=STATES,items=db().execute('SELECT * FROM roadmap WHERE published=1 ORDER BY position,id DESC').fetchall())

    @bp.route('/management/roadmap',methods=['GET','POST'])
    @admin
    def roadmap_admin():
        if request.method=='POST':
            if request.form.get('action')=='move':
                db().execute('BEGIN IMMEDIATE')
                items=db().execute('SELECT * FROM roadmap ORDER BY position,id DESC').fetchall()
                index=next((i for i,item in enumerate(items) if str(item['id'])==request.form.get('id')),None)
                if index is None: abort(404)
                if str(items[index]['revision'])!=request.form.get('revision'): abort(409)
                direction=request.form.get('direction')
                if direction not in ('up','down'): abort(400)
                other=index+(-1 if direction=='up' else 1)
                if 0<=other<len(items):
                    items[index],items[other]=items[other],items[index]
                    for position,item in enumerate(items):
                        db().execute('UPDATE roadmap SET position=?,revision=revision+1 WHERE id=?',(position,item['id']))
                db().commit()
                return redirect(url_for('community.roadmap_admin'))
            title=request.form.get('title','').strip()
            description=request.form.get('description','').strip()
            status=request.form.get('status','Planned')
            if not title or len(title)>150 or len(description)>5000 or status not in STATES:
                raise ValueError('Enter a title up to 150 characters, description up to 5,000, and a valid status.')
            try:
                position=int(request.form.get('position','0'))
                if abs(position)>100000: raise ValueError()
            except ValueError:
                raise ValueError('Display order must be a whole number between -100000 and 100000.')
            values=(title,description,status,position,int(request.form.get('published')=='1'))
            ident=request.form.get('id')
            if ident:
                changed=db().execute('UPDATE roadmap SET title=?,description=?,status=?,position=?,published=?,revision=revision+1 WHERE id=? AND revision=?',values+(ident,request.form.get('revision'))).rowcount
                if not changed: abort(409,'This roadmap item changed. Reload before saving.')
            else:
                db().execute('INSERT INTO roadmap(title,description,status,position,published) VALUES(?,?,?,?,?)',values)
            db().commit();flash('Roadmap saved.')
            return redirect(url_for('community.roadmap_admin'))
        return render_template('roadmap_admin.html',states=STATES,items=db().execute('SELECT * FROM roadmap ORDER BY position,id DESC').fetchall())

