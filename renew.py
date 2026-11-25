"""EUserv free-contract renewal using one continuous browser session."""
import os
import re
import sys
import time
from datetime import date, datetime

from renewal_core import Mailbox, StopRenewal, report, require_free_offer

URL = 'https://support.euserv.com/index.iphp'


def required(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise StopRenewal(f'缺少 GitHub Secret：{name}')
    return value


def unique(locator, description):
    if locator.count() != 1:
        raise StopRenewal(f'无法唯一识别{description}，页面可能发生变化。')
    return locator


def control(scope, name):
    # EUserv uses a mix of links, buttons and input[type=submit].
    return scope.get_by_role('button', name=name, exact=True).or_(
        scope.get_by_role('link', name=name, exact=True)).filter(visible=True)


def login_controls(page):
    # Legacy table markup leaves the actual inputs outside the form element.
    return (
        unique(page.locator('input[name="email"]:visible'), '可见登录账号输入框'),
        unique(page.locator('input[name="password"][type="password"]:visible'), '可见登录密码输入框'),
        unique(page.locator('input[name="Submit"][type="submit"]:visible'), '可见登录按钮'),
    )


def contract_row(page, contract):
    # Older layout tables may not expose ARIA cell/row roles.
    cell = page.locator('td').filter(has_text=re.compile(r'^\s*' + re.escape(contract) + r'\s*$'))
    row = cell.locator('xpath=ancestor::tr[1]').filter(visible=True)
    server_tab = page.get_by_text('vServer', exact=True).filter(visible=True)
    if row.count() == 0 and server_tab.count() == 1:
        server_tab.click()
    from playwright.sync_api import TimeoutError as BrowserTimeout
    try:
        row.first.wait_for(state='visible', timeout=15000)
    except BrowserTimeout:
        report('合同定位诊断：可见表格行数=' + str(page.locator('tr:visible').count())
               + '，匹配合同单元格数=' + str(cell.count())
               + '，精确合同文本数=' + str(page.get_by_text(contract, exact=True).count()))
    return unique(row, '指定合同列表行')


def offer_container(page):
    # Choose the nearest container holding exactly one radio and the free offer.
    # Do not select the entire modal, which also contains paid upgrades.
    radio = page.locator('input[type=radio]:visible')
    matches = []
    for item in radio.all():
        container = item.locator('xpath=ancestor::*[.//*[contains(text(), "One-time extension fee")]][1]')
        if container.count() == 1 and container.locator('input[type=radio]').count() == 1:
            if re.search(r'vServer\s+VS2-free\s+v2\.1\b', container.inner_text(), re.I):
                matches.append((item, container))
    if len(matches) != 1:
        raise StopRenewal('无法唯一识别免费原套餐区域。')
    radio, container = matches[0]
    require_free_offer(container.inner_text())
    if not radio.is_checked():
        raise StopRenewal('免费原套餐并非默认选中，停止续期。')
    return container


def parse_date(text):
    for pattern, fmt in ((r'\b\d{4}-\d{2}-\d{2}\b', '%Y-%m-%d'),
                         (r'\b\d{2}\.\d{2}\.\d{4}\b', '%d.%m.%Y')):
        match = re.search(pattern, text)
        if match:
            return datetime.strptime(match[0], fmt).date()
    raise StopRenewal('无法读取合同日期。')


def expiry(page):
    labels = re.compile(r'^(?:Contract end|Contract end date|End of contract|Contract expires|Contract expiration|Current contract end)\s*:?$', re.I)
    cells = page.get_by_role('cell').filter(has_text=labels).filter(visible=True)
    cell = unique(cells, '合同结束日期字段')
    row = cell.locator('xpath=ancestor::tr[1]')
    return parse_date(row.inner_text())


def run():
    from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout

    username = required('EUSERV_USERNAME')
    password = required('EUSERV_PASSWORD')
    contract = required('EUSERV_CONTRACT_ID')
    if not contract.isdigit():
        raise StopRenewal('合同号必须是数字。')
    dry_run = os.environ.get('DRY_RUN', 'true').lower() == 'true'
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(locale='en-US')
            page.set_default_timeout(30000)
            report('阶段：打开 EUserv 登录页。')
            page.goto(URL, wait_until='domcontentloaded')
            report('阶段：登录页已加载，识别登录表单。')
            form = page.locator('form[name="step1_anmeldung"]')
            unique(form, '登录表单')
            language = page.locator('select[name="form_selected_language"]:visible')
            if language.count() and language.input_value() != 'en':
                report('阶段：切换登录页面语言为英语。')
                with page.expect_navigation(wait_until='domcontentloaded'):
                    language.select_option(value='en')
            report('阶段：填写登录账号。')
            account_input, password_input, login_button = login_controls(page)
            account_input.fill(username)
            report('阶段：填写登录密码。')
            password_input.fill(password)
            report('阶段：提交登录表单。')
            login_button.click()
            report('阶段：等待登录结果。')
            try:
                control(page, 'Contracts').wait_for(state='visible')
            except BrowserTimeout:
                body = page.locator('body').inner_text()
                if re.search(r'finish the login process.*captcha|solve the following captcha', body, re.I | re.S):
                    from captcha_solver import solve_login_captcha
                    solve_login_captcha(page)
                    try:
                        control(page, 'Contracts').wait_for(state='visible')
                    except BrowserTimeout:
                        raise StopRenewal('一次图形验证码识别未完成登录；本次不再重试，未执行续期。') from None
                    report('阶段：图形验证码通过，已登录。')
                if re.search(r'authenticator app|two.factor|two.step', body, re.I):
                    raise StopRenewal('EUserv 登录要求身份验证器二次验证；这不是续期邮件 PIN，当前未配置。') from None
                if re.search(r'incorrect|invalid password|login failed|wrong password', body, re.I):
                    raise StopRenewal('网站返回登录错误，请检查 EUserv 用户名和密码 Secret。') from None
                if not control(page, 'Contracts').is_visible():
                    raise StopRenewal('登录未完成：请检查凭据，或网站是否要求额外登录验证。') from None
            unique(control(page, 'Contracts'), 'Contracts 入口').click()
            report('阶段：查找指定合同。')
            row = contract_row(page, contract)
            extend = control(row, 'Extend contract')
            if extend.count() == 0:
                # A missing button alone must never be treated as success.
                text = row.inner_text() + '\n' + row.evaluate('''element =>
                    Array.from(element.querySelectorAll('*')).flatMap(node =>
                    ['title','data-bs-original-title','data-original-title','data-bs-content','data-content']
                    .map(name => node.getAttribute(name) || '')).join('\\n')''')
                if 'Contract extension possible from' in text and parse_date(text.split('Contract extension possible from', 1)[1]) > date.today():
                    report('尚未到可续期日期：' + str(parse_date(text.split('Contract extension possible from', 1)[1])) + '，本次无需续期。')
                    return
                report('合同状态诊断：日期=' + ','.join(re.findall(r'\b\d{4}-\d{2}-\d{2}\b|\b\d{2}\.\d{2}\.\d{4}\b', text))
                       + '，按钮数=' + str(row.locator('button,input[type=submit],a').count()))
                raise StopRenewal('指定合同没有续期按钮，也无法确认未来可续期日期；需要检查页面。')
            unique(extend, '续期入口').click()
            report('阶段：检查保留原套餐弹窗。')
            page.get_by_text('Keep existing contract', exact=True).wait_for(state='visible')
            offer = offer_container(page)
            # Read current actual contract end; the modal only shows a proposed new date.
            before = expiry(page)
            if dry_run:
                report(f'检查通过：找到指定免费原套餐，当前合同结束日期 {before}。未请求 PIN、未提交续期。')
                return
            sender = required('EUSERV_PIN_SENDER')
            if not re.fullmatch(r'[^\s@]+@[^\s@]+', sender):
                raise StopRenewal('EUSERV_PIN_SENDER 必须是 PIN 邮件的完整发件地址。')
            with Mailbox(required('GMAIL_ADDRESS'), required('GMAIL_APP_PASSWORD'), sender) as mail:
                checkpoint = mail.checkpoint()
                requested_at = time.time()
                require_free_offer(offer.inner_text())
                unique(control(offer, 'Extend'), '免费套餐 Extend 按钮').click()
                pin_input = page.get_by_placeholder('Enter PIN', exact=True)
                pin_input.wait_for(state='visible')
                pin = mail.wait_pin(checkpoint, requested_at)
                pin_input.fill(pin)
                unique(control(page, 'Continue'), 'PIN 提交按钮').click()
                pin_input.wait_for(state='hidden')
            # Never resubmit automatically after an uncertain result.
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                page.wait_for_timeout(5000)
                page.reload(wait_until='domcontentloaded')
                after = expiry(page)
                if after > before:
                    report(f'免费续期已确认：合同结束日期由 {before} 更新为 {after}。')
                    return
            raise StopRenewal('PIN 已提交，但未确认到期日更新。请先人工检查合同，勿立即重复提交。')
        finally:
            browser.close()


if __name__ == '__main__':
    try:
        run()
    except StopRenewal as exc:
        report('失败：' + str(exc))
        sys.exit(1)
    except Exception as exc:
        # Browser/IMAP exceptions can include page contents, credentials or PINs.
        report(f'失败：{type(exc).__name__}。连接或页面结构异常；未确认续期成功。')
        sys.exit(1)
