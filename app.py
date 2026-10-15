"""Application financière : VAN / TRI / Payback — Comparateur Projet A vs Projet B."""
from typing import Optional
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ───────────────────────── Config & Style ─────────────────────────
st.set_page_config(page_title="EcoInvest · Analyse VAN / TRI", page_icon="🌿", layout="wide")

VERT_FONCE = "#1B5E20"
VERT = "#2E7D32"
VERT_CLAIR = "#E8F5E9"
VERT_ACCENT = "#43A047"
BEIGE = "#FAFDF9"

st.markdown(
    f"""
    <style>
    .stApp {{ background-color: {BEIGE}; }}
    h1, h2, h3 {{ color: {VERT_FONCE} !important; }}
    section[data-testid="stSidebar"] {{ background-color: #EDF5EE; border-right: 2px solid #C8E6C9; }}
    section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3 {{ color: {VERT_FONCE}; }}
    .metric-card {{
        background: white; border-radius: 16px; padding: 18px 20px;
        border: 1px solid #C8E6C9; border-top: 6px solid {VERT};
        box-shadow: 0 4px 14px rgba(27,94,32,0.08); text-align: center;
    }}
    .metric-card .label {{ font-size: 0.85rem; color: #558B5A; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }}
    .metric-card .value {{ font-size: 1.7rem; font-weight: 800; color: {VERT_FONCE}; margin: 4px 0; }}
    .metric-card .sub {{ font-size: 0.8rem; color: #777; }}
    .metric-card.good {{ border-top-color: {VERT_ACCENT}; }}
    .metric-card.bad {{ border-top-color: #C62828; }}
    .metric-card.bad .value {{ color: #C62828; }}
    div.stButton > button {{
        background-color: {VERT}; color: white; border-radius: 12px;
        border: none; font-weight: 700; padding: .6rem 1.4rem;
    }}
    div.stButton > button:hover {{ background-color: {VERT_FONCE}; color: white; }}
    .alert-ok {{ background: {VERT_CLAIR}; border: 1px solid {VERT_ACCENT}; border-radius: 12px; padding: 12px 16px; }}
    .alert-ko {{ background: #FFEBEE; border: 1px solid #C62828; border-radius: 12px; padding: 12px 16px; }}
    .reco {{ background: linear-gradient(135deg, {VERT_FONCE}, {VERT_ACCENT}); color: white;
             border-radius: 16px; padding: 22px 26px; box-shadow: 0 6px 20px rgba(27,94,32,.25); }}
    .reco h3 {{ color: white !important; }}
    header[data-testid="stHeader"] {{ background: {BEIGE}; }}
    </style>
    """,
    unsafe_allow_html=True,
)

# ───────────────────────── Fonctions financières ─────────────────────────
def van(invest: float, cashflows: list[float], taux: float) -> float:
    t = np.arange(1, len(cashflows) + 1)
    cf = np.array(cashflows, dtype=float)
    return float(-invest + np.sum(cf / (1 + taux) ** t))


def tri(invest: float, cashflows: list[float]) -> Optional[float]:
    """TRI par bissection sur [-99% ; +1000%]. Retourne None si introuvable."""
    def npv(r):
        if r <= -1:
            return float("inf")
        t = np.arange(1, len(cashflows) + 1)
        return float(-invest + np.sum(np.array(cashflows) / (1 + r) ** t))

    # Pas de changement de signe -> pas de TRI
    lo, hi = -0.9999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-6:
            return float(mid)
        if f_lo * f_mid <= 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return float((lo + hi) / 2)


def payback(invest: float, cashflows: list[float], taux: Optional[float] = None):
    """Retourne (délai en années, cumulés). taux=None -> payback simple, sinon actualisé."""
    cumul = []
    cum = -invest
    for i, cf in enumerate(cashflows, start=1):
        v = cf if taux is None else cf / (1 + taux) ** i
        prev = cum
        cum += v
        cumul.append(cum)
        if cum >= 0:
            frac = (0 - prev) / v if v != 0 else 0
            return (i - 1 + frac, cumul)
    return (None, cumul)


