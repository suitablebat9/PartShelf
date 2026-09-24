from test_inventory import app,client,post
from test_community_projects import make_admin


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
