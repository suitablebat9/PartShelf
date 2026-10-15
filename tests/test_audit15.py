import io,re,sqlite3,time
from unittest.mock import patch
from pypdf import PdfReader
from test_inventory import app,client,post
from test_workspaces import tenant


def test_stock_boundaries_and_currency(client,app):
    for name,stock in [('Zero',0),('Below',2),('Threshold',5),('Healthy',6)]:post(client,'/components/new',name=name,stock=stock,low_stock=5,unit_price='.10')
    page=client.get('/search?stock=low').data
    assert b'Below</a>' in page and b'Threshold</a>' in page and b'Zero</a>' not in page and b'Healthy</a>' not in page
    assert b'Zero</a>' in client.get('/search?stock=restock').data
    assert b'$0.10' in page
    assert app.jinja_env.filters['unitmoney']('.0035')=='0.0035'


def test_stock_inline_and_return(client,app):
    post(client,'/components/new',name='Part',stock=15)
    response=post(client,'/components/1/stock',direction='remove',quantity=16,reason='Correct this',back='/drawers/1?slot=1-1')
    assert response.status_code==400 and b'data-error-summary' in response.data and b'value="16"' in response.data and b'Correct this' in response.data
    assert b'Back to drawer' in response.data
    response=post(client,'/components/1/stock',direction='add',quantity=1,back='/search?q=Part&stock=in')
    assert response.status_code==302 and 'back=' in response.location
    assert b'/search?q=Part&amp;stock=in' in client.get(response.location).data


def test_quick_stock_once_undo_and_stale(client,app):
    post(client,'/components/new',name='Part',stock=15)
    data=dict(component_id=1,version=1,direction='remove',quantity=2,token='audit-once-token-123')
    response=post(client,'/inventory/quick-stock',**data)
    assert response.status_code==200 and response.json['stock']==13
    assert post(client,'/inventory/quick-stock',**data).json['replay']
    undo='/inventory/quick-stock/audit-once-token-123/undo'
    assert post(client,undo).json['stock']==15
    assert post(client,undo).status_code==409
    assert post(client,'/inventory/quick-stock',**dict(data,token='audit-stale-token-123')).status_code==400
    data.update(token='audit-second-token-123',version=3)
    assert post(client,'/inventory/quick-stock',**data).status_code==200
    post(client,'/components/1/stock',quantity=1,direction='add')
    assert post(client,'/inventory/quick-stock/audit-second-token-123/undo').status_code==409
    _,_,other=tenant(app)
    assert post(other,undo).status_code==409
    with sqlite3.connect(app.config['DATABASE']) as db:db.execute("UPDATE users SET role='viewer' WHERE id=1")
    assert post(client,'/inventory/quick-stock',**data).status_code==403


def test_bulk_comparisons(client):
    post(client,'/storage',name='Shelf',kind='Shelf')
    post(client,'/components/new',name='Part',stock=1,tags='old')
    result=post(client,'/inventory/bulk',action='tag_add',component_ids=['1'],tags='new')
    page=client.get(result.location).data
    assert b'Current tags' in page and b'new, old' in page
    result=post(client,'/inventory/bulk',action='move',component_ids=['1'],location_id='1')
    page=client.get(result.location).data
    assert b'Current location' in page and b'Unassigned' in page and b'Shelf' in page


def test_square_label_keeps_identifier():
    from inventory.label_pdf import render_pdf,settings
    pdf=render_pdf([dict(name='Part',name_id='UX-10K-0603',code='UX-10K-0603',location='UX Audit Drawers / A2')],settings(dict(width=1,height=1,copies=2,text='{name_id}\n{location}')))
    doc=PdfReader(pdf)
    assert len(doc.pages)==2 and float(doc.pages[0].mediabox.width)==72
    assert 'UX-10K-0603' in doc.pages[0].extract_text()


def test_signup_resend_subject_expiry_inline(app):
    app.config['PUBLIC_URL']='https://partshelf.example.test'
    c=app.test_client();c.get('/register')
    with c.session_transaction() as s:s['csrf']='test'
    form=dict(username='new-user',email='new@example.test',password='good-password-123',password_confirm='good-password-123',workspace_name='My bench')
    with patch('inventory.management.mail_ready',return_value=True),patch('inventory.management.send_email') as mail:
        assert post(c,'/register',**form).status_code==302
        first=mail.call_args.args;code=re.search(r'\b\d{6}\b',first[1]).group()
        assert 'account creation code' in first[1] and code in first[2]
        assert 'n•••@example.test'.encode() in c.get('/register/verify').data
        bad=post(c,'/register/verify',code='wrong')
        assert bad.status_code==400 and b'data-error-summary' in bad.data and b'Resend code' in bad.data
        assert post(c,'/register/verify',action='resend').status_code==400
        with c.session_transaction() as s:s['registration_sent']=int(time.time())-61
        with sqlite3.connect(app.config['DATABASE']) as db:db.execute("UPDATE auth_challenges SET expires=0 WHERE purpose='registration'")
        assert post(c,'/register/verify',action='resend').status_code==302
        latest=re.search(r'\b\d{6}\b',mail.call_args.args[1]).group()
        assert post(c,'/register/verify',code=code).status_code==400
        assert post(c,'/register/verify',code=latest).status_code==302
        assert b'My bench' in c.get('/').data


def test_signup_change_email_and_existing_account_inline(app):
    app.config['PUBLIC_URL']='https://partshelf.example.test'
    with sqlite3.connect(app.config['DATABASE']) as db:db.execute("UPDATE users SET email='used@example.test' WHERE id=1")
    c=app.test_client();c.get('/register')
    with c.session_transaction() as s:s['csrf']='test'
    form=dict(username='second-user',email='used@example.test',password='good-password-123',password_confirm='good-password-123',workspace_name='Keep my workshop')
    with patch('inventory.management.mail_ready',return_value=True),patch('inventory.management.send_email') as mail:
        result=post(c,'/register',**form)
        assert result.status_code==400 and b'Keep my workshop' in result.data and b'/forgot-password' in result.data
        assert b'good-password-123' not in result.data and not mail.called
        assert post(c,'/register',**dict(form,email='first@example.test')).status_code==302
        with c.session_transaction() as s:s['registration_sent']=int(time.time())-61
        assert post(c,'/register/verify',action='change_email',email='second@example.test').status_code==302
        assert mail.call_args.args[0]=='second@example.test'
        code=re.search(r'\b\d{6}\b',mail.call_args.args[1]).group()
        assert post(c,'/register/verify',code=code).status_code==302
        with sqlite3.connect(app.config['DATABASE']) as db:
            assert db.execute("SELECT email FROM users WHERE username='second-user'").fetchone()[0]=='second@example.test'


def test_quick_stock_insufficient_and_workspace_isolation(client,app):
    post(client,'/components/new',name='Private',stock=1)
    change=dict(component_id=1,version=1,direction='remove',quantity=2,token='isolated-change-token')
    assert post(client,'/inventory/quick-stock',**change).status_code==400
    _,_,other=tenant(app)
    assert post(other,'/inventory/quick-stock',**dict(change,direction='add')).status_code==404
    with sqlite3.connect(app.config['DATABASE']) as db:assert db.execute('SELECT stock FROM components WHERE id=1').fetchone()[0]==1
