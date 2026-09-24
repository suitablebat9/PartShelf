"""Public information, voluntary support, and private feedback administration."""
import hashlib
import re
import secrets
from functools import wraps
from urllib.parse import urlsplit
from xml.sax.saxutils import escape
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for, Response
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from .mailer import send_email, mail_ready

PUBLIC_ENDPOINTS = {'community.welcome','community.about','community.support','community.terms','community.privacy',
                    'community.feedback','community.email_preferences','community.robots','community.sitemap'}
INDEXABLE = {'community.welcome','community.about','community.support','community.terms','community.privacy','community.feedback'}
STATUSES = ('New', 'Reviewing', 'Planned', 'In progress', 'Released', 'Not planned')
PROMISE = 'I will never lock Partshelf features behind a paywall. Every feature is available without donating. Contributions are optional and help support hosting, maintenance, and development.'
TERMS = '''Partshelf Terms of Service
Effective September 24, 2026

Who operates Partshelf
Partshelf is provided by PCBStudios, based in Minnesota, United States. Questions can be sent to support@pcb-studios.com.

Using the service
By using Partshelf, you agree to these terms. You must have the legal capacity to enter this agreement and authority to act for any organization whose inventory you manage. Keep your credentials secure and use workspace roles responsibly. You are responsible for the content and activity in your account.

Free features and voluntary support
PCBStudios will not lock Partshelf features behind a paywall. Donations are voluntary, are not required for any feature, and do not purchase priority, a promised feature, ownership, or guaranteed availability. Payments are handled by Stripe under its applicable terms. A contribution is not represented as a tax-deductible charitable donation. For payment mistakes or refund requests, contact support with your Stripe receipt; mandatory consumer rights remain unaffected.

Your data and acceptable use
You retain ownership of your inventory and uploaded content. You permit PCBStudios to store and process it as needed to operate, secure, back up, and support Partshelf. Only upload information you have permission to use. Do not upload unlawful material, expose other people’s private information, attempt unauthorized access, distribute malware, or interfere with the service. Reasonable storage and request limits protect the service and apply independently of donations.

Inventory and project estimates
You are responsible for checking stock, component suitability, specifications, prices, and purchasing decisions. Project estimates may differ from supplier prices and exclude shipping and tax. Keep independent exports of important data.

Feedback
You may submit ideas of any size. Submission does not guarantee implementation or a release date. You allow PCBStudios to use suggestions to improve Partshelf without payment or attribution obligations. Do not include confidential information or material you are not authorized to share.

Availability, suspension, and closure
Partshelf may be changed, maintained, interrupted, or discontinued. Accounts or workspaces may be suspended for abuse, security concerns, or violations of these terms. You may request support, export your workspace when you have permission, and use the account or workspace deletion controls. Deletion may initially place records in recoverable administrative storage; backup copies may remain until removed through backup retention processes. Contact support about permanent removal.

Warranties and liability
To the extent permitted by applicable law, Partshelf is provided as available, without guarantees of uninterrupted operation, accuracy, or fitness for a particular purpose. PCBStudios is not responsible for indirect losses arising from reliance on inventory or cost estimates to the extent the law permits. Nothing in these terms excludes liability or rights that cannot legally be excluded.

Changes and applicable law
Material changes to these terms will be identified by an updated effective date and communicated through the service. The no-paywall commitment above remains part of these terms. Minnesota law applies to the extent permitted by law, without removing mandatory protections available where you live. Contact support@pcb-studios.com to discuss concerns or disputes.'''
PRIVACY = '''Information used to run Partshelf
Partshelf stores account identifiers, email addresses, protected authentication information, workspace membership, inventory, uploaded files, and activity needed to run and secure the service. Essential cookies support sign-in and security; Remember me is optional for 30 days.

Signup information
Administrative analytics may record referral website names, campaign parameters, signup method, approximate country supplied by Cloudflare, and sign-in times. Approximate country is not precise location. Technical service logs may include network addresses and requested URLs.

Feedback and email
Feedback is visible to the platform administrator, not other customers. Email is optional. If you request updates, we send a confirmation message and send feature-status updates only after confirmation. Each update includes a link to stop future updates. Do not submit confidential information in feedback.

Service providers
Cloudflare handles access to the hosted service. Google handles Google sign-in when selected and Google Workspace delivers business email. Optional contributions are processed on Stripe’s hosted checkout; Partshelf does not collect card details in its own forms. Provider privacy terms also apply to their services.

Storage and choices
Data is stored on the operator’s server and in backups. Users with permission can export inventory and use account/workspace deletion controls. Administrative recovery copies and backups may retain deleted records. Contact support@pcb-studios.com for privacy questions, correction requests, or permanent deletion requests. Do not upload sensitive information that is unnecessary for inventory management.'''
DEFAULTS = {'about_name':'Carson', 'about_text':"I'm the creator behind PCBStudios. I’m building Partshelf to make organizing components, planning projects, and finding the right part easier. Your suggestions help shape where it goes next.",
            'about_ai_heading':'Built with help from AI', 'about_ai_text':'AI tools, including OpenAI’s Codex, helped write code, explore designs, troubleshoot problems, and build features for Partshelf. The project’s direction and the decisions about what to build come from me and the people using it. I’m sharing that openly because I want you to know how the project was made.',
            'stripe_link':'', 'terms_text':TERMS, 'privacy_text':PRIVACY, 'google_verification':''}


