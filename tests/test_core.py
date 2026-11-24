import unittest
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from unittest.mock import Mock, patch

from renewal_core import Mailbox, StopRenewal, extract_pin, require_free_offer

FREE = 'vServer VS2-free v2.1 One-time extension fee: 0.00 EUR per month: 0.00 EUR'
NOW = datetime(2026, 11, 24, 4, 0, tzinfo=timezone.utc)


def message(body='PIN:\n123456', sender='support@example.test', sent=NOW, html=False):
    msg = EmailMessage()
    msg['From'] = sender
    msg['Date'] = format_datetime(sent)
    msg.set_content('you have just requested a PIN for confirmation of a security check at EUserv.\n' + body,
                    subtype='html' if html else 'plain')
    return msg.as_bytes()


class SafetyTests(unittest.TestCase):
    def test_zero_cost_original_offer(self):
        require_free_offer(FREE)

    def test_reject_paid_and_unknown_offers(self):
        for text in (FREE.replace('0.00', '2.00', 1), FREE.replace('VS2-free', 'VS2-cloud'),
                     FREE + ' setup: 1.00 EUR', FREE.replace('per month', 'per year'),
                     FREE.replace('0.00 EUR', '0.00 USD')):
            with self.subTest(text=text), self.assertRaises(StopRenewal):
                require_free_offer(text)

    def test_plain_and_html_pin(self):
        self.assertEqual(extract_pin(message(), 'support@example.test', NOW.timestamp()), '123456')
        self.assertEqual(extract_pin(message('PIN:<br><b>012345</b>', html=True),
                                     'support@example.test', NOW.timestamp()), '012345')

    def test_reject_stale_wrong_sender_ambiguous_pin(self):
        self.assertIsNone(extract_pin(message(), 'different@example.test', NOW.timestamp()))
        self.assertIsNone(extract_pin(message(), 'support@example.test', NOW.timestamp() + 60))
        for body in ('PIN: 1234567', 'PIN: 123456\nPIN: 654321', 'Contract: 123456'):
            self.assertIsNone(extract_pin(message(body), 'support@example.test', NOW.timestamp()))

    def test_imap_range_does_not_reuse_older_uid(self):
        mailbox = Mailbox('a', 'b', 'support@example.test')
        mailbox.client = Mock()
        mailbox.checkpoint = Mock(return_value=(1, 100))
        mailbox.client.uid.return_value = ('OK', [b'99'])
        with patch('renewal_core.time.monotonic', side_effect=[0, 0, 200]), patch('renewal_core.time.sleep'):
            with self.assertRaises(StopRenewal):
                mailbox.wait_pin((1, 100), NOW.timestamp())
        self.assertEqual(mailbox.client.uid.call_count, 1)

    def test_uidvalidity_change_stops(self):
        mailbox = Mailbox('a', 'b', 'support@example.test')
        mailbox.client = Mock()
        mailbox.checkpoint = Mock(return_value=(2, 100))
        with self.assertRaises(StopRenewal):
            mailbox.wait_pin((1, 100), NOW.timestamp())
        mailbox.client.uid.assert_not_called()


if __name__ == '__main__':
    unittest.main()