def flux_actualises(cashflows, taux):
    return [cf / (1 + taux) ** i for i, cf in enumerate(cashflows, start=1)]


def fmt_eur(x: float) -> str:
    return f"{x:,.0f} €".replace(",", " ").replace(".", ",")


def fmt_pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x * 100:.2f} %"


def fmt_payback(p) -> str:
    if p is None:
        return "Jamais"
    a = int(p)
    m = round((p - a) * 12)
    if a == 0:
        return f"{m} mois"
    return f"{a} ans {m} mois ({p:.2f} ans)"


# ───────────────────────── Sidebar : paramètres dynamiques ─────────────────────────
st.sidebar.markdown("## 🌿 Paramètres globaux")
st.sidebar.caption("Ajustez les hypothèses — tous les calculs se mettent à jour.")

taux = st.sidebar.slider("Taux d'actualisation / coût du capital (%)", 0.0, 20.0, 8.0, 0.1) / 100
horizon = st.sidebar.slider("Horizon d'investissement (années)", 1, 15, 5, 1)
budget = st.sidebar.number_input("Budget global alloué maximal (€)", 0, 10_000_000, 100_000, 1_000)
volatilite = st.sidebar.slider("Incertitude / volatilité du marché (%)", 0, 50, 20, 1) / 100

st.sidebar.markdown("---")
st.sidebar.markdown("**Scénarios de sensibilité**")
st.sidebar.write(f"🔴 Pessimiste : cash-flows × {(1 - volatilite):.0%}")
st.sidebar.write("🟢 Base : cash-flows × 100 %")
st.sidebar.write(f"🔵 Optimiste : cash-flows × {(1 + volatilite):.0%}")
st.sidebar.markdown("---")
st.sidebar.caption("🌱 VAN > 0 = projet rentable · TRI > taux = création de valeur")

# ───────────────────────── En-tête ─────────────────────────
st.markdown("# 🌿 EcoInvest — Aide à la décision d'investissement")
st.markdown(
    "**Comparez deux projets :** Valeur Actuelle Nette (VAN), Taux de Rendement Interne (TRI), "
    "délai de récupération (payback) et conformité budgétaire."
)

# ───────────────────────── Saisie projets ─────────────────────────
DEFAULT_A = [30_000, 35_000, 40_000, 40_000, 35_000]
DEFAULT_B = [20_000, 25_000, 35_000, 50_000, 60_000]

colA, colB = st.columns(2)

def bloc_projet(nom, couleur, defaut_inv, defaut_cf):
    with st.container():
        st.markdown(f"### {nom}")
        inv = st.number_input(
            f"Investissement initial — {nom} (€)", 0, 10_000_000, defaut_inv, 1_000, key=f"inv_{nom}"
        )
        cfs = []
        cols = st.columns(min(horizon, 5))
        for i in range(horizon):
            d = defaut_cf[i] if i < len(defaut_cf) else defaut_cf[-1]
            with cols[i % len(cols)]:
                cfs.append(
                    st.number_input(f"Année {i+1}", 0, 10_000_000, int(d), 1_000, key=f"cf_{nom}_{i}")
                )
        return inv, cfs

with colA:
    invA, cfA = bloc_projet("🅰️ Projet A", VERT, 100_000, DEFAULT_A)
with colB:
    invB, cfB = bloc_projet("🅱️ Projet B", VERT_ACCENT, 120_000, DEFAULT_B)

# ───────────────────────── Calculs ─────────────────────────
vanA, vanB = van(invA, cfA, taux), van(invB, cfB, taux)
triA, triB = tri(invA, cfA), tri(invB, cfB)
pb_simpleA, _ = payback(invA, cfA)
pb_simpleB, _ = payback(invB, cfB)
pb_actuA, cumA = payback(invA, cfA, taux)
pb_actuB, cumB = payback(invB, cfB, taux)
ok_budgetA, ok_budgetB = invA <= budget, invB <= budget
depassA, depassB = invA - budget, invB - budget

