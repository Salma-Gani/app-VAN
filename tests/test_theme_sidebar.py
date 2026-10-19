"""La navigation principale doit rester ancrée dans la barre latérale.

Régression : Streamlit mémorise l'état « replié » dans le navigateur ; même
avec ``initial_sidebar_state="expanded"``, la barre pouvait rester masquée et
l'utilisateur devait utiliser le bouton retour pour changer de rubrique.
"""
from __future__ import annotations

import inspect
import unittest

from ecoinvest import theme


class TestSidebarAlwaysVisible(unittest.TestCase):
    def test_initial_state_is_expanded(self) -> None:
        source = inspect.getsource(theme.setup_page)
        self.assertIn('initial_sidebar_state="expanded"', source)

    def test_css_neutralises_the_collapsed_state(self) -> None:
        css = inspect.getsource(theme.inject_css)
        self.assertIn('[aria-expanded="false"]', css)
        self.assertIn("transform: none !important", css)
        self.assertIn('min-width: 18rem !important', css)

    def test_collapse_controls_are_hidden(self) -> None:
        css = inspect.getsource(theme.inject_css)
        self.assertIn('[data-testid="stSidebarCollapseButton"]', css)
        self.assertIn('[data-testid="stSidebarCollapsedControl"]', css)
        self.assertIn("display: none !important", css)


if __name__ == "__main__":
    unittest.main()
