import unittest
from captcha_solver import arithmetic_answer, captcha_answer
from renewal_core import StopRenewal


class ArithmeticTests(unittest.TestCase):
    def test_six_character_challenge_preserves_case(self):
        self.assertEqual(captcha_answer('AbX2yK'), 'AbX2yK')
        self.assertEqual(captcha_answer('123456'), '123456')
        for invalid in ['abc', 'abcdefgh', 'abc?ef', 'ab cdE']:
            with self.assertRaises(StopRenewal):
                captcha_answer(invalid)

    def test_complete_simple_expressions(self):
        for raw, expected in [('2 + 3 = ?', '5'), ('8×3=', '24'), ('4-7', '-3'), ('12/3', '4')]:
            self.assertEqual(arithmetic_answer(raw), expected)

    def test_reject_ambiguous_or_executable_input(self):
        for raw in ['12', '1+2+3', '7/2', '2/0', '2?3', '__import__("os")', '1+2junk', '1**2']:
            with self.subTest(raw=raw), self.assertRaises(StopRenewal):
                arithmetic_answer(raw)