# Sensibilité scénarios
vanA_pes = van(invA, [c * (1 - volatilite) for c in cfA], taux)
vanA_opt = van(invA, [c * (1 + volatilite) for c in cfA], taux)
vanB_pes = van(invB, [c * (1 - volatilite) for c in cfB], taux)
vanB_opt = van(invB, [c * (1 + volatilite) for c in cfB], taux)

# ───────────────────────── Alertes budgétaires ─────────────────────────
st.markdown("## 🚨 Contrôle budgétaire")
c1, c2 = st.columns(2)
with c1:
    if ok_budgetA:
        st.markdown(f'<div class="alert-ok">✅ <b>Projet A conforme</b> — {fmt_eur(invA)} ≤ budget {fmt_eur(budget)}</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="alert-ko">⚠️ <b>Projet A dépasse le budget de {fmt_eur(depassA)}</b> — {fmt_eur(invA)} > {fmt_eur(budget)}</div>', unsafe_allow_html=True)
with c2:
    if ok_budgetB:
        st.markdown(f'<div class="alert-ok">✅ <b>Projet B conforme</b> — {fmt_eur(invB)} ≤ budget {fmt_eur(budget)}</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="alert-ko">⚠️ <b>Projet B dépasse le budget de {fmt_eur(depassB)}</b> — {fmt_eur(invB)} > {fmt_eur(budget)}</div>', unsafe_allow_html=True)

# ───────────────────────── Cartes métriques ─────────────────────────
st.markdown("## 📊 Indicateurs clés")

def carte(label, valeur, sous, bonne: Optional[bool] = None):
    cls = "metric-card" + (" good" if bonne is True else " bad" if bonne is False else "")
    st.markdown(f'<div class="{cls}"><div class="label">{label}</div><div class="value">{valeur}</div><div class="sub">{sous}</div></div>', unsafe_allow_html=True)

m1, m2, m3, m4 = st.columns(4)
with m1:
    carte("VAN — Projet A", fmt_eur(vanA), f"Taux {taux:.1%}", vanA > 0)
with m2:
    carte("VAN — Projet B", fmt_eur(vanB), f"Taux {taux:.1%}", vanB > 0)
with m3:
    carte("TRI — Projet A", fmt_pct(triA), "vs coût du capital", None if triA is None else triA > taux)
with m4:
    carte("TRI — Projet B", fmt_pct(triB), "vs coût du capital", None if triB is None else triB > taux)

m5, m6, m7, m8 = st.columns(4)
with m5:
    carte("Payback actualisé A", fmt_payback(pb_actuA), f"Simple : {fmt_payback(pb_simpleA)}")
with m6:
    carte("Payback actualisé B", fmt_payback(pb_actuB), f"Simple : {fmt_payback(pb_simpleB)}")
with m7:
    carte("Investissement A", fmt_eur(invA), "✅ Conforme" if ok_budgetA else "⚠️ Hors budget", ok_budgetA)
with m8:
    carte("Investissement B", fmt_eur(invB), "✅ Conforme" if ok_budgetB else "⚠️ Hors budget", ok_budgetB)

# ───────────────────────── Graphique 1 : flux cumulés actualisés ─────────────────────────
st.markdown("## 📈 Flux cumulés actualisés (comparatif)")
annees = list(range(0, horizon + 1))
cumA_full = [-invA] + list(np.array(cumA) if len(cumA) else [-invA] * 0)
# cumA déjà = cumul actualisé incluant -invest ; on reconstruit proprement pour le graphe
def cumul_actu(inv, cfs, r):
    out = [-inv]
    s = -inv
    for i, c in enumerate(cfs, 1):
        s += c / (1 + r) ** i
        out.append(s)
    return out

