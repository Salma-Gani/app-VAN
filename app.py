"""MARKET MIND — point d'entrée Streamlit.

Lancement :  python3 -m streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

from ecoinvest import theme
from ecoinvest.config import APP_ICON, APP_NAME, VERSION


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
                  <div style="font-size:1.35rem;font-weight:700">{row['value']:,.2f}</div>
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
        st.sidebar.caption(f"Horizon {profile.horizon_years} ans · données stockées localement")
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
        "Cours différés. Fondamentaux hors titres/dividende saisis par l'utilisateur."
    )
    st.sidebar.caption(f"{APP_NAME} · v{VERSION}")


def main() -> None:
    theme.setup_page(f"{APP_NAME} — Investment intelligence", APP_ICON)

    # Import après set_page_config : les pages enregistrent des décorateurs Streamlit.
    from ecoinvest.ui.pages import (
        ai_page,
        alerts_page,
        company,
        dashboard,
        fundamentals_page,
        home,
        news_page,
        portfolio_builder,
        profile_page,
        projects,
        screener,
        simulator,
        sources_page,
        valuation,
    )

    entries = [
        ("home", "Accueil", "🧭", home.render, "accueil"),
        ("dashboard", "Vue globale du marché", "📊", dashboard.render, "marche"),
        ("screener", "Screener & technique", "🔍", screener.render, "screener"),
        ("company", "Analyse société", "🏢", company.render, "societe"),
        ("news_page", "Actualités & sentiment", "📰", news_page.render, "actualites"),
        ("valuation", "Valorisation & cash-flows", "🧮", valuation.render, "valorisation"),
        ("fundamentals_page", "Données fondamentales", "🧾", fundamentals_page.render, "fondamentaux"),
        ("profile_page", "Mon patrimoine", "👤", profile_page.render, "patrimoine"),
        ("simulator", "Simulateur", "📈", simulator.render, "simulateur"),
        ("portfolio_builder", "Portefeuille & alternatives", "💼", portfolio_builder.render, "portefeuille"),
        ("ai_page", "Market Mind AI", "🧠", ai_page.render, "intelligence"),
        ("alerts_page", "Alertes & surveillance", "🔔", alerts_page.render, "alertes"),
        ("projects", "Comparateur de projets", "🌿", projects.render, "projets"),
        ("sources_page", "Sources & méthodologie", "📚", sources_page.render, "sources"),
    ]

    pages = {}
    for key, title, icon, fn, path in entries:
        kwargs = dict(title=title, icon=icon, default=(key == "home"))
        if key != "home":
            kwargs["url_path"] = path
        pages[key] = st.Page(fn, **kwargs)
    st.session_state["_nav_pages"] = pages

    try:
        st.logo("assets/market_mind_logo.svg", size="large")
    except Exception:
        pass

    nav = st.navigation(
        {
            "Pilotage": [pages["home"], pages["dashboard"]],
            "Marchés": [pages["screener"], pages["company"], pages["news_page"]],
            "Analyse": [pages["valuation"], pages["fundamentals_page"]],
            "Patrimoine": [pages["profile_page"], pages["simulator"], pages["portfolio_builder"]],
            "Intelligence": [pages["ai_page"], pages["alerts_page"]],
            "Outils": [pages["projects"], pages["sources_page"]],
        },
        position="sidebar",
    )

    _sidebar()
    nav.run()


if __name__ == "__main__":
    main()
