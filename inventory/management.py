"""Public onboarding and workspace administration; inventory never switches by URL."""
import os
import re
import secrets
import time
from functools import wraps
from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash
from .mailer import mail_ready, send_email
from .workspaces import initialize_inventory

ROLES = ('owner', 'admin', 'member', 'viewer')


def install_management(app, db, auth):
    bp = Blueprint('manage', __name__)

    def audit(action, workspace_id, detail=''):
        db().execute('INSERT INTO management_audit(actor_id,workspace_id,action,detail) VALUES(?,?,?,?)',
                     (g.user['id'] if getattr(g, 'user', None) else None, workspace_id, action, detail))

    def email_value(value):
        value = value.strip().lower()
        if len(value) > 254 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', value):
            raise ValueError('Enter a valid email address.')
        return value

    def credentials():
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not re.fullmatch(r'[A-Za-z0-9_.@+-]{3,80}', username):
            raise ValueError('Use 3–80 letters, numbers, dots, underscores, @, + or - for your username.')
        if len(password) < 8 or len(password) > 256:
            raise ValueError('Use a password between 8 and 256 characters.')
        if password != request.form.get('password_confirm'):
            raise ValueError('Passwords do not match.')
        if db().execute('SELECT 1 FROM users WHERE username=? COLLATE NOCASE', (username,)).fetchone():
            raise ValueError('That username is unavailable.')
        return username, generate_password_hash(password)

    def public_origin():
        origin = app.config['PUBLIC_URL']
        if not origin.startswith('https://'):
            raise ValueError('Public HTTPS access must be configured first.')
        return origin

    def registration_open():
        return db().execute("SELECT value FROM site_settings WHERE key='registration_enabled'").fetchone()[0] == '1'

    def new_workspace(name):
        name = name.strip()
        if not name or len(name) > 100:
            raise ValueError('Enter a workspace name of up to 100 characters.')
        if db().execute('SELECT COUNT(*) FROM workspaces').fetchone()[0] >= int(os.environ.get('MAX_WORKSPACES', '1000')):
            raise ValueError('New workspace capacity has been reached. Contact support.')
        workspace_id = db().execute('INSERT INTO workspaces(name) VALUES(?)', (name,)).lastrowid
        initialize_inventory(app, workspace_id)
        return workspace_id

    def authorize(workspace_id):
        workspace = db().execute('SELECT * FROM workspaces WHERE id=?', (workspace_id,)).fetchone()
        if not workspace:
            abort(404)
        if not g.user['platform_admin'] and not (g.user['workspace_id'] == workspace_id and g.user['role'] in ('owner', 'admin')):
            abort(403)
        return workspace

    def platform(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not g.user or not g.user['platform_admin']:
                abort(403)
            return view(*args, **kwargs)
        return wrapped

    def revoke(user_id):
        for table in ('auth_sessions', 'auth_challenges'):
            db().execute(f'DELETE FROM {table} WHERE user_id=?', (user_id,))
        db().execute('DELETE FROM invitations WHERE created_by=?', (user_id,))

    @bp.route('/register', methods=['GET', 'POST'])
    def register():
        ready = registration_open() and mail_ready() and app.config['PUBLIC_URL'].startswith('https://')
        if request.method == 'POST':
            if not ready:
                raise ValueError('Registration is currently unavailable. Contact support.')
            auth['limit']('signup-ip:'+str(request.remote_addr), 10, 3600)
            email = email_value(request.form.get('email', ''))
            auth['limit']('signup-email:'+email, 3, 3600)
            username, password = credentials()
            name = request.form.get('workspace_name', '').strip()
            if not name or len(name) > 100:
                raise ValueError('Enter a workspace name of up to 100 characters.')
            if db().execute('SELECT 1 FROM users WHERE email=? COLLATE NOCASE', (email,)).fetchone():
                raise ValueError('This email already has an account. Sign in or reset your password.')
            code = f'{secrets.randbelow(1000000):06d}'
            auth['challenge']('registration', payload=dict(username=username, password=password, email=email, name=name), code=code)
            send_email(email, 'Verify your new Partshelf workspace', f'Your verification code is {code}. It expires in 10 minutes. Ignore this email if you did not request an account.')
            return redirect(url_for('manage.verify_registration'))
        return render_template('register.html', ready=ready)

    @bp.route('/register/verify', methods=['GET', 'POST'])
    def verify_registration():
        if not registration_open():
            abort(403)
        if request.method == 'POST':
            auth['limit']('signup-verify:'+str(request.remote_addr), 20, 900)
            payload = auth['consume']('registration', request.form.get('code', ''))['payload']
            db().execute('BEGIN IMMEDIATE')
            try:
                if db().execute('SELECT 1 FROM users WHERE username=? COLLATE NOCASE OR email=? COLLATE NOCASE', (payload['username'], payload['email'])).fetchone():
                    raise ValueError('The username or email is already registered. Start again.')
                workspace_id = new_workspace(payload['name'])
                db().execute("INSERT INTO users(username,password,email,email_verified,workspace_id,role) VALUES(?,?,?,1,?,'owner')",
                             (payload['username'], payload['password'], payload['email'], workspace_id))
                audit('workspace.registered', workspace_id)
                db().commit()
            except Exception:
                db().rollback()
                raise
            flash('Workspace created. Sign in with your new account.')
            return redirect(url_for('login'))
        auth['get_challenge']('registration')
        return render_template('registration_verify.html')

    @bp.get('/management')
    def dashboard():
        if g.user['platform_admin']:
            workspaces = db().execute('SELECT w.*,COUNT(u.id) AS members FROM workspaces w LEFT JOIN users u ON u.workspace_id=w.id GROUP BY w.id ORDER BY w.id DESC').fetchall()
            logs = db().execute('SELECT a.*,u.username FROM management_audit a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 100').fetchall()
            return render_template('management.html', workspaces=workspaces, logs=logs, registration_open=registration_open(), mail_ready=mail_ready())
        authorize(g.user['workspace_id'])
        return redirect(url_for('manage.workspace', workspace_id=g.user['workspace_id']))

    @bp.post('/management/registration')
    @platform
    @auth['recent']
    def registration_setting():
        db().execute("UPDATE site_settings SET value=? WHERE key='registration_enabled'", ('1' if request.form.get('enabled') else '0',))
        audit('registration.changed', None)
        db().commit()
        return redirect(url_for('manage.dashboard'))

    @bp.post('/management/workspaces')
    @platform
    @auth['recent']
    def create_workspace():
        db().execute('BEGIN IMMEDIATE')
        try:
            workspace_id = new_workspace(request.form.get('name', ''))
            audit('workspace.created', workspace_id)
            db().commit()
        except Exception:
            db().rollback()
            raise
        flash('Workspace created. Invite its owner below.')
        return redirect(url_for('manage.workspace', workspace_id=workspace_id))

    @bp.get('/management/workspaces/<int:workspace_id>')
    def workspace(workspace_id):
        current = authorize(workspace_id)
        members = db().execute('SELECT id,username,email,role,active,platform_admin FROM users WHERE workspace_id=? ORDER BY username', (workspace_id,)).fetchall()
        invitations = db().execute('SELECT token_hash,email,role,expires FROM invitations WHERE workspace_id=? AND expires>?', (workspace_id, int(time.time()))).fetchall()
        return render_template('workspace_management.html', workspace=current, members=members, invitations=invitations, roles=ROLES, mail_ready=mail_ready())

    @bp.post('/management/workspaces/<int:workspace_id>/settings')
    @auth['recent']
    def workspace_settings(workspace_id):
        authorize(workspace_id)
        name = request.form.get('name', '').strip()
        if not name or len(name) > 100:
            raise ValueError('Enter a workspace name of up to 100 characters.')
        db().execute('UPDATE workspaces SET name=? WHERE id=?', (name, workspace_id))
        audit('workspace.renamed', workspace_id)
        db().commit()
        return redirect(url_for('manage.workspace', workspace_id=workspace_id))

    @bp.post('/management/workspaces/<int:workspace_id>/status')
    @platform
    @auth['recent']
    def workspace_status(workspace_id):
        authorize(workspace_id)
        if workspace_id == g.user['workspace_id']:
            raise ValueError('You cannot suspend your own platform administration workspace.')
        active = int(request.form.get('active') == '1')
        db().execute('BEGIN IMMEDIATE')
        db().execute('UPDATE workspaces SET active=? WHERE id=?', (active, workspace_id))
        for member in db().execute('SELECT id FROM users WHERE workspace_id=?', (workspace_id,)).fetchall():
            revoke(member['id'])
        if not active:
            db().execute('DELETE FROM invitations WHERE workspace_id=?', (workspace_id,))
        audit('workspace.enabled' if active else 'workspace.suspended', workspace_id)
        db().commit()
        return redirect(url_for('manage.workspace', workspace_id=workspace_id))

    @bp.post('/management/workspaces/<int:workspace_id>/members/<int:user_id>')
    @auth['recent']
    def member_change(workspace_id, user_id):
        authorize(workspace_id)
        db().execute('BEGIN IMMEDIATE')
        target = db().execute('SELECT * FROM users WHERE id=? AND workspace_id=?', (user_id, workspace_id)).fetchone()
        if not target:
            abort(404)
        role = request.form.get('role', '')
        active = int(request.form.get('active') == '1')
        if role not in ROLES:
            raise ValueError('Choose a valid role.')
        if target['platform_admin'] or target['id'] == g.user['id']:
            raise ValueError('You cannot change your own role/access or a platform administrator here.')
        if not g.user['platform_admin'] and g.user['role'] != 'owner' and (target['role'] in ('owner', 'admin') or role in ('owner', 'admin')):
            abort(403)
        if target['role'] == 'owner' and target['active'] and (role != 'owner' or not active):
            if db().execute("SELECT COUNT(*) FROM users WHERE workspace_id=? AND role='owner' AND active=1 AND id!=?", (workspace_id, user_id)).fetchone()[0] == 0:
                raise ValueError('Keep at least one active workspace owner.')
        db().execute('UPDATE users SET role=?,active=? WHERE id=?', (role, active, user_id))
        revoke(user_id)
        audit('member.changed', workspace_id, f'user={user_id}; role={role}; active={active}')
        db().commit()
        return redirect(url_for('manage.workspace', workspace_id=workspace_id))

    @bp.post('/management/workspaces/<int:workspace_id>/invite')
    @auth['recent']
    def invite(workspace_id):
        current = authorize(workspace_id)
        if not current['active']:
            raise ValueError('Reactivate the workspace before inviting staff.')
        email = email_value(request.form.get('email', ''))
        role = request.form.get('role', 'member')
        if role not in ROLES or (not g.user['platform_admin'] and g.user['role'] != 'owner' and role in ('owner', 'admin')):
            abort(403)
        auth['limit']('invite:'+str(g.user['id']), 20, 3600)
        origin = public_origin()
        token = secrets.token_urlsafe(32)
        db().execute('DELETE FROM invitations WHERE expires<? OR (workspace_id=? AND email=?)', (int(time.time()), workspace_id, email))
        db().execute('INSERT INTO invitations VALUES(?,?,?,?,?,?)', (auth['digest'](token), workspace_id, email, role, int(time.time())+48*3600, g.user['id']))
        audit('member.invited', workspace_id, email)
        db().commit()
        link = origin + url_for('manage.accept_invite', token=token)
        if request.form.get('send_email') == '1':
            send_email(email, 'Invitation to '+current['name']+' on Partshelf', f'You have been invited to join {current["name"]} as {role}.\n\n{link}\n\nThis link expires in 48 hours. Ignore it if unexpected.')
            flash('Invitation sent.')
            return redirect(url_for('manage.workspace', workspace_id=workspace_id))
        return render_template('invitation_created.html', link=link, workspace=current, email=email)

    @bp.post('/management/workspaces/<int:workspace_id>/invites/revoke')
    @auth['recent']
    def revoke_invite(workspace_id):
        authorize(workspace_id)
        db().execute('DELETE FROM invitations WHERE token_hash=? AND workspace_id=?', (request.form.get('token_hash', ''), workspace_id))
        audit('invitation.revoked', workspace_id)
        db().commit()
        return redirect(url_for('manage.workspace', workspace_id=workspace_id))

    @bp.route('/invite/<token>', methods=['GET', 'POST'])
    def accept_invite(token):
        invitation = db().execute('SELECT i.*,w.name FROM invitations i JOIN workspaces w ON w.id=i.workspace_id WHERE i.token_hash=? AND i.expires>? AND w.active=1', (auth['digest'](token), int(time.time()))).fetchone()
        if not invitation:
            abort(404, 'This invitation has expired or was revoked.')
        if request.method == 'POST':
            auth['limit']('invite-accept:'+str(request.remote_addr), 20, 3600)
            username, password = credentials()
            db().execute('BEGIN IMMEDIATE')
            try:
                # Revalidate single-use status inside the write transaction.
                removed = db().execute('DELETE FROM invitations WHERE token_hash=? AND expires>? AND workspace_id IN (SELECT id FROM workspaces WHERE active=1)', (invitation['token_hash'], int(time.time()))).rowcount
                if not removed:
                    raise ValueError('This invitation has expired or was used.')
                if db().execute('SELECT COUNT(*) FROM users WHERE workspace_id=?', (invitation['workspace_id'],)).fetchone()[0] >= int(os.environ.get('MAX_WORKSPACE_MEMBERS', '100')):
                    raise ValueError('Workspace member capacity has been reached.')
                if db().execute('SELECT 1 FROM users WHERE username=? COLLATE NOCASE OR email=? COLLATE NOCASE', (username, invitation['email'])).fetchone():
                    raise ValueError('This username or email already has an account. Use a different account email; accounts belong to one workspace.')
                db().execute('INSERT INTO users(username,password,email,workspace_id,role) VALUES(?,?,?,?,?)', (username, password, invitation['email'], invitation['workspace_id'], invitation['role']))
                audit('invitation.accepted', invitation['workspace_id'])
                db().commit()
            except Exception:
                db().rollback()
                raise
            flash('Account created. Sign in to your workspace.')
            return redirect(url_for('login'))
        return render_template('accept_invitation.html', invitation=invitation)

    @bp.route('/forgot-password', methods=['GET', 'POST'])
    def forgot_password():
        if request.method == 'POST':
            auth['limit']('reset-ip:'+str(request.remote_addr), 10, 3600)
            email = email_value(request.form.get('email', ''))
            auth['limit']('reset-email:'+email, 3, 3600)
            user = db().execute('SELECT u.* FROM users u JOIN workspaces w ON w.id=u.workspace_id WHERE u.email=? COLLATE NOCASE AND u.email_verified=1 AND u.active=1 AND w.active=1', (email,)).fetchone()
            if user and mail_ready():
                code = f'{secrets.randbelow(1000000):06d}'
                auth['challenge']('password_reset', user['id'], code=code)
                send_email(email, 'Reset your Partshelf password', f'Your password reset code is {code}. Enter it in the browser where you requested it. It expires in 10 minutes. If you did not request this, ignore it.')
            else:
                # Same response and browser challenge shape for unknown/unverified accounts.
                auth['challenge']('password_reset', payload={'unavailable': True}, code=secrets.token_hex(32))
            return redirect(url_for('manage.reset_password'))
        return render_template('forgot_password.html')

    @bp.route('/reset-password', methods=['GET', 'POST'])
    def reset_password():
        if request.method == 'POST':
            auth['limit']('reset-verify:'+str(request.remote_addr), 20, 900)
            password = request.form.get('password', '')
            if not 8 <= len(password) <= 256 or password != request.form.get('password_confirm'):
                raise ValueError('Passwords must match and contain 8–256 characters.')
            pending = auth['consume']('password_reset', request.form.get('code', ''))
            if not pending['user_id']:
                raise ValueError('Invalid reset request.')
            db().execute('UPDATE users SET password=? WHERE id=?', (generate_password_hash(password), pending['user_id']))
            revoke(pending['user_id'])
            audit('password.reset', None, 'user='+str(pending['user_id']))
            db().commit()
            session.clear()
            flash('Password reset. Sign in again; your existing two-step verification still applies.')
            return redirect(url_for('login'))
        return render_template('reset_password.html')

    app.register_blueprint(bp)
