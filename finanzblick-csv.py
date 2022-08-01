#!/usr/bin/env python3

#%%
import os
import json
import datetime
import re
import io
import csv
import urllib.parse as up
import requests as rq
import pathlib
from tqdm import tqdm


CONFIG_FILE = os.path.join(
    os.environ["HOME"],
    ".finanzblick-csv.conf.json"
)

if not os.path.isfile(CONFIG_FILE):
    # TODO: query login data and accounts...
    pass

def save_config(conf):
    with open(CONFIG_FILE, "w") as f:
        json.dump(conf, f)

def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)

conf = load_config()


#%%
from seleniumwire import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import ElementClickInterceptedException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from pyshadow.main import Shadow
from webdriver_manager.chrome import ChromeDriverManager


def get_dl_menu(shadow):
  return shadow.find_element('div.sectionList__toolbar > button')

#%%

driver = webdriver.Chrome(ChromeDriverManager().install())
shadow = Shadow(driver)
shadow.set_implicit_wait(10)


#%% login
def login():
    driver.get("https://www.buhl.de/mein-buhlkonto/?buhlparam=1040101")

    def accept_cookies():
        try:
            shadow.find_element('button[aria-label="Zustimmen"]').click()
        except:
            # already accepted, hopefully
            pass
    
    #driver.fullscreen_window()
    element = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.ID, 'form-login-submit'))
    )

    field_email = driver.find_element_by_id('eml-user-login')
    field_password = driver.find_element_by_id('psw-user-login')
    field_email.clear()
    field_email.send_keys(conf['fb_username'])
    field_password.clear()
    field_password.send_keys(conf['fb_password'])

    def click_login():
        driver.find_element_by_id('form-login-submit').click()
    
    try:
        click_login()
    except:
        accept_cookies()
        click_login()

    WebDriverWait(driver, 60).until(
        EC.presence_of_element_located((By.CLASS_NAME, 'cardListItem__name'))
    )
login()

#%%

loginRequest = [r for r in driver.requests if 'sessionToken' in r.url][0]

all_tokens = [dict(r.headers) for r in driver.requests]
all_tokens = [h['Authorization'] for h in all_tokens if 'Authorization' in h]

token = all_tokens[-1]
headers = dict(loginRequest.headers)
headers['Authorization'] = token
headers['Accept'] = "application/json, text/plain, */*"
headers['Referer'] = driver.current_url

driver.close()

def get_csv(account_id):
    from datetime import datetime as dt
    end_date = dt.now() + datetime.timedelta(days=1)
    start_date = end_date - datetime.timedelta(days=90)
    fmt = lambda d: d.isoformat() + 'Z'
    url = f'https://finanzblickx.buhl.de/svc/api/v1/bookings/export/csv/{account_id}?StartDate={fmt(start_date)}&EndDate={fmt(end_date)}'


    resp = rq.get(url, headers=headers)
    return resp.content


#%% adapted from my previous fb2ynab conversion script...

def read_fbl(f):
    r = csv.reader(f, delimiter=';')
    header = next(r)
    for line in r:
      d = dict(zip(header, line))
      if d['Buchungstext'] == 'SONSTIGER EINZUG' and d['Empfaenger'] == 'Unbekannt' and d['Verwendungszweck'].startswith('EC '):
        # vorgemerkt
        continue
      yield d

def to_ynab(item):
    date = item['Buchungsdatum']
    if '.' in date:
        date = date.split('.')
        date = '/'.join([date[1], date[0], date[2]])
    payee = item['Empfaenger']

    memo = ' '.join([item[k] for k in ['Verwendungszweck', 'Buchungstext', 'Notiz'] if k in item])
    amt = float('.'.join(item['Betrag'].split(',')))
    inflow = 0 if amt <= 0 else amt
    outflow = 0 if amt >= 0 else -amt
    return dict(Date=date, Payee=payee, Memo=memo, Outflow='%.2f' % outflow, Inflow='%.2f' % inflow)


all_csv = {a['name']: get_csv(a['id']) for a in tqdm(conf['fb_accounts'])}
paypal_transactions = [to_ynab(i) for i in read_fbl(io.StringIO(all_csv[conf['paypal_account_name']].decode('utf8')))]
del all_csv[conf['paypal_account_name']]
paypal_pattern = re.compile(conf['paypal_reference_pattern'])
paypal_by_amt: dict[float, list] = {}
amt_as_key = lambda t: float(t['Inflow']) - float(t['Outflow'])
for t in paypal_transactions:
    k = amt_as_key(t)
    if k not in paypal_by_amt: 
        paypal_by_amt[k] = []
    paypal_by_amt[k].append(t)

def transform_item(d):
    if paypal_pattern.findall(d['Memo']) and amt_as_key(d) in paypal_by_amt:
        # fix for the new, even stupider paypal contactless transactions
        candidates = paypal_by_amt[amt_as_key(d)]
        parse = lambda d: datetime.datetime.strptime(d, '%m/%d/%Y')
        ddate = parse(d['Date'])
        ddiff = lambda c: abs((parse(c['Date']) - ddate).total_seconds())
        best = min(candidates, key=ddiff)
        d['Payee'] = best['Payee']
        
    if (d['Payee'].startswith("PayPal (Europe)") and ", " in d['Memo']):
        ## if it's a paypal payment with the real payee in the memo, flip this around
        m = d['Memo']
        d['Memo'] = ", ".join([d['Payee']] + m.split(', ')[1:])
        d['Payee'] = re.sub(r"^\. ", "", m.split(", ")[0])
    return d

def convert(f, out_fn):
  items = list(read_fbl(f))
  with open(out_fn, 'w') as f:
    w = csv.DictWriter(f, 'Date Payee Memo Outflow Inflow'.split())
    w.writeheader()
    w.writerows(transform_item(to_ynab(i)) for i in items)

for name, data in all_csv.items():
    f = io.StringIO(data.decode('utf8'))
    fn = pathlib.Path(conf['output_directory']).expanduser()
    convert(f, fn / f"{conf['filename_prefix']}{name}.csv" )

# %%
