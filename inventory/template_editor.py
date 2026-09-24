"""Editable HTML templates with immutable server logic and form contracts."""
import hashlib
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from flask import abort, flash, has_request_context, redirect, render_template, request, url_for
from jinja2 import BaseLoader, TemplateSyntaxError
from .site_editor import PublicHTML

TOKENS=re.compile(r'({{.*?}}|{%.*?%}|{#.*?#})',re.S)
MARKER=re.compile(r'PARTSHELFTOKEN(\d+)END',re.I)
RECOVERY={'community.template_editor','community.html_editor','community.site_admin'}


def source_hash(source):
    return hashlib.sha256(source.encode()).hexdigest()


class Contract(HTMLParser):
    controls={'form','input','select','option','textarea','button','iframe','script','style','link','meta','base','object','embed','svg','path','stripe-buy-button'}
    allowed=PublicHTML.tags|{'header','footer','main','aside','nav','label','fieldset','legend','figure','figcaption','dl','dt','dd','img'}
    def __init__(self,source):
        super().__init__(convert_charrefs=True)
        self.protected=[];self.dynamic=[];self.forms=[];self.form_count=0;self.special=[];self.special_stack=[]
        self.number=0
        def mask(match):
            value='PARTSHELFTOKEN'+str(self.number)+'END';self.number+=1;return value
        self.feed(TOKENS.sub(mask,source));self.close()
    def handle_starttag(self,tag,attrs):
        if tag=='form':
            self.form_count+=1;self.forms.append(self.form_count)
        parent=self.forms[-1] if self.forms else 0
        if tag in self.controls or tag not in self.allowed:
            self.protected.append((tag,tuple(sorted(attrs,key=lambda x:x[0])),parent))
        for name,value in attrs:
            value=value or ''
            for token in MARKER.findall(name):
                self.dynamic.append((token,tag,'attribute-name',name))
            for token in MARKER.findall(value):
                self.dynamic.append((token,tag,name,value))
            if tag not in self.controls and (name.startswith('on') or name in ('srcdoc','style','formaction')):
                raise ValueError('Scripts, event handlers, and inline styles cannot be added in this editor.')
            if name in ('href','src','action','formaction') and not MARKER.search(value):
                scheme=urlsplit(value).scheme.lower()
                if scheme and scheme not in ('https','http','mailto','data'):
                    raise ValueError('Links must use safe web URLs.')
                if scheme=='data' and not (tag=='img' and value.startswith('data:image/')):
                    raise ValueError('Only image data URLs are supported.')
                if any(ord(c)<32 for c in value):raise ValueError('Control characters are not allowed in links.')
        if tag in ('script','style','option'):
            self.special_stack.append(tag);self.special.append(('start',tag))
    def handle_endtag(self,tag):
        if tag in self.controls and tag!='form':
            self.protected.append(('/'+tag,(),self.forms[-1] if self.forms else 0))
        if tag=='form':
            self.protected.append(('/form',(),self.forms[-1] if self.forms else 0))
            if self.forms:self.forms.pop()
        if tag in ('script','style','option'):
            self.special.append(('end',tag))
            if self.special_stack:self.special_stack.pop()
    def handle_data(self,data):
        if self.special_stack:self.special.append(('data',data))
    def handle_comment(self,data):
        # Moving dynamic fields into comments can expose private values in unexpected contexts.
        for token in MARKER.findall(data):self.dynamic.append((token,'comment','',data))


