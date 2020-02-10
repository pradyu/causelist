import json
import requests
import logging
import base64
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
SEARCH_TYPE_URL = 'http://tshc.gov.in/Hcdbs/searchtype.do'
SEARCH_INPUT_URL = 'http://tshc.gov.in/Hcdbs/searchtypeinput.do'
DATES_URL = 'http://tshc.gov.in/Hcdbs/getdates.jsp?listtype=D'
SEARCH_DATES_URL = 'http://tshc.gov.in/Hcdbs/searchdates.do'
MAIN_INFO_URL = "http://tshc.gov.in/csis/MainInfo.jsp?mtype={}&mno={}&year={}"
CASE_DETAILS_URL = "http://distcourts.tap.nic.in/csis/getCaseDetails.action?searchtype=casenumber&mtype={}&mno={}&myear={}"
CASE_DETAILS_URL_TELANGANA = "http://tshcstatus.nic.in/getMainCaseDetails.action?casenum={}%20{}/{}"
JUDGE2_LABEL = 'CORAM2'
JUDGE1_LABEL = 'CORAM1'
IGNORED_CASE_TYPES = '- -/-', '.', 'WPMP', 'WVMP', 'WAMP', 'CRLPMP', 'IA'
DATA_LABEL = 'data-label'
SKIP_SAME_SERIAL_NO = True


class CaseWorker(Thread):
    def __init__(self, q):
        Thread.__init__(self)
        self.q = q

    def run(self):
        while True:
            case = self.q.get()
            print("case:" + str(case['case_id']))
            case_id = case['case_id']
            case_type = case_id.split('/')[0]
            case_no = case_id.split('/')[1]
            case_year = case_id.split('/')[2]
            try:
                pet, resp = CaseDetails().getCaseDetails(case_type, case_no, case_year)
                case['petitioner'] = escape(pet)
                case['respondent'] = escape(resp)
            except:
                print("Could not find case details for:" + str(case_id) + " with old endpoint, trying new one.")
                try:
                    pet, resp = CaseDetails().getCaseDetailsV2(case_type, case_no, case_year)
                    case['petitioner'] = escape(pet)
                    case['respondent'] = escape(resp)
                except:
                    print("Could not get case info in newer version as well.")
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
        print("Petitioner:" + petitioner.text)
        print("respondent:" + respondent.text)
        return petitioner.text,respondent.text

    def getCaseDetailsV2(self, case_type, case_no, year):
        res = requests.get(CASE_DETAILS_URL_TELANGANA.format(case_type, case_no, year))
        decoded_resp = base64.b64decode(res.text)
        json_resp = json.loads(decoded_resp)
        petitioner = str(json_resp[0]['petitioner'])
        respondent = str(json_resp[0]['respondent'])
        print("New endpoint: Petitioner:" + petitioner + ", respondent:" + respondent + " ,case number" + case_type + case_no)
        return petitioner,respondent


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
        print(r2.cookies)
        court = {}
        for adv_code in adv_codes:
            r3 = s.post(SEARCH_TYPE_URL, data={'advcd': adv_code})
            soup = BeautifulSoup(r3.text, 'html.parser')
            courts_data = soup.find_all('thead')
            causelist = []
            # Set up some threads to fetch the enclosures

            for court_data in courts_data:
                print('--------')
                #print court_data.text
                court_number = court_data.select("tr:nth-of-type(1)")[0].text
                court_number = int(court_number.split('COURT NO.').pop().strip())
                court.setdefault(court_number, {})
                cj1 = court_data.select("tr:nth-of-type(2)")[0].text
                court[court_number]['cj1'] = escape(cj1.split('JUSTICE').pop().strip())
                cj2 = court_data.select("tr:nth-of-type(3)")[0].text
                court[court_number]['cj2'] = escape(cj2.split('JUSTICE').pop().strip())
                cases = {}
                cur_stage = court_data.next_sibling.next_sibling.text.strip()
                print(cur_stage)
                self.get_cases_by_court(cases, court_data, cur_stage, self.worker_queue, adv_code)
                court[court_number].setdefault('cases', {})
                court[court_number]['cases'].update(cases)
                self.worker_queue.join()
        return court

    def get_cases_by_court(self, cases, court_data, cur_stage, worker_queue, adv_code):
        stage = court_data.next_sibling.next_sibling
        cur_stage = stage.text.strip()
        print(cur_stage)
        for court_sib in stage.find_all_next('tr'):
            find_tds = court_sib.find("td")
            find_ths = court_sib.find("th")
            if find_tds and find_tds.has_key(DATA_LABEL):
                cases_list = court_sib.find("td", attrs={'data-label' : 'Case Det'}).text.strip().split()
                cur_sno = int(court_sib.find("td", attrs={'data-label' : 'S.No'}).text.strip())
                self.resolve_case_entry(adv_code, cases, cases_list, cur_sno, cur_stage, worker_queue)
            elif find_ths and find_ths.text.strip().startswith('COURT NO.'):
                break
            elif find_tds:
                #This is case where for the last court the data-labels are not present. We try to infer based on the position of the records
                pos_text = find_tds.text
                try:
                    cur_sno = int(pos_text)
                    cases_list = court_sib.select("td:nth-of-type(2)")[0].text.strip().split()
                    self.resolve_case_entry(adv_code, cases, cases_list, cur_sno, cur_stage, worker_queue)
                except ValueError:
                    print("Unknown field value, Skipping")
            else:
                cur_stage = court_sib.text.strip()
                print("updating current stage:" + court_sib.text.strip())
            #Need to write boundary condition for breaking out of the look

            print(court_sib)

    def resolve_case_entry(self, adv_code, cases, cases_list, cur_sno, cur_stage, worker_queue):
        case_id = {'case_id': str(cases_list[0])}
        cases[cur_sno] = {"stage": escape(cur_stage), 'adv_code': adv_code}
        cases[cur_sno].setdefault('caseno', []).append(case_id)
        worker_queue.put(case_id)

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
