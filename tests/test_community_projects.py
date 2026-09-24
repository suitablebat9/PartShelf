import re
from decimal import Decimal
import sqlite3
from unittest.mock import patch
from flask import template_rendered
from inventory.community import DEFAULTS
from test_inventory import app, client, part, post
from test_workspaces import tenant


def public_post(c, path, **values):
    c.get(path)
    with c.session_transaction() as state:
        token=state['csrf']
    return c.post(path,data={'csrf':token,**values})


def make_admin(app):
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('UPDATE users SET platform_admin=1 WHERE id=1')


def test_public_pages_seo_and_private_exclusions(app, client):
    app.config['PUBLIC_URL']='https://partshelf.example.com'
    c=app.test_client()
    assert c.get('/').location.endswith('/welcome')
    for path in ('/welcome','/about','/support','/terms','/privacy','/feedback'):
        page=c.get(path)
        assert page.status_code==200
        assert b'index, follow' in page.data
        assert ('https://partshelf.example.com'+path).encode() in page.data
        assert b'Inventory<span' not in page.data
    assert b'application/ld+json' in c.get('/welcome').data
    assert b'paywall' in c.get('/support').data
    assert b'Minnesota' in c.get('/terms').data
    sitemap=c.get('/sitemap.xml')
    assert b'/welcome' in sitemap.data and b'/components' not in sitemap.data
    assert b'Sitemap: https://partshelf.example.com/sitemap.xml' in c.get('/robots.txt').data
    for path in ('/login','/register','/demo','/components/999'):
        assert 'noindex' in c.get(path).headers['X-Robots-Tag']
    assert 'noindex' in client.get('/').headers['X-Robots-Tag']


def test_site_settings_admin_only_safe_text_and_stripe(app,client):
    assert client.get('/management/site').status_code==403
    make_admin(app)
    values=dict(DEFAULTS, about_name='Creator', about_text='<script>bad()</script>', stripe_link='https://donate.stripe.com/example')
    assert post(client,'/management/site',**values).status_code==302
    page=app.test_client().get('/about')
    assert b'&lt;script&gt;' in page.data and b'<script>bad' not in page.data
    assert b'https://donate.stripe.com/example' in app.test_client().get('/support').data
    for link in ('javascript:alert(1)','https://stripe.com.evil.test/pay','https://evil.test/','https://donate.stripe.com@evil.test/a'):
        assert post(client,'/management/site',**dict(values,stripe_link=link)).status_code==400
    wid,uid,other=tenant(app)
    assert other.get('/management/site').status_code==403
    assert other.get('/management/feedback').status_code==403


def test_anonymous_feedback_is_private_and_needs_csrf(app,client):
    c=app.test_client()
    assert c.post('/feedback',data={'title':'Idea','body':'Message'}).status_code==400
    with patch('inventory.community.send_email') as send:
        assert public_post(c,'/feedback',title='Tiny idea',body='Private feedback',kind='Feedback').status_code==302
        send.assert_not_called()
    assert b'Private feedback' not in c.get('/feedback').data
    assert c.get('/management/feedback').status_code==302
    make_admin(app)
    assert b'Private feedback' in client.get('/management/feedback').data