def install_community(app, db, auth):
    bp = Blueprint('community', __name__)
    with app.app_context():
        db().executescript('''CREATE TABLE IF NOT EXISTS feedback(
            id INTEGER PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
            email TEXT NOT NULL DEFAULT '', verified INTEGER NOT NULL DEFAULT 0,
            subscribed INTEGER NOT NULL DEFAULT 0, nonce TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'New', update_text TEXT NOT NULL DEFAULT '',
            revision INTEGER NOT NULL DEFAULT 0, notified_revision INTEGER NOT NULL DEFAULT 0,
            created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE INDEX IF NOT EXISTS feedback_created ON feedback(created);''')
        for key, value in DEFAULTS.items():
            db().execute('INSERT OR IGNORE INTO site_settings VALUES(?,?)', (key,value))
        db().commit()

    def settings():
        return {row['key']:row['value'] for row in db().execute('SELECT * FROM site_settings')}

    def admin(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not getattr(g,'user',None) or g.demo or not g.user['platform_admin']:
                abort(403)
            return view(*args, **kwargs)
        return wrapped

    def token_for(row):
        return URLSafeTimedSerializer(app.secret_key, salt='feedback-email').dumps([row['id'],row['nonce']])

    def origin():
        value = app.config['PUBLIC_URL']
        if not value.startswith('https://'):
            raise ValueError('Public HTTPS URL must be configured before email updates are available.')
        return value

    @app.context_processor
    def public_metadata():
        values = settings()
        descriptions = {
            'community.welcome':('Partshelf — Free Electronics Inventory by PCBStudios','Organize electronic components, search specifications, plan projects, and print QR labels. Free features, shared workspaces, and a hands-on demo.'),
            'community.about':('About Partshelf and PCBStudios','Meet the creator of Partshelf, learn how AI helped build the project, and read our promise to never paywall features.'),
            'community.support':('Support Partshelf — Optional Donations','Help support Partshelf through optional Stripe contributions. Features will never be locked behind a paywall.'),
            'community.feedback':('Partshelf Feedback and Feature Requests','Share any idea, big or small. Optional verified-email updates keep you informed when a feature is planned or released.'),
            'community.terms':('Partshelf Terms of Service','Terms for using Partshelf, operated by PCBStudios in Minnesota.'),
            'community.privacy':('Partshelf Privacy Information','How Partshelf handles account, inventory, feedback, and signup information.')}
        title, description = descriptions.get(request.endpoint, ('Partshelf · Inventory','Partshelf by PCBStudios'))
        return dict(site=values, no_paywall=PROMISE, public_page=request.endpoint in INDEXABLE,
                    seo_title=title, seo_description=description,
                    canonical=app.config['PUBLIC_URL']+request.path if request.endpoint in INDEXABLE else '',
                    seo_schema={'@context':'https://schema.org','@type':'WebApplication','name':'Partshelf',
                        'url':app.config['PUBLIC_URL']+'/welcome','applicationCategory':'BusinessApplication',
                        'operatingSystem':'Web browser','description':descriptions['community.welcome'][1],
                        'offers':{'@type':'Offer','price':'0','priceCurrency':'USD'},
                        'creator':{'@type':'Organization','name':'PCBStudios','url':'https://pcb-studios.com/'}})

    @app.after_request
    def indexing_headers(response):
        if request.endpoint not in INDEXABLE | {'static','community.robots','community.sitemap'} or response.status_code != 200:
            response.headers['X-Robots-Tag']='noindex, nofollow'
        return response

    @bp.get('/welcome')
    def welcome():
        return render_template('welcome.html')

    @bp.get('/about')
    def about():
        return render_template('public_page.html', page='about')

    @bp.get('/support')
    def support():
        return render_template('public_page.html', page='support')

    @bp.get('/terms')
    def terms():
        return render_template('public_page.html', page='terms')

    @bp.get('/privacy')
    def privacy():
        return render_template('public_page.html', page='privacy')

    @bp.route('/feedback', methods=['GET','POST'])
    def feedback():
        if request.method=='POST':
            auth['limit']('feedback-ip:'+str(request.remote_addr), 100, 3600)
            if db().execute('SELECT COUNT(*) FROM feedback').fetchone()[0]>=10000:
                raise ValueError('The feedback inbox is full. Please contact support.')
            kind=request.form.get('kind','Feature request')
            title=request.form.get('title','').strip()
            body=request.form.get('body','').strip()
            email=request.form.get('email','').strip().lower()
            subscribe=bool(email and request.form.get('updates')=='1')
            if request.form.get('updates')=='1' and not email:
                raise ValueError('Enter an email address for updates, or uncheck email updates to submit anonymously.')
            if kind not in ('Feature request','Feedback','Bug report') or not 1<=len(title)<=150 or not 1<=len(body)<=5000:
                raise ValueError('Choose a feedback type and enter a title (up to 150 characters) and message (up to 5,000).')
            if email and (len(email)>254 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',email)):
                raise ValueError('Enter a valid email address or leave it blank.')
            if subscribe:
                if not mail_ready():
                    raise ValueError('Email updates are temporarily unavailable. Submit without email updates or try later.')
                origin()
                auth['limit']('feedback-email:'+hashlib.sha256(email.encode()).hexdigest(), 3, 86400)
            ident=db().execute('INSERT INTO feedback(kind,title,body,email,subscribed,nonce) VALUES(?,?,?,?,?,?)',
                (kind,title,body,email,int(subscribe),secrets.token_hex(32))).lastrowid
            db().commit()
            if subscribe:
                row=db().execute('SELECT * FROM feedback WHERE id=?',(ident,)).fetchone()
                try:
                    send_email(email,'Confirm Partshelf feature updates', 'You requested email updates for feedback submitted to Partshelf. Confirm within 48 hours:\n'+origin()+url_for('community.email_preferences',token=token_for(row))+'\n\nIf this was not you, ignore this message. No updates are sent until you confirm.')
                    flash('Thanks! Check your email to confirm feature-status updates.')
                except ValueError:
                    flash('Your feedback was saved, but the confirmation email could not be sent. Contact support if you want updates.','error')
            else:
                flash('Thanks for sharing your idea. Every suggestion, big or small, is welcome.')
            return redirect(url_for('community.feedback'))
        return render_template('feedback.html')

    @bp.route('/feedback/email/<token>', methods=['GET','POST'])
    def email_preferences(token):
        try:
            ident, nonce=URLSafeTimedSerializer(app.secret_key,salt='feedback-email').loads(token, max_age=365*86400)
        except (BadSignature,SignatureExpired,TypeError,ValueError):
            abort(400,'This email preference link is invalid or expired.')
        row=db().execute('SELECT * FROM feedback WHERE id=? AND nonce=?',(ident,nonce)).fetchone()
        if not row:
            abort(404)
        if request.method=='POST':
            if request.form.get('action')=='unsubscribe':
                db().execute('UPDATE feedback SET subscribed=0 WHERE id=?',(ident,))
                flash('Feature-status emails have been stopped.')
            elif request.form.get('action')=='confirm':
                try:
                    URLSafeTimedSerializer(app.secret_key,salt='feedback-email').loads(token,max_age=48*3600)
                except SignatureExpired:
                    abort(400,'Confirmation expired. Contact support for help.')
                db().execute('UPDATE feedback SET verified=1,subscribed=1 WHERE id=?',(ident,))
                flash('Email updates confirmed. You will receive future status updates.')
            else:
                abort(400)
            db().commit()
            return redirect(url_for('community.feedback'))
        return render_template('feedback_email.html', row=row)

    @bp.route('/management/site', methods=['GET','POST'])
    @admin
    @auth['recent']
    def site_admin():
        if request.method=='POST':
            current=settings()
            values={key:request.form.get(key,current.get(key,default)).strip() for key,default in DEFAULTS.items()}
            if len(values['about_name'])>100 or any(len(value)>30000 for value in values.values()):
                raise ValueError('Keep page text under 30,000 characters and the name under 100.')
            link=values['stripe_link']
            parsed=urlsplit(link)
            if link and (parsed.scheme!='https' or parsed.hostname not in ('buy.stripe.com','donate.stripe.com') or parsed.username or parsed.port or not parsed.path or parsed.path=='/'):
                raise ValueError('Use a Stripe-hosted Payment Link from buy.stripe.com or donate.stripe.com.')
            if values['google_verification'] and not re.fullmatch(r'[A-Za-z0-9_-]{10,200}',values['google_verification']):
                raise ValueError('Paste only the Google site verification token, not the HTML tag.')
            for key,value in values.items():
                db().execute('UPDATE site_settings SET value=? WHERE key=?',(value,key))
            db().commit();flash('Public site settings saved.')
            return redirect(url_for('community.site_admin'))
        return render_template('site_admin.html')

    def notify(row):
        if not (row['verified'] and row['subscribed'] and row['revision']>row['notified_revision']):
            return
        send_email(row['email'], 'Partshelf feature update: '+row['status'],
            'Your request: '+row['title']+'\nStatus: '+row['status']+'\n\n'+row['update_text']+
            '\n\nStop future updates: '+origin()+url_for('community.email_preferences',token=token_for(row)))
        db().execute('UPDATE feedback SET notified_revision=? WHERE id=?',(row['revision'],row['id']))
        db().commit()

    @bp.route('/management/feedback', methods=['GET','POST'])
    @admin
    def feedback_admin():
        if request.method=='POST':
            row=db().execute('SELECT * FROM feedback WHERE id=?',(request.form.get('id'),)).fetchone()
            if not row:
                abort(404)
            if request.form.get('action')!='retry':
                status=request.form.get('status','')
                note=request.form.get('update_text','').strip()
                if status not in STATUSES or len(note)>5000:
                    raise ValueError('Select a status and keep the update under 5,000 characters.')
                changed=db().execute('UPDATE feedback SET status=?,update_text=?,revision=revision+1,updated=CURRENT_TIMESTAMP WHERE id=? AND revision=? AND (status!=? OR update_text!=?)',
                    (status,note,row['id'],request.form.get('revision'),status,note)).rowcount
                if not changed and (status!=row['status'] or note!=row['update_text']):
                    abort(409,'This request changed in another tab. Reload before saving.')
                db().commit()
            row=db().execute('SELECT * FROM feedback WHERE id=?',(row['id'],)).fetchone()
            try:
                notify(row)
                flash('Feedback status saved. Confirmed subscribers receive changed-status updates.')
            except ValueError:
                flash('Status saved, but email delivery failed. Use Retry email after checking mail settings.','error')
            return redirect(url_for('community.feedback_admin'))
        try:
            page=max(1,int(request.args.get('page','1')))
        except ValueError:
            abort(400)
        entries=db().execute('SELECT * FROM feedback ORDER BY id DESC LIMIT 51 OFFSET ?',((page-1)*50,)).fetchall()
        return render_template('feedback_admin.html', entries=entries[:50], has_next=len(entries)>50, page=page, statuses=STATUSES)

    @bp.get('/robots.txt')
    def robots():
        return Response('User-agent: *\nAllow: /\nSitemap: '+app.config['PUBLIC_URL']+'/sitemap.xml\n',mimetype='text/plain')

    @bp.get('/sitemap.xml')
    def sitemap():
        paths=['/welcome','/about','/support','/feedback','/terms','/privacy']
        return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join('<url><loc>'+escape(app.config['PUBLIC_URL']+path)+'</loc></url>' for path in paths)+'</urlset>',mimetype='application/xml')

    app.register_blueprint(bp)
