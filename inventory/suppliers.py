"""Conservative supplier defaults from the product hostname."""
from urllib.parse import urlsplit

def supplier_from_url(value):
    try:
        url=urlsplit(value)
        host=(url.hostname or '').lower().removeprefix('www.')
        if url.scheme not in ('http','https'): return ''
    except ValueError:
        return ''
    brands={'digikey.com':'Digi-Key','digikey.ca':'Digi-Key','mouser.com':'Mouser','aliexpress.com':'AliExpress','amazon.com':'Amazon','lcsc.com':'LCSC','adafruit.com':'Adafruit','sparkfun.com':'SparkFun','ebay.com':'eBay'}
    return next((name for domain,name in brands.items() if host==domain or host.endswith('.'+domain)),host)
