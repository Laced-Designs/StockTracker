"""Demo-only browser acceptance for personalized navigation. Run against localhost:8000."""
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1512,'height':1100})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8000');page.get_by_text('Demo feed connected').wait_for(timeout=20000)
    page.get_by_role('button',name='Favorite TSLA',exact=True).click()
    page.get_by_role('button',name='Favorites',exact=True).click()
    assert page.locator('.tracker-card').filter(has_text='TSLA').count()==1
    page.reload();page.get_by_text('Your personal watchlist',exact=True).wait_for()
    assert page.locator('.tracker-card').filter(has_text='TSLA').count()==1
    page.get_by_role('button',name='News',exact=True).click()
    page.locator('.feed-article').first.wait_for()
    page.get_by_role('button',name='My favorites',exact=True).click()
    page.get_by_label('News topic',exact=True).select_option('macro')
    assert page.locator('.feed-article').count()==4
    page.get_by_role('button',name='Create paper account',exact=True).click()
    page.get_by_role('dialog').get_by_role('button',name='Create paper account',exact=True).click()
    page.get_by_role('button',name='Goals',exact=True).click()
    page.get_by_role('button',name='Set a goal',exact=True).click()
    page.get_by_label('Goal name',exact=True).fill('My first practice milestone')
    page.get_by_label('Target token balance',exact=True).fill('9000')
    assert not page.get_by_label('Target token balance',exact=True).evaluate('(el)=>el.checkValidity()')
    page.get_by_label('Target token balance',exact=True).fill('11000')
    page.get_by_role('button',name='Save practice goal',exact=True).click()
    page.get_by_text('My first practice milestone',exact=True).wait_for()
    assert page.locator('.achievement.unlocked').count()==1
    page.reload();page.get_by_text('My first practice milestone',exact=True).wait_for()
    page.get_by_role('button',name='Trade',exact=True).click()
    page.get_by_role('button',name='Buy AAPL',exact=True).click()
    page.get_by_role('button',name='Confirm simulated order',exact=True).click()
    page.get_by_text('filled',exact=True).wait_for(timeout=20000)
    page.get_by_role('button',name='Goals',exact=True).click()
    assert page.locator('.achievement.unlocked').count()==2
    page.get_by_role('button',name='Learn',exact=True).click()
    page.get_by_role('button',name='Goals',exact=True).click()
    assert page.locator('.achievement.unlocked').count()==3
    page.get_by_role('button',name='Market',exact=True).click()
    page.screenshot(path='/tmp/stocktracker-personal-desktop.png',full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    page.get_by_role('button',name='Toggle navigation menu',exact=True).click()
    page.get_by_role('button',name='Favorites',exact=True).click()
    assert page.get_by_text('Your personal watchlist',exact=True).is_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.screenshot(path='/tmp/stocktracker-personal-mobile.png',full_page=True)
    page.get_by_role('button',name='Toggle navigation menu',exact=True).click()
    page.get_by_role('button',name='Goals',exact=True).click()
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    assert not errors,errors
    print('PASS: favorite persistence, filtered news, account goal persistence, ledger milestones, trade confirmation/fill, learning milestone, mobile navigation and layout')
    browser.close()
