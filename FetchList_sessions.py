import json
import requests
import logging
from docxtpl import DocxTemplate
from bs4 import BeautifulSoup
from Queue import Queue
from threading import Thread
from xml.sax.saxutils import escape

#try:
#    from http.client import HTTPConnection # py3
#except ImportError:
#    from httplib import HTTPConnection # py2

#logging.basicConfig(level=logging.DEBUG)

class CaseWorker(Thread):
    def __init__(self, q):
        Thread.__init__(self)
        self.q = q

    def run(self):
        while True:
            case = self.q.get()
            print "case:" + str(case['case_id'])
            case_id = case['case_id']
            case_type = case_id.split(' ')[0]
            case_no = case_id.split(' ')[1].split('/')
            try:
                pet, resp = CaseDetails().getCaseDetails(case_type, case_no[0], case_no[1])
                case['petitioner'] = escape(pet)
                case['respondent'] = escape(resp)
            except:
                print "Could not find case details for:" + str(case_id)
                case['petitioner'] = ''
                case['respondent'] = ''
            self.q.task_done()

class CaseDetails():
    def __init__(self):
        self.test = "test"

    def getCaseDetails(self, case_type, case_no, year):
        res = requests.get("http://hc.tap.nic.in/csis/MainInfo.jsp?mtype={}&mno={}&year={}".format(case_type, case_no, year))
        #print res.text
        soup = BeautifulSoup(res.text, 'html.parser')
        pet = soup.find('b',text="PETITIONER")
        petitioner = pet.find_next('b').find_next('b')
        respondent = petitioner.find_next('b').find_next('b').find_next('b')
        print "Petitioner:" + petitioner.text
        print "respondent:" + respondent.text
        return petitioner.text,respondent.text

class FetchList():

    def __init__(self):
        self.test = "test"


    def get_dates(self):
        s = requests.Session()
        r0 = s.post('http://hc.tap.nic.in/Hcdbs/searchdates.do', data = {'causelisttype':'D'})
        r = s.get('http://hc.tap.nic.in/Hcdbs/getdates.jsp?listtype=D')
        resp = r.text.strip()
        dates = resp.split('@')
        return dates[0]

    def get_causelist(self, date):
        #HTTPConnection.debuglevel = 1
        s = requests.Session()
        r0 = s.post('http://hc.tap.nic.in/Hcdbs/searchdates.do', data = {'causelisttype':'D'})
        r = s.get('http://hc.tap.nic.in/Hcdbs/getdates.jsp?listtype=D')
        resp = r.text.strip()
        dates = resp.split('@')
        print dates[0]
        r2 = s.post('http://hc.tap.nic.in/Hcdbs/searchtypeinput.do', data = {'listdate': date, 'caset': 'advcdsearch'})
        print r2.cookies
        #cookies = dict(jsessionid=r2.cookies['JSESSIONID'])
        r3 = s.post('http://hc.tap.nic.in/Hcdbs/searchtype.do', data = {'advcd' : '4199' })
        soup = BeautifulSoup(r3.text, 'html.parser')
        courts = soup.find_all('td', attrs = {'data-label': 'Court'})
        c_list = []
        q = Queue()
        # Set up some threads to fetch the enclosures
        for i in range(10):
            worker = CaseWorker(q)
            worker.setDaemon(True)
            worker.start()

        for court in courts:
            c = {}
            print '--------'
            print court.text
            c['ct_no'] = court.text
            c['cj1'] =  court.find_next('td', attrs = {'data-label': 'CORAM1'}).text.split('JUSTICE').pop().strip()
            cj2 = court.find_next('td', attrs = {'data-label': 'CORAM2'})
            c['cj2'] = cj2.text.split('JUSTICE').pop().strip() if cj2 else ''
            cases = {}
            cur_stage = ''
            for court_sib in court.find_all_next('td'):
                #print "text:" + court_sib.text
                if not court_sib.has_key('data-label') or court_sib['data-label'] == 'CORAM1' or court_sib['data-label'] == 'CORAM2':
                    continue
                elif court_sib['data-label'] == 'Court':
                    break
                elif court_sib['data-label'] == 'Stage':
                    cur_stage = court_sib.text
                elif court_sib['data-label'] == 'S.No':
                    cur_sno = int(court_sib.text.strip('.'))
                    cases[cur_sno] = {"stage": cur_stage}
                elif  court_sib['data-label'] == 'Case No.' or court_sib['data-label'] == 'Sub case No.':
                    #print "case_no:" + court_sib.text
                    if not (court_sib.text.startswith('- -/-') or court_sib.text.startswith('.') or court_sib.text.startswith('WPMP') or court_sib.text.startswith('WVMP') or court_sib.text.startswith('WAMP')):
                        case_id = {'case_id': court_sib.text}
                        cases[cur_sno].setdefault('caseno',[]).append(case_id)
                        q.put(case_id)
                        # Add to queue cases[cur_sno]
            cases_to_list = []
            q.join()
            #print "cases:" + str(cases)
            for key,val in cases.iteritems():
                val['id'] = key
                cases_to_list.append(val)
            cases_to_list = sorted(cases_to_list, key = lambda x: x['id'])
            print(json.dumps(cases_to_list, indent=4))
            c['cases'] = cases_to_list
            c_list.append(c)
        #print(json.dumps(c_list, sort_keys=True, indent=4))
        return c_list

    def convertToCauseListDocx(self):
        fetchList = FetchList()
        date = fetchList.get_dates()
        causelist = fetchList.get_causelist(date)
        context = { 'causelist': causelist, 'date': date }
        #print "printing the context:"
        #print(json.dumps(context, sort_keys=True, indent=4))
        tpl=DocxTemplate('causelists.docx')
        tpl.render(context)
        tpl.save('causelists_result.docx')

fetchList = FetchList()
fetchList.convertToCauseListDocx()
caseDetails = CaseDetails()
caseDetails.getCaseDetails('WP', '37427', '2013')
