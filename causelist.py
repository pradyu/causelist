import json
import requests
import logging
from docxtpl import DocxTemplate
from bs4 import BeautifulSoup
from Queue import Queue
from threading import Thread
from xml.sax.saxutils import escape
import argparse

#try:
#    from http.client import HTTPConnection # py3
#except ImportError:
#    from httplib import HTTPConnection # py2

#logging.basicConfig(level=logging.DEBUG)
NUMBER_OF_WORKERS = 15
SEARCH_TYPE_URL = 'http://hc.tap.nic.in/Hcdbs/searchtype.do'
SEARCH_INPUT_URL = 'http://hc.tap.nic.in/Hcdbs/searchtypeinput.do'
DATES_URL = 'http://hc.tap.nic.in/Hcdbs/getdates.jsp?listtype=D'
SEARCH_DATES_URL = 'http://hc.tap.nic.in/Hcdbs/searchdates.do'
MAIN_INFO_URL = "http://hc.tap.nic.in/csis/MainInfo.jsp?mtype={}&mno={}&year={}"

JUDGE2_LABEL = 'CORAM2'
JUDGE1_LABEL = 'CORAM1'
IGNORED_CASE_TYPES = '- -/-', '.', 'WPMP', 'WVMP', 'WAMP', 'CRLPMP'
DATA_LABEL = 'data-label'
SKIP_SAME_SERIAL_NO = True


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
        res = requests.get(MAIN_INFO_URL.format(case_type, case_no, year))
        #print res.text
        soup = BeautifulSoup(res.text, 'html.parser')
        pet = soup.find('b',text="PETITIONER")
        petitioner = pet.find_next('b').find_next('b')
        respondent = petitioner.find_next('b').find_next('b').find_next('b')
        print "Petitioner:" + petitioner.text
        print "respondent:" + respondent.text
        return petitioner.text,respondent.text


class FetchList:

    def __init__(self, number_of_workers):
        self.worker_queue = Queue()
        for i in range(number_of_workers):
            worker = CaseWorker(self.worker_queue)
            worker.setDaemon(True)
            worker.start()

    def get_dates(self, session=requests.Session()):
        r0 = session.post(SEARCH_DATES_URL, data = {'causelisttype': 'D'})
        r = session.get(DATES_URL)
        resp = r.text.strip()
        dates = resp.split('@')
        return dates[0]

    def get_causelist(self, date, adv_codes):
        #HTTPConnection.debuglevel = 1
        s = requests.Session()
        self.get_dates(s)
        r2 = s.post(SEARCH_INPUT_URL, data = {'listdate': date, 'caset': 'advcdsearch'})
        print r2.cookies
        court = {}
        for adv_code in adv_codes:
            r3 = s.post(SEARCH_TYPE_URL, data={'advcd': adv_code})
            soup = BeautifulSoup(r3.text, 'html.parser')
            courts_data = soup.find_all('td', attrs = {DATA_LABEL: 'Court'})
            causelist = []
            # Set up some threads to fetch the enclosures

            for court_data in courts_data:
                print '--------'
                print court_data.text
                court_number = court_data.text
                court_number = int(court_number.split('COURT NO.').pop().strip())
                court.setdefault(court_number, {})
                cj1 = court_data.find_next('td', attrs = {DATA_LABEL: JUDGE1_LABEL})
                court[court_number]['cj1'] =  cj1.text.split('JUSTICE').pop().strip()
                cj2 = cj1.find_next('td')
                if cj2.has_key(DATA_LABEL) and cj2[DATA_LABEL] == JUDGE2_LABEL:
                    court[court_number]['cj2'] = cj2.text.split('JUSTICE').pop().strip()
                else:
                    court[court_number]['cj2'] = ''
                cases = {}
                cur_stage = ''
                self.get_cases_by_court(cases, court_data, cur_stage, self.worker_queue, adv_code)
                court[court_number].setdefault('cases', {})
                court[court_number]['cases'].update(cases)
                self.worker_queue.join()
        return court

    def get_cases_by_court(self, cases, court_data, cur_stage, worker_queue, adv_code):
        for court_sib in court_data.find_all_next('td'):
            # print "text:" + court_sib.text
            if not court_sib.has_key(DATA_LABEL) or court_sib[DATA_LABEL] == JUDGE1_LABEL or court_sib[DATA_LABEL] == JUDGE2_LABEL:
                continue
            elif court_sib[DATA_LABEL] == 'Court':
                break
            elif court_sib[DATA_LABEL] == 'Stage':
                cur_stage = court_sib.text
            elif court_sib[DATA_LABEL] == 'S.No':
                case_id_processed = False
                cur_sno = int(court_sib.text.strip('.'))
                cases[cur_sno] = {"stage": cur_stage, 'adv_code': adv_code}
            elif court_sib[DATA_LABEL] == 'Case No.' or court_sib[DATA_LABEL] == 'Sub case No.':
                # print "case_no:" + court_sib.text
                if not (court_sib.text.startswith((IGNORED_CASE_TYPES))) and not (case_id_processed and SKIP_SAME_SERIAL_NO):
                    case_id = {'case_id': court_sib.text}
                    cases[cur_sno].setdefault('caseno', []).append(case_id)
                    # Add to queue cases[cur_sno]
                    worker_queue.put(case_id)
                    case_id_processed = True

    def convertToCauseListDocx(self, adv_codes):
        date = self.get_dates()
        causelist = self.get_causelist(date, adv_codes)
        context = { 'causelist': causelist, 'date': date }
        tpl=DocxTemplate('causelist_tmpl.docx')
        tpl.render(context)
        tpl.save(date + '.docx')

parser = argparse.ArgumentParser(description='List of advocate codes')
parser.add_argument('integers', metavar='N', type=int, nargs='+',
                    help='List of advocate codes')
args = parser.parse_args()

fetchList = FetchList(NUMBER_OF_WORKERS)
fetchList.convertToCauseListDocx(args.integers)
