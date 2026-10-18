"""EcoInvest Pro — point d'entrée Streamlit.

Lancement :  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

from ecoinvest import theme
from ecoinvest.config import APP_ICON, APP_NAME, APP_TAGLINE, VERSION


def _sidebar() -> None:
    """Compléments de barre latérale (après la navigation)."""
    from ecoinvest.ui import components as ui
    from ecoinvest.ui.pages import shared

    st.sidebar.divider()

    st.sidebar.markdown("#### 🌍 Marché")
    try:
        indices = shared.indices()
        masi = indices[indices["code"] == "MASI"]
        if not masi.empty:
            row = masi.iloc[0]
            change = row.get("change_pct")
            tone = "ei-up" if (change or 0) >= 0 else "ei-down"
            arrow = "▲" if (change or 0) >= 0 else "▼"
            st.sidebar.markdown(
                f"""
                <div class="ei-card" style="padding:12px 14px">
                  <div class="ei-kpi-label">MASI</div>
                  <div style="font-size:1.35rem;font-weight:800">{row['value']:,.2f}</div>
                  <span class="ei-badge {tone}">{arrow} {change * 100:+.2f} %</span>
                  <div class="ei-kpi-sub" style="margin-top:.35rem">
                    YTD {row['ytd_pct'] * 100:+.2f} %
                  </div>
                </div>
                """.replace(",", "\u202f"),
                unsafe_allow_html=True,
            )
        masi20 = indices[indices["code"] == "MSI20"]
        if not masi20.empty:
            row = masi20.iloc[0]
            st.sidebar.caption(
                f"MASI 20 : {row['value']:,.2f} ({row['change_pct'] * 100:+.2f} %)"
            )
    except Exception:
        st.sidebar.caption("Indices momentanément indisponibles.")

    st.sidebar.divider()
    st.sidebar.markdown("#### 👤 Mon profil")
    try:
        profile = shared.get_profile()
        itype = profile.investor_type()
        st.sidebar.markdown(
            f"{ui.badge(itype['label'], 'info')}",
            unsafe_allow_html=True,
        )
        st.sidebar.caption(
            f"Revenu {profile.monthly_income:,.0f} MAD · épargne "
            f"{profile.savings_capacity:,.0f} MAD/mois".replace(",", "\u202f")
        )
    except Exception:
        st.sidebar.caption("Profil non disponible.")

    st.sidebar.divider()
    if st.sidebar.button("🔄 Rafraîchir les données", use_container_width=True,
                         help="Purge les caches et recharge BVC, Yahoo Finance et les actualités."):
        shared.clear_caches()
        st.rerun()

    watch = []
    try:
        watch = shared.watchlist()
    except Exception:
        pass
    if watch:
        st.sidebar.caption("⭐ Liste de suivi : " + ", ".join(watch[:8]) + ("…" if len(watch) > 8 else ""))

    st.sidebar.divider()
    st.sidebar.caption(
        "Sources : Bourse de Casablanca (API publique), Yahoo Finance, flux RSS publics. "
        "Fondamentaux saisis par l'utilisateur."
    )
    st.sidebar.caption(f"{APP_NAME} · v{VERSION}")


def main() -> None:
    theme.setup_page(f"{APP_NAME} — Analyse & simulation", APP_ICON)

    # Import après set_page_config : les pages enregistrent des décorateurs Streamlit.
    from ecoinvest.ui.pages import (
        ai_page,
        company,
        dashboard,
        fundamentals_page,
        news_page,
        portfolio_builder,
        profile_page,
        projects,
        screener,
        simulator,
        valuation,
    )

    entries = [
        ("dashboard", "Tableau de bord", "🏠", dashboard.render, "dashboard"),
        ("screener", "Screener BVC", "🔍", screener.render, "screener"),
        ("company", "Analyse société", "🏢", company.render, "company"),
        ("news_page", "Actualités & sentiment", "📰", news_page.render, "news"),
        ("valuation", "Valorisation DCF", "🧮", valuation.render, "valuation"),
        ("fundamentals_page", "Données fondamentales", "📊", fundamentals_page.render, "fundamentals"),
        ("profile_page", "Mon profil", "👤", profile_page.render, "profile"),
        ("simulator", "Simulateur", "📈", simulator.render, "simulator"),
        ("portfolio_builder", "Portefeuille & arbitrage", "💼", portfolio_builder.render, "portfolio"),
        ("ai_page", "Agent IA", "🤖", ai_page.render, "agent"),
        ("projects", "Projets VAN / TRI", "🌿", projects.render, "projects"),
    ]

    pages = {}
    for key, title, icon, fn, path in entries:
        pages[key] = st.Page(
            fn,
            title=title,
            icon=icon,
            url_path=path,
            default=(key == "dashboard"),
        )
    st.session_state["_nav_pages"] = pages

    nav = st.navigation(
        {
            "Marché": [pages["dashboard"], pages["screener"], pages["company"], pages["news_page"]],
            "Analyse": [pages["valuation"], pages["fundamentals_page"]],
            "Patrimoine": [pages["profile_page"], pages["simulator"], pages["portfolio_builder"]],
            "Intelligence": [pages["ai_page"]],
            "Outils": [pages["projects"]],
        },
        position="sidebar",
    )

    _sidebar()
    nav.run()


if __name__ == "__main__":
    main()
