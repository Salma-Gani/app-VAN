# 🌿 EcoInvest — Analyse VAN / TRI

Application Streamlit d'aide à la décision d'investissement : compare deux projets
(Projet A vs Projet B) avec calculs financiers automatisés et graphiques interactifs.

## Fonctionnalités

- 🎨 Interface vert nature / blanc (cartes métriques, boutons verts)
- ⚙️ Sidebar dynamique : taux d'actualisation, horizon (1–15 ans), budget max, volatilité
- 📝 Saisie : investissement initial + cash-flows annuels par projet
- 🧮 VAN, TRI (bissection), payback simple **et** actualisé, contrôle budgétaire
- 📈 Plotly : flux cumulés actualisés + VAN par scénario + sensibilité au taux
- 🧭 Recommandation automatique (VAN, TRI, budget, risque) + tableau récapitulatif + export CSV

## Lancement

```bash
cd app-VAN
pip install -r requirements.txt
streamlit run app.py
```

## Formules

- **VAN** = −I₀ + Σ CFₜ / (1+r)ᵗ
- **TRI** = taux r annulant la VAN (résolution par bissection)
- **Payback** = 1ʳᵉ année où le flux cumulé (simple ou actualisé) ≥ 0
- **Scénarios** : pessimiste = CF × (1 − volatilité), optimiste = CF × (1 + volatilité)
