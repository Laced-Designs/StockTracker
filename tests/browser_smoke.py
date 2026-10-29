from playwright.sync_api import sync_playwright
import json
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1512,'height':1200},device_scale_factor=1)
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8000');page.get_by_text('Demo feed connected').wait_for(timeout=20000)
    page.locator('canvas').first.wait_for();page.screenshot(path='/tmp/stocktracker-new-desktop.png',full_page=True)
    page.get_by_role('button',name='Create paper account',exact=True).click()
    page.get_by_role('dialog').get_by_role('button',name='Create paper account',exact=True).click()
    page.get_by_role('button',name='Buy AAPL',exact=True).wait_for()
    page.get_by_role('button',name='Buy AAPL',exact=True).click()
    page.get_by_text('Order queued.',exact=False).wait_for()
    page.get_by_text('filled',exact=True).wait_for(timeout=20000)
    page.get_by_role('button',name='Positions',exact=False).first.click()
    assert page.locator('tbody').inner_text().find('Equity')>=0
    page.get_by_role('button',name='Analytics',exact=True).click()
    page.get_by_text('Shapley feature contributions').wait_for()
    page.get_by_role('button',name='Learn',exact=True).click()
    page.get_by_text('Know what an option represents',exact=True).wait_for()
    page.get_by_role('button',name='Workspace',exact=False).first.click()
    page.get_by_role('button',name='Options',exact=False).first.click()
    page.get_by_text('European cash-settled model',exact=False).wait_for()
    page.get_by_role('button',name='Buy AAPL',exact=True).click()
    page.wait_for_function("Array.from(document.querySelectorAll('td')).filter(td=>td.textContent==='filled').length===2",timeout=20000)
    page.get_by_role('button',name='Equities',exact=True).click()
    page.locator('.order-panel select').first.select_option('limit')
    page.get_by_label('Limit price',exact=True).fill('1')
    page.get_by_role('button',name='Buy AAPL',exact=True).click()
    page.get_by_role('button',name='Cancel',exact=True).wait_for()
    page.get_by_role('button',name='Cancel',exact=True).click()
    page.get_by_text('canceled',exact=True).wait_for()
    page.get_by_role('button',name='Options',exact=False).first.click()

    page.set_viewport_size({'width':390,'height':844});page.screenshot(path='/tmp/stocktracker-new-mobile.png',full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),'Mobile horizontal overflow'
    assert not errors,errors
    print('PASS: desktop chart, create account, next-quote buy fill, positions, analytics, learn, option execution, limit cancellation, mobile width, zero browser errors')
    browser.close()
