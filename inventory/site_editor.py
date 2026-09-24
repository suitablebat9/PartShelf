"""Admin-managed public HTML and a public roadmap. Never executes templates or scripts."""
import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit
from flask import abort, flash, redirect, render_template, request, url_for

PAGES={'welcome':('Welcome','welcome.html'), 'about':('About','public_page.html'),
       'support':('Donations','public_page.html'), 'terms':('Terms','public_page.html'),
       'privacy':('Privacy','public_page.html')}
STATES=('Planned','In progress','Released')

class PublicHTML(HTMLParser):
    tags={'section','article','div','span','p','br','hr','h1','h2','h3','h4','strong','em','b','i','u','s','ul','ol','li','blockquote','pre','code','a','table','thead','tbody','tr','th','td','small','details','summary'}
    void={'br','hr'}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output=[]
        self.stack=[]
    def handle_starttag(self,tag,attrs):
        if tag not in self.tags:
            return
        kept=[]
        for name,value in attrs:
            value=value or ''
            if name=='class' and re.fullmatch(r'[a-zA-Z0-9 _-]{0,200}',value):
                kept.append(('class',value))
            elif name=='title':
                kept.append((name,value[:500]))
            elif tag=='a' and name=='href':
                parsed=urlsplit(value)
                if not any(ord(c)<33 for c in value) and (parsed.scheme in ('https','http','mailto') or value.startswith(('/', '#')) and not value.startswith('//')):
                    kept.append(('href',value))
        self.output.append('<'+tag+''.join(' '+k+'="'+escape(v,quote=True)+'"' for k,v in kept)+'>')
        if tag not in self.void:
            self.stack.append(tag)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in self.void:
            self.handle_endtag(tag)
    def handle_endtag(self,tag):
        if tag in self.stack:
            while self.stack:
                current=self.stack.pop();self.output.append('</'+current+'>')
                if current==tag: break
    def handle_data(self,data):
        self.output.append(escape(data))
    def result(self):
        return ''.join(self.output)+''.join('</'+tag+'>' for tag in reversed(self.stack))


def sanitize_html(value):
    if len(value)>60000:
        raise ValueError('Keep each page under 60,000 characters.')
    parser=PublicHTML()
    try:
        parser.feed(value)
        parser.close()
    except ValueError:
        raise ValueError('The HTML contains an invalid link.')
    return parser.result()


def install_site_editor(app,bp,db,admin,auth):
    with app.app_context():
        db().executescript('''CREATE TABLE IF NOT EXISTS public_html(
            page TEXT PRIMARY KEY,html TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS roadmap(
            id INTEGER PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Planned',position INTEGER NOT NULL DEFAULT 0,
            published INTEGER NOT NULL DEFAULT 1,revision INTEGER NOT NULL DEFAULT 1);''')
        db().commit()

    @app.context_processor
    def editable_content():
        page=(request.endpoint or '').removeprefix('community.')
        row=db().execute('SELECT html FROM public_html WHERE page=?',(page,)).fetchone() if page in PAGES else None
        return {'custom_page_html':row['html'] if row else None}

    @bp.get('/roadmap')
    def roadmap():
        return render_template('roadmap.html',states=STATES,items=db().execute('SELECT * FROM roadmap WHERE published=1 ORDER BY position,id DESC').fetchall())

    @bp.route('/management/roadmap',methods=['GET','POST'])
    @admin
    def roadmap_admin():
        if request.method=='POST':
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

    @bp.route('/management/pages',methods=['GET','POST'])
    @admin
    @auth['recent']
    def html_editor():
        page=request.values.get('page','welcome')
        if page not in PAGES: abort(404)
        current=db().execute('SELECT * FROM public_html WHERE page=?',(page,)).fetchone()
        revision=current['revision'] if current else 0
        preview=None
        if request.method=='POST':
            action=request.form.get('action')
            content=sanitize_html(request.form.get('html',''))
            if action=='preview':
                revision=request.form.get('revision','0')
                preview=content
            elif action in ('save','reset'):
                conn=db();conn.execute('BEGIN IMMEDIATE')
                fresh=conn.execute('SELECT revision FROM public_html WHERE page=?',(page,)).fetchone()
                if str(fresh['revision'] if fresh else 0)!=request.form.get('revision'):
                    conn.rollback();abort(409,'This page changed in another tab. Reload before saving.')
                if action=='reset':
                    conn.execute('DELETE FROM public_html WHERE page=?',(page,))
                else:
                    conn.execute('INSERT INTO public_html(page,html,revision) VALUES(?,?,1) ON CONFLICT(page) DO UPDATE SET html=excluded.html,revision=public_html.revision+1',(page,content))
                conn.commit();flash('Default content restored.' if action=='reset' else 'HTML page saved.')
                return redirect(url_for('community.html_editor',page=page))
            else: abort(400)
        else:
            if current:
                content=current['html']
            else:
                rendered=render_template(PAGES[page][1],page=page,custom_page_html=None)
                content=rendered.split('<!-- public-content:start -->',1)[1].split('<!-- public-content:end -->',1)[0]
        return render_template('html_editor.html',pages=PAGES,page=page,content=content,preview=preview,revision=revision,customized=bool(current))
