from __future__ import annotations

import unittest

from ecoinvest.ai import prompts
from ecoinvest.portfolio.profile import InvestorProfile
from ecoinvest.utils.formatting import fmt_money


class TestPromptPrivacy(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = InvestorProfile(
            salary_monthly=123456.0,
            monthly_expenses=23456.0,
            cash=987654.0,
            target_capital=7654321.0,
        )

    def test_amounts_are_redacted_by_default(self) -> None:
        context = prompts.portfolio_context(self.profile, None, None, share_amounts=False)
        self.assertIn("confidentiel", context)
        self.assertNotIn(fmt_money(self.profile.monthly_income), context)
        self.assertNotIn(fmt_money(self.profile.cash, compact=True), context)
        self.assertNotIn(fmt_money(self.profile.target_capital, compact=True), context)

    def test_amounts_are_included_only_with_explicit_consent(self) -> None:
        context = prompts.portfolio_context(self.profile, None, None, share_amounts=True)
        self.assertNotIn("Revenu et charges : **non transmis", context)
        self.assertIn(fmt_money(self.profile.monthly_income), context)
        self.assertIn(fmt_money(self.profile.target_capital, compact=True), context)


if __name__ == "__main__":
    unittest.main()
