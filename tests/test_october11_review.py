import re
import sqlite3
import pytest
from test_inventory import app, client, post


def project_fixture(client):
    post(client,'/components/new',name='Review resistor',stock='8',unit_price='0.35')
    post(client,'/projects',name='Review project')
    post(client,'/projects/1',component_id='1',quantity='9')


def test_project_shopping_round_trip(client):
    project_fixture(client)
    page=client.get('/projects/1?builds=2')
    assert page.status_code==200
    assert b'value="2" required' in page.data and b'$6.30' in page.data and b'$3.50' in page.data
    shopping=client.get('/projects/1/shopping-list?builds=2')
    assert shopping.status_code==200 and b'10 pcs' in shopping.data
    back=re.search(rb'href="([^"]+)">Back to project',shopping.data).group(1).decode()
    returned=client.get(back)
    assert returned.status_code==200 and b'Cost for 2 builds' in returned.data


@pytest.mark.parametrize('count',['0','-1','1.5','10001','oops','NaN','Infinity',''])
def test_invalid_build_counts(client,count):
    project_fixture(client)
    for suffix in ['', '/shopping-list']:
        assert client.get('/projects/1'+suffix,query_string={'builds':count}).status_code==400


def test_preview_preserves_context_and_rejects_external_returns(client):
    post(client,'/components/new',name='Review part',stock=8)
    back='/search?q=Review&stock=in&sort=stock_desc'
    preview=post(client,'/inventory/bulk',action='stock_add',component_ids=['1'],quantity=1,back=back)
    page=client.get(preview.location)
    assert b'/search?q=Review&amp;stock=in&amp;sort=stock_desc' in page.data
    applied=post(client,preview.location,confirmed='yes')
    assert applied.location==back
    for url in ['https://evil.example','//evil.example','/logout','/\\evil.example']:
        response=post(client,'/inventory/bulk',action='stock_add',component_ids=['1'],quantity=1,back=url)
        page=client.get(response.location)
        assert url.encode() not in page.data


def test_missing_price_distinguished_from_explicit_zero(client):
    post(client,'/components/new',name='Unknown',stock=0)
    post(client,'/components/new',name='Free',stock=0,unit_price='0')
    assert b'Price not set' in client.get('/components/1').data
    assert b'$0.00' in client.get('/components/2').data
    post(client,'/projects',name='Unpriced project')
    post(client,'/projects/1',component_id='1',quantity=2)
    page=client.get('/projects/1/shopping-list')
    assert b'Known whole-pack subtotal' in page.data and b'Price not set' in page.data
    assert b'Exact shortage cost' in page.data and b'Exact unit cost' not in page.data
    assert b'Known subtotal for 1 build' in client.get('/projects/1').data


def test_server_error_has_recovery(client,app):
    from flask import abort
    app.add_url_rule('/test-server-error',view_func=lambda:abort(500))
    response=client.get('/test-server-error')
    assert response.status_code==500 and b'Return to inventory' in response.data and b'Contact support' in response.data
