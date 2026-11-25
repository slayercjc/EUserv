import unittest
import os
from playwright.sync_api import sync_playwright
from renewal_core import StopRenewal
from renew import offer_container, contract_row, control, expiry, login_controls


class PageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel=os.environ.get('TEST_BROWSER_CHANNEL'))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.page = self.browser.new_page()

    def tearDown(self):
        self.page.close()

    def test_legacy_form_controls_outside_form(self):
        self.page.set_content('''<table><form name="step1_anmeldung"><tr>
        <td><input name="email" type="text"></td>
        <td><input name="password" type="password"></td>
        <td><input name="Submit" type="submit" value="Login"></td>
        </tr></form></table>''')
        self.assertEqual(self.page.locator('form input').count(), 0)
        account, password, button = login_controls(self.page)
        account.fill('test-account')
        password.fill('test-password')
        self.assertEqual(account.input_value(), 'test-account')
        self.assertEqual(button.count(), 1)

    def test_free_offer_isolated_from_paid_options(self):
        self.page.set_content('''<div><h3>Keep existing contract</h3>
        <div><input type="radio" name="offer" checked><b>vServer VS2-free v2.1</b>
        <p>One-time extension fee: 0.00 EUR<br>per month: 0.00 EUR</p><button>Extend</button></div>
        <div><input type="radio" name="offer"><b>vServer VS2-cloud</b>
        <p>One-time extension fee: 0.00 EUR<br>per year: 10.08 EUR</p><button>Extend</button></div></div>''')
        offer = offer_container(self.page)
        self.assertEqual(control(offer, 'Extend').count(), 1)
        self.assertNotIn('10.08', offer.inner_text())
        self.page.locator('input').last.check()
        with self.assertRaises(StopRenewal):
            offer_container(self.page)

    def test_exact_contract_and_expiry(self):
        self.page.set_content('''<table><tr><td>123</td><td><a href="#">Extend contract</a></td></tr>
        <tr><td>1234</td><td><a href="#">Extend contract</a></td></tr></table>
        <table><tr><td>Contract end:</td><td>2026-12-24</td></tr></table>''')
        self.assertEqual(control(contract_row(self.page, '123'), 'Extend contract').count(), 1)
        self.assertEqual(str(expiry(self.page)), '2026-12-24')
        with self.assertRaises(StopRenewal):
            contract_row(self.page, '999')

    def test_hidden_duplicate_and_script_in_visible_cell(self):
        self.page.set_content('''<div style="display:none"><table><tr><td>123</td></tr></table></div>
        <table><tr><td><table><tr><td>123<script>void 0;</script></td>
        <td><button>Extend contract</button></td></tr>
        <tr><td>1234</td></tr></table></td></tr></table>''')
        self.assertEqual(control(contract_row(self.page, '123'), 'Extend contract').count(), 1)
