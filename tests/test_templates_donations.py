from pathlib import Path
import sqlite3
import pytest
from test_inventory import app,client,post,part
from test_community_projects import make_admin
from inventory.template_editor import validate_template

ROOT=Path(__file__).parents[1]/'inventory/templates'


def test_template_changes_keep_inventory_and_labels_functional(app,client):
    assert client.get('/management/templates').status_code==403
    make_admin(app)
    source=(ROOT/'inventory.html').read_text().replace('<h1>Inventory','<h1>My parts')
    assert post(client,'/management/templates',template='inventory.html',revision='0',action='save',source=source).status_code==302
    assert b'My parts' in client.get('/').data
    assert part(client).status_code==302
    page=client.get('/')
    assert b'My parts' in page.data and b'10k resistor' in page.data
    labels=(ROOT/'labels.html').read_text().replace('Labels that fit.','My label studio')
    assert post(client,'/management/templates',template='labels.html',revision='0',action='save',source=labels).status_code==302
    result=client.get('/labels')
    assert b'My label studio' in result.data and b'id="label-form"' in result.data and b'name="csrf"' in result.data
    assert post(client,'/management/templates',template='labels.html',revision='0',action='save',source=labels).status_code==409
    assert post(client,'/management/templates',template='labels.html',revision='1',action='reset').status_code==302
    assert b'Labels that fit.' in client.get('/labels').data


def test_template_safety_contract_and_recovery(app,client):
    make_admin(app)
    source=(ROOT/'labels.html').read_text()
    for edited in [source+'{{ config }}',source.replace('action="/labels/pdf"','action="https://evil.test"'),source.replace('name="csrf"','name="bad"'),source+'<img src=x onerror="alert(1)">',source+'<script>alert(1)</script>',source.replace('id="label-form"','id="broken"')]:
        assert post(client,'/management/templates',template='labels.html',revision='0',action='save',source=edited).status_code==400
    assert client.get('/management/templates?template=../../auth.py').status_code==404
    base=(ROOT/'base.html').read_text().replace('Public site settings','Custom navigation')
    assert post(client,'/management/templates',template='base.html',revision='0',action='save',source=base).status_code==302
    assert b'Custom navigation' in client.get('/').data
    assert b'>Public site settings<' in client.get('/management/templates').data


def test_all_shipped_templates_pass_validation(app):
    for path in ROOT.glob('*.html'):
        validate_template(app,path.read_text(),path.read_text())
    baseline='<p>{{ user.email }}</p>'
    for edited in ['<img src="https://evil.test/?email={{ user.email }}">','<a {{ user.email }}>x</a>','<!-- {{ user.email }} -->']:
        with pytest.raises(ValueError):validate_template(app,baseline,edited)


def test_template_update_fallback(app,client):
    make_admin(app)
    source=(ROOT/'inventory.html').read_text().replace('<h1>Inventory','<h1>Custom')
    post(client,'/management/templates',template='inventory.html',revision='0',action='save',source=source)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE template_overrides SET base_hash='old',revision=revision+1")
    assert b'<h1>Inventory' in client.get('/').data
    assert b'paused' in client.get('/management/templates').data


def test_donation_embed_confirmation_and_scoped_csp(app,client):
    c=app.test_client()
    thanks=c.get('/donation/thank-you?amount=999&success=true')
    assert thanks.status_code==200 and b'Thank you for supporting' in thanks.data
    assert b'not a payment receipt' in thanks.data and b'999' not in thanks.data
    assert 'noindex' in thanks.headers['X-Robots-Tag']
    assert b'/donation/thank-you' not in c.get('/sitemap.xml').data
    embed=c.get('/donation/embed')
    assert b'buy_btn_1UJFm36xlGS0fY1JvHZYI3ms' in embed.data
    assert 'script-src' in embed.headers['Content-Security-Policy'] and 'https://js.stripe.com' in embed.headers['Content-Security-Policy']
    assert embed.headers['X-Frame-Options']=='SAMEORIGIN'
    for path in ['/welcome','/support']:
        page=c.get(path)
        assert b'<stripe-buy-button' in page.data
        assert 'https://js.stripe.com' in page.headers['Content-Security-Policy']
    assert 'https://js.stripe.com' not in client.get('/labels').headers['Content-Security-Policy']
    make_admin(app)
    assert post(client,'/management/site',stripe_publishable_key='sk_live_never').status_code==400
    assert post(client,'/management/site',stripe_buy_button_id='',stripe_publishable_key='').status_code==302
    assert b'<stripe-buy-button' not in c.get('/donation/embed').data
    assert b'<stripe-buy-button' not in c.get('/support').data
