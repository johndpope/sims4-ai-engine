import webbrowser
import hashlib
webbrowser.open('http://xkcd.com/353/')

def geohash(latitude, longitude, datedow):
    h = hashlib.md5(datedow).hexdigest()
    (p, q) = ['%f' % float.fromhex('0.' + x) for x in (h[:16], h[16:32])]
    print('%d%s %d%s' % (latitude, p[1:], longitude, q[1:]))

