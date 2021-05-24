#!/usr/bin/env python3

#%%
import os
import json
import datetime
import re
import time

CONFIG_FILE = os.path.join(
    os.environ["HOME"],
    ".finanzblick-csv.conf.json"
)

if not os.path.isfile(CONFIG_FILE):
    # TODO: query login data
    pass

def save_config(conf):
    with open(CONFIG_FILE, "w") as f:
        json.dump(conf, f)

def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)

conf = load_config()

def get_daterange():
    from datetime import datetime as dt
    to = dt.now()
    fr = to - datetime.timedelta(days=90)
    fmt = lambda t: re.sub("(?<=\.)0|^0", "", dt.strftime(t, '%e.%m.%Y'))
    return fmt(fr), fmt(to)

get_daterange()

#%%
from selenium import webdriver
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
driver.get("https://www.buhl.de/mein-buhlkonto/?buhlparam=1040101")
try:
    shadow.find_element('button[aria-label="Zustimmen"]').click()
except:
    # already accepted, hopefully
    pass

element = WebDriverWait(driver, 10).until(
    EC.element_to_be_clickable((By.ID, 'form-login-submit'))
)

field_email = driver.find_element_by_id('eml-user-login')
field_password = driver.find_element_by_id('psw-user-login')
field_email.clear()
field_email.send_keys(conf['fb_username'])
field_password.clear()
field_password.send_keys(conf['fb_password'])


driver.find_element_by_id('form-login-submit').click()

#%%

def handle(acct):
    iban_field = acct.find_element_by_class_name('cardListItem__iban')
    if ' ' in iban_field.text:
        return None  # this is not a single account
    iban = iban_field.text
    name = acct.find_element_by_class_name('cardListItem__name').text

    acct.click()
    dlm = get_dl_menu(shadow)
    dl = shadow.find_element('.icon-ic-csv-download')

    (ActionChains(driver).move_to_element(dlm).pause(.5).click()
    .move_to_element(dl.parent).pause(.5).click()).perform()

    daterange = driver.find_element_by_tag_name('mat-date-range-input')
    dstart = daterange.find_element_by_css_selector('input.mat-start-date')
    dend = daterange.find_element_by_css_selector('input.mat-end-date')

    dfr, dto = get_daterange()
    dstart.send_keys(dfr)
    dend.send_keys(dto)


#%%
for acct in driver.find_elements_by_tag_name('app-card-list-item'):
    handle(acct)
    break

# %%
