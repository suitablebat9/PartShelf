"""Per-user appearance and permission-filtered sidebar preferences."""
import json
from flask import g, request, render_template, redirect, flash, abort

THEMES = [('default','Partshelf blue'),('forest','Forest green'),('violet','Violet'),('amber','Warm amber'),('slate','Slate')]
NAV = [('inventory','Inventory','/','▤'),('projects','Projects','/projects','▱'),('storage','Storage areas','/storage','▥'),('labels','Label studio','/labels','▧'),('management','Team management','/management','▦'),('analytics','Analytics','/management/analytics','▥'),('feedback','Feedback & ideas','/feedback','♡'),('inbox','Feedback inbox','/management/feedback','✉'),('roadmap','Edit roadmap','/management/roadmap','▱')]

def install_preferences(app,db):
    with app.app_context():
        db().execute('CREATE TABLE IF NOT EXISTS user_preferences(user_id INTEGER PRIMARY KEY REFERENCES users(id),palette TEXT NOT NULL DEFAULT \'default\',sidebar TEXT NOT NULL DEFAULT \'[]\',donate INTEGER NOT NULL DEFAULT 1)')
        db().commit()

    def preferences():
        user=getattr(g,'user',None)
        row=db().execute('SELECT * FROM user_preferences WHERE user_id=?',(user['id'],)).fetchone() if user and not getattr(g,'demo',False) else None
        choices=[]
        for key,label,url,icon in NAV:
            if key in ('analytics','inbox','roadmap') and not (user and user['platform_admin']): continue
            if key=='management':
                if not user or not (user['platform_admin'] or user['role'] in ('owner','admin')): continue
                label='Client management' if user['platform_admin'] else label
            choices.append(dict(key=key,label=label,url=url,icon=icon))
        saved=json.loads(row['sidebar']) if row else []
        by_key={item['key']:item for item in choices}
        ordered=[]
        for item in saved:
            if item['key'] in by_key:
                ordered.append(dict(by_key.pop(item['key']),visible=item['visible']))
        ordered.extend(dict(item,visible=True) for item in by_key.values())
        return dict(palette=row['palette'] if row else 'default',sidebar_choices=ordered,show_donate=bool(row['donate']) if row else True,palettes=THEMES)

    app.context_processor(preferences)

    @app.route('/settings',methods=['GET','POST'])
    def settings():
        if getattr(g,'demo',False): abort(403)
        if request.method=='POST':
            palette=request.form.get('palette','default')
            if palette not in dict(THEMES): raise ValueError('Choose a listed color theme.')
            available={item['key'] for item in preferences()['sidebar_choices']}
            order=request.form.getlist('nav_order')
            shown=request.form.getlist('nav_visible')
            if len(order)!=len(set(order)) or set(order)!=available or not set(shown)<=available:
                raise ValueError('Reload settings and choose valid sidebar items.')
            items=[dict(key=key,visible=key in shown) for key in order]
            if request.form.get('action')=='reset':
                db().execute('DELETE FROM user_preferences WHERE user_id=?',(g.user['id'],))
            else:
                db().execute('INSERT INTO user_preferences VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET palette=excluded.palette,sidebar=excluded.sidebar,donate=excluded.donate',(g.user['id'],palette,json.dumps(items),int(request.form.get('donate')=='1')))
            db().commit();flash('Your settings have been saved.')
            return redirect('/settings')
        return render_template('settings.html')