def test_feedback_confirmation_status_email_retry_and_unsubscribe(app,client):
    app.config.update(PUBLIC_URL='https://partshelf.test',SMTP_HOST='smtp.test',SMTP_USERNAME='sender',SMTP_PASSWORD='test')
    make_admin(app)
    c=app.test_client()
    with patch('inventory.community.send_email') as send:
        public_post(c,'/feedback',title='Bigger labels',body='Please add a size',email='reader@example.test',updates='1')
        assert send.call_count==1
        link=re.search(r'https://partshelf.test(/feedback/email/[^\s]+)',send.call_args.args[2]).group(1)
        assert c.get(link).status_code==200
        with sqlite3.connect(app.config['DATABASE']) as db:
            assert db.execute('SELECT verified FROM feedback').fetchone()[0]==0
        post(client,'/management/feedback',id='1',revision='0',status='Reviewing',update_text='Taking a look')
        assert send.call_count==1  # No updates before consent is verified.
        assert public_post(c,link,action='confirm').status_code==302
        assert post(client,'/management/feedback',id='1',revision='1',status='Planned',update_text='On the roadmap').status_code==302
        assert send.call_count==2 and 'Planned' in send.call_args.args[1]
        post(client,'/management/feedback',id='1',revision='2',status='Planned',update_text='On the roadmap')
        assert send.call_count==2
        with patch('inventory.community.send_email',side_effect=ValueError('unavailable')):
            assert post(client,'/management/feedback',id='1',revision='2',status='Released',update_text='It is live').status_code==302
        page=client.get('/management/feedback')
        assert b'Retry email' in page.data
        post(client,'/management/feedback',id='1',action='retry')
        assert send.call_count==3 and 'Released' in send.call_args.args[1]
        assert public_post(c,link,action='unsubscribe').status_code==302
        post(client,'/management/feedback',id='1',revision='3',status='Released',update_text='More details')
        assert send.call_count==3
    assert c.get('/feedback/email/tampered').status_code==400


def test_whole_pack_cost_and_inline_project_edits(app,client):
    part(client,name='Resistor',stock='0',price='0.02',price_mode='unit',purchase_pack='100')
    post(client,'/projects',name='Amplifier')
    post(client,'/projects/1',component_id='1',quantity='32')
    contexts=[]
    def capture(sender,template,context,**extra):
        contexts.append(context)
    with template_rendered.connected_to(capture,app):
        assert client.get('/projects/1').status_code==200
    assert contexts[-1]['buy']==Decimal('0.64')
    assert contexts[-1]['package_buy']==Decimal('2.00')
    assert contexts[-1]['items'][0]['purchase_units']==100
    assert b'Required quantity' in client.get('/projects/1').data
    post(client,'/projects/1',component_id='1',quantity='132')
    with template_rendered.connected_to(capture,app):
        client.get('/projects/1')
    assert contexts[-1]['items'][0]['purchase_units']==200
    post(client,'/projects/1',action='details',name='Updated project',description='Changed')
    assert b'Updated project' in client.get('/projects/1').data
    assert post(client,'/components/1/project',project_id='1',quantity='3').status_code==302
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT quantity FROM project_items').fetchone()[0]==135


def test_project_search_facets_and_workspace_permissions(app,client):
    part(client,name='Small resistor',size='0603',resistance='10k',purchase_pack='100')
    part(client,name='Large capacitor',size='0805',capacitance='100nF')
    post(client,'/projects',name='Filter test')
    page=client.get('/projects/1?size_value=0603&q=resistor')
    assert page.status_code==200 and b'Small resistor' in page.data and b'Large capacitor' not in page.data
    assert b'action="/projects/1"' in page.data
    wid,uid,other=tenant(app)
    assert post(other,'/components/1/project',project_id='1',quantity='1').status_code==404
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE users SET role='viewer' WHERE id=1")
    assert post(client,'/components/1/project',project_id='1',quantity='1').status_code==403


def test_pack_size_validation_and_preservation(client,app):
    for value in ('0','-1','nan','1000000001'):
        assert part(client,name='Invalid',purchase_pack=value).status_code==400
    part(client,name='Valid',purchase_pack='100')
    with sqlite3.connect(app.config['DATABASE']) as db:
        version=db.execute('SELECT version FROM components WHERE id=1').fetchone()[0]
    assert post(client,'/components/1/edit',name='Valid',stock='1',price_mode='unit',unit_price='2',version=version).status_code==302
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT purchase_pack FROM components WHERE id=1').fetchone()[0]=='100'


def test_fractional_shortage_does_not_buy_extra_pack(client,app):
    part(client,name='Wire',stock='0.1',price='2',price_mode='unit',purchase_pack='0.1',unit='m')
    post(client,'/projects',name='Fractional stock')
    post(client,'/projects/1',component_id='1',quantity='0.8')
    contexts=[]
    def capture(sender,template,context,**extra):
        contexts.append(context)
    with template_rendered.connected_to(capture,app):
        client.get('/projects/1')
    assert contexts[-1]['items'][0]['packs']==7
    assert contexts[-1]['items'][0]['purchase_units']==Decimal('0.7')
