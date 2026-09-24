import sqlite3
import time
from unittest.mock import patch
from test_inventory import app, client, post
from test_community_projects import make_admin, public_post
from inventory.site_editor import sanitize_html


def test_roadmap_admin_publish_hide_and_stale(app,client):
    assert client.get('/management/roadmap').status_code==403
    make_admin(app)
    assert post(client,'/management/roadmap',title='Part import',description='<script>unsafe</script>',status='Planned',published='1').status_code==302
    public=app.test_client()
    assert b'Part import' in public.get('/roadmap').data
    assert b'&lt;script&gt;' in public.get('/roadmap').data
    assert b'/roadmap' in public.get('/sitemap.xml').data
    assert post(client,'/management/roadmap',id='1',revision='1',title='Part import',status='In progress',published='1').status_code==302
    assert post(client,'/management/roadmap',id='1',revision='1',title='Stale',status='Planned').status_code==409
    assert post(client,'/management/roadmap',id='1',revision='2',title='Part import',status='In progress').status_code==302
    assert b'Part import' not in public.get('/roadmap').data


def test_html_editor_preview_save_reset_and_access(app,client):
    assert client.get('/management/pages').status_code==403
    make_admin(app)
    assert b'Your parts, in order' in client.get('/management/pages?page=welcome').data
    html='<h1>My edited page</h1><p>{{ 7*7 }}</p><script>alert(1)</script><a href="javascript:alert(1)" onclick="bad()">Link</a>'
    preview=post(client,'/management/pages',page='welcome',revision='0',action='preview',html=html)
    assert preview.status_code==200 and b'Preview' in preview.data
    assert b'My edited page' not in app.test_client().get('/welcome').data
    assert post(client,'/management/pages',page='welcome',revision='0',action='save',html=html).status_code==302
    saved=app.test_client().get('/welcome').data
    assert b'My edited page' in saved and b'{{ 7*7 }}' in saved
    assert b'<script>alert' not in saved and b'onclick=' not in saved and b'href="javascript' not in saved
    assert post(client,'/management/pages',page='welcome',revision='0',action='save',html='stale').status_code==409
    assert post(client,'/management/pages',page='welcome',revision='1',action='reset').status_code==302
    assert b'Your parts, in order' in app.test_client().get('/welcome').data
    assert client.get('/management/pages?page=login').status_code==404


def test_html_sanitizer_disallows_active_content():
    result=sanitize_html('<img src=x onerror=bad()><iframe srcdoc="bad"></iframe><form action="/logout"><input name="csrf"></form><svg><a href="jav&#x61;script:bad()">x</a></svg><p style="position:fixed" id="theme-toggle">safe</p>')
    assert result=='<a>x</a><p>safe</p>'
    assert sanitize_html('<h2>Text</h2><a href="/login">Sign in</a>')=='<h2>Text</h2><a href="/login">Sign in</a>'


def test_live_visitors_demo_sessions_and_admin_exclusion(app,client):
    make_admin(app)
    c=app.test_client()
    c.get('/demo')
    client.get('/welcome')
    assert post(client,'/visitor-pulse',mode='website').status_code==204
    base=int(time.time())
    with patch('time.time',return_value=base):
        assert public_post(c,'/visitor-pulse',mode='demo').status_code==204
        assert public_post(c,'/visitor-pulse',mode='demo').status_code==204
        stats=client.get('/management/analytics/live').json
        assert stats['live_demo']==stats['live_website']==stats['demo_total']==1
    with patch('time.time',return_value=base+121):
        stats=client.get('/management/analytics/live').json
        assert stats['live_demo']==stats['live_website']==0
        assert stats['demo_total']==1
    with patch('time.time',return_value=base+1801):
        assert public_post(c,'/visitor-pulse',mode='demo').status_code==204
        assert client.get('/management/analytics/live').json['demo_total']==2
    assert c.get('/management/analytics/live').status_code==302
    assert c.post('/visitor-pulse',data={'mode':'demo'}).status_code==400


def test_pulse_preserves_demo_and_respects_privacy(app,client):
    make_admin(app)
    c=app.test_client()
    c.get('/demo')
    assert public_post(c,'/demo').status_code==302
    c.get('/')
    with c.session_transaction() as state:
        token=state['csrf']
    assert c.post('/visitor-pulse',data={'csrf':token,'mode':'demo'}).status_code==204
    with c.session_transaction() as state:
        assert state['demo'] is True
    private=app.test_client()
    page=private.get('/welcome',headers={'Sec-GPC':'1'})
    assert b'data-track-visits="0"' in page.data
    with private.session_transaction() as state:
        assert 'visitor_id' not in state
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT COUNT(*) FROM visitor_activity').fetchone()[0]==1
