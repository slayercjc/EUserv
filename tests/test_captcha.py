import unittest
from captcha_solver import arithmetic_answer
from renewal_core import StopRenewal


class ArithmeticTests(unittest.TestCase):
    def test_complete_simple_expressions(self):
        for raw, expected in [('2 + 3 = ?', '5'), ('8×3=', '24'), ('4-7', '-3'), ('12/3', '4')]:
            self.assertEqual(arithmetic_answer(raw), expected)

    def test_reject_ambiguous_or_executable_input(self):
        for raw in ['12', '1+2+3', '7/2', '2/0', '2?3', '__import__("os")', '1+2junk', '1**2']:
            with self.subTest(raw=raw), self.assertRaises(StopRenewal):
                arithmetic_answer(raw)
