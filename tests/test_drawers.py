import sqlite3
from unittest.mock import patch
import pytest
from test_inventory import app, client, post, part


def setup_cabinet(app,client):
    with sqlite3.connect(app.config['DATABASE']) as db: db.execute("UPDATE users SET role='owner' WHERE id=1")
    app.config['DEVICE_ENDPOINTS']={'1':['http://192.168.1.50']}
    assert post(client,'/drawers',name='Stacked shelves',rows='16').status_code==302


def configure(client,**kwargs):
    return post(client,'/drawers/1/settings',**dict(endpoint='http://192.168.1.50',api_key='local-device-test-key',enabled='1',x_origin='10',y_origin='20',x_pitch='40',y_pitch='-40',section_gap='-15',servo_closed='10',servo_open='90',light_seconds='15',**kwargs))


def test_stacked_map_assignment_and_coordinates(app,client):
    setup_cabinet(app,client)
    page=client.get('/drawers/1')
    assert page.status_code==200 and b'Lower section' in page.data and b'data-label="P8"' in page.data
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT COUNT(*) FROM cabinet_drawers').fetchone()[0]==128
    part(client)
    assert post(client,'/drawers/1/assign',row='9',col='8',component_id='1').status_code==302
    assert configure(client).status_code==302
    captured=[]
    def device(cabinet,method,path,payload=None):
        captured.append(payload)
        return {'command_id':payload['command_id'],'status':'completed'}
    with patch('inventory.drawers.device_request',side_effect=device):
        r=post(client,'/drawers/1/command',action='open',row='9',col='8',confirmed='1')
    assert r.status_code==202 and r.json['status']=='completed'
    assert captured[0]['position_mm']=={'x':290,'y':-315}
    assert captured[0]['drawer']=={'row':9,'column':8,'label':'I8'}
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT location_id FROM components').fetchone()[0]==db.execute('SELECT location_id FROM cabinet_drawers WHERE row=9 AND col=8').fetchone()[0]
        assert 'local-device-test-key' not in db.execute('SELECT api_key FROM cabinets').fetchone()[0]
    assert b'local-device-test-key' not in client.get('/drawers/1').data


def test_ambiguous_delivery_lock_and_status(app,client):
    setup_cabinet(app,client);configure(client)
    with patch('inventory.drawers.device_request',side_effect=ValueError('timeout')) as transport:
        r=post(client,'/drawers/1/command',action='light',row=1,col=1)
        assert r.json['status']=='unknown'
        assert post(client,'/drawers/1/command',action='light',row=1,col=2).status_code==409
        assert transport.call_count==1
    cid=r.json['command_id']
    assert configure(client).status_code==409
    with patch('inventory.drawers.device_request',return_value={'command_id':cid,'status':'completed'}):
        assert client.get('/drawers/1/status/'+cid).json['status']=='completed'
    assert configure(client).status_code==302


def test_permissions_validation_and_csrf(app,client):
    setup_cabinet(app,client)
    assert client.post('/drawers/1/command',data={'action':'open'}).status_code==400
    assert post(client,'/drawers/1/command',action='open',row=1,col=1).status_code==400
    assert post(client,'/drawers/1/command',action='light',row=1,col=1).status_code==409
    assert post(client,'/drawers/1/assign',row=17,col=1,component_id=1).status_code==404
    with sqlite3.connect(app.config['DATABASE']) as db: db.execute("UPDATE users SET role='viewer'")
    assert client.get('/drawers/1').status_code==200
    assert post(client,'/drawers/1/command',action='light',row=1,col=1).status_code==403
    assert post(client,'/drawers',name='No').status_code==403
    assert post(client,'/drawers/1/assign',row=1,col=1,component_id=1).status_code==403


