import requests
import logging

try:
    from http.client import HTTPConnection # py3
except ImportError:
    from httplib import HTTPConnection # py2

logging.basicConfig(level=logging.DEBUG)
class FetchList():

    def __init__(self):
        self.test = "test"

    def get_causelist_dates(self):
        HTTPConnection.debuglevel = 1
        r = requests.get('http://hc.tap.nic.in/Hcdbs/getdates.jsp?listtype=D')
        resp = r.text.strip()
        dates = resp.split('@')
        print dates[0]
        r2 = requests.post('http://hc.tap.nic.in/Hcdbs/searchtypeinput.do', data = {'listdate': dates[0], 'caset': 'advcdsearch'}, cookies = r.cookies)
        print r2.cookies
        #cookies = dict(jsessionid=r2.cookies['JSESSIONID'])
        r3 = requests.post('http://hc.tap.nic.in/Hcdbs/searchtype.do', data = {'advcd' : '4199' }, cookies = r.cookies)
        print r3.text

test = FetchList()
test.get_causelist_dates()
