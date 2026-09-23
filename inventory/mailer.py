"""TLS-only business email delivery and opt-in low-stock alerts."""
import smtplib
import ssl
import time
from decimal import Decimal
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from flask import current_app


def mail_ready():
    return bool(current_app.config.get('SMTP_HOST') and current_app.config.get('SMTP_USERNAME') and current_app.config.get('SMTP_PASSWORD'))


def send_email(recipient, subject, text):
    if not mail_ready():
        raise ValueError('Business email delivery has not been configured on the server yet.')
    message = EmailMessage()
    sender = parseaddr(current_app.config['MAIL_FROM'])[1]
    if not sender or '@' not in sender or any(c in sender for c in '\r\n'):
        raise ValueError('Configure a valid business sender address on the server.')
    message['From'] = formataddr(('PCB Studios · Partshelf', sender))
    message['To'] = recipient
    message['Reply-To'] = 'support@pcb-studios.com'
    message['Subject'] = subject
    message.set_content(text + '\n\nPartshelf by PCB Studios\nSupport: support@pcb-studios.com\n')
    config = current_app.config
    try:
        if config['SMTP_PORT'] == 465:
            client = smtplib.SMTP_SSL(config['SMTP_HOST'], 465, timeout=15, context=ssl.create_default_context())
        else:
            client = smtplib.SMTP(config['SMTP_HOST'], config['SMTP_PORT'], timeout=15)
        with client:
            if config['SMTP_PORT'] != 465:
                client.starttls(context=ssl.create_default_context())
            client.login(config['SMTP_USERNAME'], config['SMTP_PASSWORD'])
            client.send_message(message, from_addr=sender, to_addrs=[recipient])
    except (smtplib.SMTPException, OSError):
        raise ValueError('Email could not be sent. Check the server’s Google Workspace mail configuration.') from None


def deliver_stock_alerts(db, users=None):
    """One alert per low-stock episode and recipient; retries after 15 minutes."""
    sent = failed = 0
    if not mail_ready():
        return sent, failed
    if users is None:
        users = db.execute('SELECT id,email FROM users WHERE low_stock_email=1 AND email_verified=1').fetchall()
    for user in users:
        items = db.execute('SELECT id FROM components').fetchall()
        for item in items:
            db.execute('BEGIN IMMEDIATE')
            try:
                part = db.execute('SELECT * FROM components WHERE id=?', (item['id'],)).fetchone()
                low = part['low_stock'] is not None and Decimal(str(part['stock'])) <= Decimal(part['low_stock'])
                if not low:
                    db.execute('DELETE FROM stock_alerts WHERE user_id=? AND component_id=?', (user['id'], part['id']))
                    db.commit()
                    continue
                db.execute('INSERT OR IGNORE INTO stock_alerts(user_id,component_id) VALUES(?,?)', (user['id'], part['id']))
                state = db.execute('SELECT * FROM stock_alerts WHERE user_id=? AND component_id=?', (user['id'], part['id'])).fetchone()
                if state['sent'] or state['last_attempt'] > time.time()-900:
                    db.commit()
                    continue
                db.execute('UPDATE stock_alerts SET last_attempt=? WHERE user_id=? AND component_id=?', (int(time.time()), user['id'], part['id']))
                try:
                    send_email(user['email'], 'Partshelf: low stock — ' + part['name'],
                               f"{part['name']} ({part['name_id']}) is low on stock.\nRemaining: {part['stock']:g} {part['unit']}\nAlert threshold: {part['low_stock']}\n\n{current_app.config['PUBLIC_URL']}/components/{part['id']}")
                    db.execute('UPDATE stock_alerts SET sent=1 WHERE user_id=? AND component_id=?', (user['id'], part['id']))
                    sent += 1
                except ValueError:
                    failed += 1
                db.commit()
            except Exception:
                db.rollback()
                raise
    return sent, failed