def test_no_arbitrary_destinations_and_malformed_ack(app,client):
    setup_cabinet(app,client);configure(client)
    app.config['DEVICE_ENDPOINTS']={}
    with patch('inventory.drawers.device_request') as network:
        assert post(client,'/drawers/1/command',action='light',row=1,col=1).status_code==409
        network.assert_not_called()
    app.config['DEVICE_ENDPOINTS']={'1':['http://192.168.1.50']}
    with patch('inventory.drawers.device_request',return_value={'command_id':'wrong','status':'completed'}):
        assert post(client,'/drawers/1/command',action='light',row=1,col=1).json['status']=='unknown'
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT active FROM cabinet_commands').fetchone()[0]==1


def test_tenant_and_demo_isolation(app,client):
    setup_cabinet(app,client)
    from inventory.workspaces import initialize_inventory
    initialize_inventory(app,2)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("INSERT INTO workspaces(id,name) VALUES(2,'Other')")
        db.execute('UPDATE users SET workspace_id=2')
    assert client.get('/drawers/1').status_code==404
    assert post(client,'/drawers/1/command',action='light',row=1,col=1).status_code==404
    demo=app.test_client();demo.get('/demo')
    with demo.session_transaction() as s: token=s['csrf']
    demo.post('/demo',data={'csrf':token})
    assert demo.get('/drawers').status_code==403


def test_device_transport_is_authenticated_bounded_and_no_redirects(app,client):
    from inventory.drawers import cipher, device_request
    from flask import g
    from unittest.mock import MagicMock
    app.config['DEVICE_ENDPOINTS']={'1':['http://192.168.1.50']}
    with app.test_request_context():
        g.workspace={'id':1}
        device={'endpoint':'http://192.168.1.50','api_key':cipher().encrypt(b'private-device-key').decode()}
        response=MagicMock(status_code=202)
        response.iter_content.return_value=[b'{"command_id":"abc","status":"accepted"}']
        session=MagicMock();session.__enter__.return_value=session;session.request.return_value=response
        with patch('inventory.drawers.requests.Session',return_value=session):
            assert device_request(device,'POST','/api/commands',{'action':'light'})['status']=='accepted'
            args=session.request.call_args
            assert args.kwargs['headers']=={'Authorization':'Bearer private-device-key'}
            assert args.kwargs['allow_redirects'] is False and session.trust_env is False
            response.status_code=302
            with pytest.raises(ValueError): device_request(device,'POST','/api/commands',{})
            response.status_code=200;response.iter_content.return_value=[b'x'*8193]
            with pytest.raises(ValueError): device_request(device,'GET','/api/commands/abc')
            device['endpoint']='http://169.254.169.254'
            before=session.request.call_count
            with pytest.raises(ValueError): device_request(device,'GET','/api/commands/abc')
            assert session.request.call_count==before


def test_single_section_and_out_of_bounds_requests(app,client):
    setup_cabinet(app,client)
    assert post(client,'/drawers',name='Single',rows=8).status_code==302
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT COUNT(*) FROM cabinet_drawers WHERE cabinet_id=2').fetchone()[0]==64
    assert post(client,'/drawers/2/command',action='light',row=9,col=1).status_code==404
    assert post(client,'/drawers',name='Invalid',rows=17).status_code==400
    assert post(client,'/drawers/1/command',action='arbitrary',row=1,col=1).status_code==400


def test_manual_resolution_requires_owner_confirmation(app,client):
    setup_cabinet(app,client);configure(client)
    with patch('inventory.drawers.device_request',side_effect=ValueError('offline')):
        command=post(client,'/drawers/1/command',action='light',row=1,col=1).json['command_id']
    assert post(client,'/drawers/1/resolve',command_id=command).status_code==400
    with sqlite3.connect(app.config['DATABASE']) as db: db.execute("UPDATE users SET role='member'")
    assert post(client,'/drawers/1/resolve',command_id=command,confirmed=1).status_code==403
    with sqlite3.connect(app.config['DATABASE']) as db: db.execute("UPDATE users SET role='owner'")
    with patch('inventory.drawers.device_request') as network:
        assert post(client,'/drawers/1/resolve',command_id=command,confirmed=1).status_code==302
        network.assert_not_called()
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT active,status FROM cabinet_commands').fetchone()==(0,'manually resolved')