ca, cb = cumul_actu(invA, cfA, taux), cumul_actu(invB, cfB, taux)
fig1 = go.Figure()
fig1.add_trace(go.Scatter(x=annees, y=ca, mode="lines+markers", name="Projet A",
                          line=dict(color="#2E7D32", width=3), fill="tozeroy",
                          fillcolor="rgba(46,125,50,0.12)"))
fig1.add_trace(go.Scatter(x=annees, y=cb, mode="lines+markers", name="Projet B",
                          line=dict(color="#66BB6A", width=3, dash="dash"), fill="tozeroy",
                          fillcolor="rgba(102,187,106,0.12)"))
fig1.add_hline(y=0, line_dash="dot", line_color="grey", annotation_text="Seuil de rentabilité")
fig1.update_layout(title="Récupération du capital (valeurs actualisées)",
                   xaxis_title="Année", yaxis_title="Flux cumulé actualisé (€)",
                   template="plotly_white", hovermode="x unified",
                   legend=dict(orientation="h", y=1.08))
st.plotly_chart(fig1, width="stretch")

# ───────────────────────── Graphique 2 : sensibilité ─────────────────────────
st.markdown("## 🎲 Analyse de sensibilité face au risque de marché")
g1, g2 = st.columns(2)

with g1:
    df_scen = pd.DataFrame({
        "Scénario": ["Pessimiste", "Base", "Optimiste"],
        "Projet A": [vanA_pes, vanA, vanA_opt],
        "Projet B": [vanB_pes, vanB, vanB_opt],
    })
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(x=df_scen["Scénario"], y=df_scen["Projet A"], name="Projet A", marker_color="#1B5E20"))
    fig2.add_trace(go.Bar(x=df_scen["Scénario"], y=df_scen["Projet B"], name="Projet B", marker_color="#81C784"))
    fig2.update_layout(title=f"VAN par scénario (±{volatilite:.0%} sur les cash-flows)",
                       yaxis_title="VAN (€)", template="plotly_white", barmode="group")
    st.plotly_chart(fig2, width="stretch")

with g2:
    taux_range = np.linspace(max(0.001, taux - 0.08), taux + 0.12, 60)
    sensA = [van(invA, cfA, r) for r in taux_range]
    sensB = [van(invB, cfB, r) for r in taux_range]
    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(x=taux_range * 100, y=sensA, name="Projet A", line=dict(color="#2E7D32", width=3)))
    fig3.add_trace(go.Scatter(x=taux_range * 100, y=sensB, name="Projet B", line=dict(color="#66BB6A", width=3, dash="dash")))
    fig3.add_hline(y=0, line_dash="dot", line_color="grey")
    fig3.add_vline(x=taux * 100, line_dash="dot", line_color="#1B5E20", annotation_text="Taux actuel")
    fig3.update_layout(title="Sensibilité de la VAN au taux d'actualisation",
                       xaxis_title="Taux (%)", yaxis_title="VAN (€)",
                       template="plotly_white", hovermode="x unified")
    st.plotly_chart(fig3, width="stretch")

# ───────────────────────── Recommandation automatique ─────────────────────────
st.markdown("## 🧭 Recommandation stratégique")

def score(van_, tri_, ok_bud, pb_):
    s = 0
    s += 3 if van_ > 0 else -3
    s += van_ / 100_000  # poids VAN
    if tri_ is not None and tri_ > taux:
        s += 2
    if tri_ is None:
        s -= 2
    if not ok_bud:
        s -= 5
    if pb_ is None:
        s -= 1
    return s

sA, sB = score(vanA, triA, ok_budgetA, pb_actuA), score(vanB, triB, ok_budgetB, pb_actuB)

if sA == sB and vanA == vanB:
    reco_titre, reco_texte = "🤝 Égalité parfaite", "Les deux projets sont équivalents sur tous les critères mesurés."