def validate_template(app,baseline,edited):
    if len(edited)>150000:raise ValueError('Keep templates under 150,000 characters.')
    if TOKENS.findall(baseline)!=TOKENS.findall(edited):
        raise ValueError('Keep all {{ dynamic fields }}, {% template instructions %}, and template comments unchanged and in their original order. Edit the surrounding HTML and text.')
    try:
        app.jinja_env.parse(edited)
        original=Contract(baseline);candidate=Contract(edited)
    except (TemplateSyntaxError,ValueError) as error:
        raise ValueError('Template validation failed: '+str(error))
    if original.protected!=candidate.protected or original.special!=candidate.special:
        raise ValueError('Keep form controls, options, scripts, embedded widgets, and their attributes unchanged. You can edit surrounding HTML and button/label text.')
    if Counter(original.dynamic)!=Counter(candidate.dynamic):
        raise ValueError('Keep dynamic fields in their original HTML attributes or text context.')
    # Functional IDs and data attributes are used by the app JavaScript.
    def hooks(source):
        return re.findall(r'\b(?:id|data-[\w-]+)\s*=\s*(?:"[^"]*"|\x27[^\x27]*\x27)',source)
    if hooks(baseline)!=hooks(edited):raise ValueError('Keep existing HTML IDs and data attributes unchanged.')
    return edited


def install_template_editor(app,bp,db,admin,auth):
    root=Path(app.root_path)/'templates'
    catalog={p.name:p.stem.replace('_',' ').title() for p in sorted(root.glob('*.html')) if p.name not in ('template_editor.html','html_editor.html','site_admin.html')}
    with app.app_context():
        db().execute('CREATE TABLE IF NOT EXISTS template_overrides(name TEXT PRIMARY KEY,source TEXT NOT NULL,base_hash TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1)')
        db().commit()
    original_loader=app.jinja_loader
    class EditableLoader(BaseLoader):
        def get_source(self,environment,name):
            source,filename,up_to_date=original_loader.get_source(environment,name)
            protected=not has_request_context() or request.endpoint in RECOVERY
            row=db().execute('SELECT * FROM template_overrides WHERE name=?',(name,)).fetchone() if not protected and name in catalog else None
            version=row['revision'] if row else None
            active=bool(row and row['base_hash']==source_hash(source))
            def current():
                if not has_request_context():return False
                if (request.endpoint in RECOVERY)!=protected:return False
                latest=db().execute('SELECT revision FROM template_overrides WHERE name=?',(name,)).fetchone() if name in catalog and not protected else None
                return (latest['revision'] if latest else None)==version and up_to_date()
            return (row['source'] if active else source),filename,current
    app.jinja_loader=EditableLoader()
    app.jinja_env.auto_reload=True

    @bp.route('/management/templates',methods=['GET','POST'])
    @admin
    @auth['recent']
    def template_editor():
        name=request.values.get('template','inventory.html')
        if name not in catalog:abort(404)
        baseline=(root/name).read_text()
        row=db().execute('SELECT * FROM template_overrides WHERE name=?',(name,)).fetchone()
        revision=row['revision'] if row else 0
        source=row['source'] if row else baseline
        preview=None
        if request.method=='POST':
            action=request.form.get('action')
            source=request.form.get('source','')
            if action!='reset':validate_template(app,baseline,source)
            if action=='preview':
                # Static preview: server expressions are placeholders, never executed with admin data.
                from .site_editor import sanitize_html
                preview=sanitize_html(TOKENS.sub(' [dynamic content] ',source))
                revision=request.form.get('revision','0')
            elif action in ('save','reset'):
                conn=db();conn.execute('BEGIN IMMEDIATE')
                fresh=conn.execute('SELECT revision FROM template_overrides WHERE name=?',(name,)).fetchone()
                if str(fresh['revision'] if fresh else 0)!=request.form.get('revision'):
                    conn.rollback();abort(409,'This template changed in another tab. Reload before saving.')
                conn.execute('INSERT INTO template_overrides(name,source,base_hash,revision) VALUES(?,?,?,1) ON CONFLICT(name) DO UPDATE SET source=excluded.source,base_hash=excluded.base_hash,revision=template_overrides.revision+1',(name,baseline if action=='reset' else source,source_hash(baseline)))
                conn.commit();app.jinja_env.cache.clear()
                flash('Template restored.' if action=='reset' else 'Template published.')
                return redirect(url_for('community.template_editor',template=name))
            else:abort(400)
        return render_template('template_editor.html',catalog=catalog,name=name,source=source,revision=revision,preview=preview,outdated=bool(row and row['base_hash']!=source_hash(baseline)))
