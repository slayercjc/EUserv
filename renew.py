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


def contract_row(page, contract):
    cell = page.get_by_role('cell', name=contract, exact=True)
    row = page.get_by_role('row').filter(has=cell).filter(visible=True)
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
            page.goto(URL, wait_until='domcontentloaded')
            form = page.locator('form[name="step1_anmeldung"]')
            unique(form, '登录表单')
            language = form.locator('select[name="form_selected_language"]')
            if language.count() and language.input_value() != 'en':
                with page.expect_navigation(wait_until='domcontentloaded'):
                    language.select_option(value='en')
            form.locator('input[name="email"]').fill(username)
            form.locator('input[name="password"]').fill(password)
            form.locator('input[type="submit"]').click()
            try:
                control(page, 'Contracts').wait_for(state='visible')
            except BrowserTimeout:
                raise StopRenewal('登录未完成：请检查凭据，或网站是否要求图形验证码/额外登录验证。') from None
            unique(control(page, 'Contracts'), 'Contracts 入口').click()
            row = contract_row(page, contract)
            extend = control(row, 'Extend contract')
            if extend.count() == 0:
                # A missing button alone must never be treated as success.
                text = row.inner_text()
                if 'Contract extension possible from' in text and parse_date(text.split('Contract extension possible from', 1)[1]) > date.today():
                    report('尚未到可续期日期，本次无需续期。')
                    return
                raise StopRenewal('指定合同没有续期按钮，也无法确认未来可续期日期；需要检查页面。')
            unique(extend, '续期入口').click()
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