elif sA > sB:
    gagnant = "Projet A 🅰️"
    raisons = []
    if vanA > vanB: raisons.append(f"VAN supérieure ({fmt_eur(vanA)} vs {fmt_eur(vanB)})")
    if (triA or -1) > (triB or -1): raisons.append(f"TRI supérieur ({fmt_pct(triA)} vs {fmt_pct(triB)})")
    if ok_budgetA and not ok_budgetB: raisons.append("seul projet conforme au budget")
    if (pb_actuA or 99) < (pb_actuB or 99): raisons.append("récupération du capital plus rapide")
    if vanA_opt > vanB_opt and vanA_pes > vanB_pes: raisons.append("plus résilient dans tous les scénarios de risque")
    reco_titre, reco_texte = f"🏆 Recommandation : {gagnant}", " · ".join(raisons) + "." if raisons else "Meilleur score global."
else:
    gagnant = "Projet B 🅱️"
    raisons = []
    if vanB > vanA: raisons.append(f"VAN supérieure ({fmt_eur(vanB)} vs {fmt_eur(vanA)})")
    if (triB or -1) > (triA or -1): raisons.append(f"TRI supérieur ({fmt_pct(triB)} vs {fmt_pct(triA)})")
    if ok_budgetB and not ok_budgetA: raisons.append("seul projet conforme au budget")
    if (pb_actuB or 99) < (pb_actuA or 99): raisons.append("récupération du capital plus rapide")
    if vanB_opt > vanA_opt and vanB_pes > vanA_pes: raisons.append("plus résilient dans tous les scénarios de risque")
    reco_titre, reco_texte = f"🏆 Recommandation : {gagnant}", " · ".join(raisons) + "." if raisons else "Meilleur score global."

# Cas limites
avert = ""
if vanA < 0 and vanB < 0:
    avert = "<p>⚠️ <b>Attention :</b> les deux VAN sont négatives au taux actuel — aucun projet n'est rentable. Envisagez de renégocier les coûts ou d'abandonner.</p>"
if not ok_budgetA and not ok_budgetB:
    avert += "<p>⛔ <b>Les deux projets dépassent le budget global.</b> Un arbitrage budgétaire est indispensable.</p>"

st.markdown(f'<div class="reco"><h3>{reco_titre}</h3><p>{reco_texte}</p>{avert}</div>', unsafe_allow_html=True)

# ───────────────────────── Tableau récapitulatif ─────────────────────────
st.markdown("## 📋 Tableau récapitulatif complet")
recap = pd.DataFrame({
    "Indicateur": [
        "Investissement initial (€)", "Budget conforme ?",
        "VAN — scénario base (€)", "VAN — pessimiste (€)", "VAN — optimiste (€)",
        "TRI (%)", "TRI > coût du capital ?",
        "Payback simple", "Payback actualisé",
        "Total cash-flows non actualisés (€)",
    ],
    "Projet A": [
        fmt_eur(invA), "✅ Oui" if ok_budgetA else f"❌ Non ({fmt_eur(depassA)} de dépassement)",
        fmt_eur(vanA), fmt_eur(vanA_pes), fmt_eur(vanA_opt),
        fmt_pct(triA), "—" if triA is None else ("✅ Oui" if triA > taux else "❌ Non"),
        fmt_payback(pb_simpleA), fmt_payback(pb_actuA),
        fmt_eur(sum(cfA)),
    ],
    "Projet B": [
        fmt_eur(invB), "✅ Oui" if ok_budgetB else f"❌ Non ({fmt_eur(depassB)} de dépassement)",
        fmt_eur(vanB), fmt_eur(vanB_pes), fmt_eur(vanB_opt),
        fmt_pct(triB), "—" if triB is None else ("✅ Oui" if triB > taux else "❌ Non"),
        fmt_payback(pb_simpleB), fmt_payback(pb_actuB),
        fmt_eur(sum(cfB)),
    ],
})
st.dataframe(recap, width="stretch", hide_index=True)

csv = recap.to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Exporter le rapport (CSV)", csv, "rapport_van_tri.csv", "text/csv")

st.caption("Formules : VAN = −I₀ + Σ CFₜ/(1+r)ᵗ · TRI = taux annulant la VAN · Payback = 1ʳᵉ année où le cumulé ≥ 0.")
