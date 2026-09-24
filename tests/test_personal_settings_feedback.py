import json
import re
import sqlite3
from unittest.mock import patch
from itsdangerous import URLSafeTimedSerializer
from inventory.mailer import send_email
from test_inventory import app, client, post, part
from test_community_projects import make_admin, public_post
from test_workspaces import tenant


def nav_keys(client):
    return re.findall(r'name="nav_order" value="([^"]+)"',client.get('/settings').text)


def test_preferences_are_personal_and_permission_filtered(app,client):
    keys=nav_keys(client)
    assert 'analytics' not in keys
    result=post(client,'/settings',palette='forest',nav_order=list(reversed(keys)),nav_visible=['projects','storage'])
    assert result.status_code==302
    html=client.get('/').text
    assert 'data-palette="forest"' in html and 'donate-button' not in html
    nav=html.split('<nav aria-label="Sidebar">')[1].split('</nav>')[0]
    assert 'Inventory' not in nav and nav.index('Storage')<nav.index('Projects')
    _,_,other=tenant(app)
    assert 'data-palette="default"' in other.get('/').text
    assert 'donate-button' in other.get('/').text
    assert post(client,'/settings',palette='forest',nav_order=keys+['analytics']).status_code==400
    assert post(client,'/settings',palette='invalid',nav_order=keys).status_code==400
    assert post(client,'/settings',palette='forest',nav_order=list(reversed(keys)),action='reset').status_code==302
    assert 'data-palette="default"' in client.get('/').text


def test_storage_banner_and_authenticated_feedback_sidebar(app,client):
    post(client,'/storage',name='Cabinet A',kind='Cabinet')
    post(client,'/storage',name='Drawer 2',kind='Drawer',parent_id='1')
    page=client.get('/search?location_id=2').text
    assert 'VIEWING STORAGE' in page and 'Cabinet A / Drawer 2' in page
    for path in ['/feedback','/support']:
        assert '<aside class="sidebar">' in client.get(path).text
        assert '<aside class="sidebar">' not in app.test_client().get(path).text
    assert 'action="/logout"' not in client.get('/').text
    assert 'signout-button' in client.get('/settings').text


def feedback(app,client,verified=True):
    make_admin(app)
    app.config['PUBLIC_URL']='https://partshelf.test'
    public_post(app.test_client(),'/feedback',title='Bulk import',body='Private account details',email='reader@example.test')
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('UPDATE feedback SET subscribed=1,verified=?',(int(verified),))


def test_feedback_roadmap_notification_unsubscribe_and_trash(app,client):
    feedback(app,client)
    with patch('inventory.community.send_email') as send:
        response=post(client,'/management/feedback',id='1',revision='0',action='roadmap',roadmap_title='Import parts',roadmap_description='Public summary',roadmap_status='Planned')
        assert response.status_code==302 and send.call_count==1
        unsubscribe=re.search(r'https://partshelf.test(/feedback/unsubscribe/\S+)',send.call_args.args[2]).group(1)
        roadmap=app.test_client().get('/roadmap').text
        assert 'Import parts' in roadmap and 'Private account details' not in roadmap and 'reader@example.test' not in roadmap
        assert post(client,'/management/feedback',id='1',revision='0',action='roadmap',roadmap_title='Duplicate',roadmap_status='Planned').status_code==409
        c=app.test_client()
        assert c.get(unsubscribe).status_code==200
        assert c.get(unsubscribe).status_code==200
        assert c.get(unsubscribe+'tampered').status_code==400
        post(client,'/management/feedback',id='1',revision='1',status='Released',update_text='Ready')
        assert send.call_count==1
        assert post(client,'/management/feedback',id='1',revision='2',action='delete').status_code==302
        assert 'Bulk import' not in client.get('/management/feedback').text
        assert 'Bulk import' in client.get('/management/feedback?trash=1').text
        assert 'Import parts' in c.get('/roadmap').text
        assert post(client,'/management/feedback',id='1',revision='3',action='restore').status_code==302
        assert 'Bulk import' in client.get('/management/feedback').text


def test_unverified_feedback_is_not_emailed_for_roadmap(app,client):
    feedback(app,client,verified=False)
    with patch('inventory.community.send_email') as send:
        assert post(client,'/management/feedback',id='1',revision='0',action='roadmap',roadmap_title='Import',roadmap_status='In progress').status_code==302
        send.assert_not_called()
    _,_,other=tenant(app)
    assert post(other,'/management/feedback',id='1',revision='1',action='delete').status_code==403


def test_branded_multipart_email_and_unsubscribe_button(app):
    app.config.update(PUBLIC_URL='https://partshelf.test',SMTP_HOST='smtp.test',SMTP_PORT=587,SMTP_USERNAME='test',SMTP_PASSWORD='test')
    with app.app_context(), patch('inventory.mailer.smtplib.SMTP') as smtp:
        send_email('reader@example.test','Feature <update>','Hello <script>bad</script>\nUnsubscribe: https://partshelf.test/feedback/unsubscribe/signed-token')
        message=smtp.return_value.send_message.call_args.args[0]
        assert message.is_multipart()
        html=message.get_body(preferencelist=('html',)).get_content()
        assert 'BY PCB STUDIOS' in html and '>Unsubscribe</a>' in html
        assert '<script>' not in html and '&lt;script&gt;' in html
        assert '>https://partshelf.test/' not in html
        assert 'https://partshelf.test/' in message.get_body(preferencelist=('plain',)).get_content()


def test_verified_email_change_keeps_old_email_until_confirmed(app,client):
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE users SET email='old@example.test',email_verified=1 WHERE id=1")
    page=client.get('/account').text
    assert 'Change email address' in page and 'Send verification code' not in page
    with patch('inventory.auth.send_email') as send:
        post(client,'/account/email/send',email='old@example.test')
        send.assert_not_called()
        assert post(client,'/account/email/send',email='new@example.test').status_code==302
        code=re.search(r'\b\d{6}\b',send.call_args.args[2]).group()
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT email FROM users WHERE id=1').fetchone()[0]=='old@example.test'
    assert post(client,'/account/email/verify',code=code).status_code==302
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT email,email_verified FROM users WHERE id=1').fetchone()==('new@example.test',1)


def test_stock_unsubscribe_without_signin(app,client):
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE users SET email='reader@example.test',low_stock_email=1 WHERE id=1")
    token=URLSafeTimedSerializer(app.secret_key,salt='stock-unsubscribe').dumps([1,'reader@example.test'])
    c=app.test_client()
    assert c.get('/notifications/unsubscribe/'+token).status_code==200
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT low_stock_email FROM users WHERE id=1').fetchone()[0]==0
    assert c.get('/notifications/unsubscribe/tampered').status_code==400
