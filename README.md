# 🧭 MARKET MIND

**Écosystème d'analyse, de simulation et d'aide à la décision sur les marchés — Bourse de Casablanca et marchés internationaux.**

Application **Streamlit** complète, en français, construite uniquement sur des **données de marché réelles** (API publique de la Bourse de Casablanca, Yahoo Finance, flux RSS publics, World Bank, documents officiels AMMC). Aucune donnée fondamentale n'est inventée : ce qui n'est pas disponible est signalé comme tel et peut être importé ou saisi.

**MARKET MIND** organise son écosystème autour d'un **parcours d'analyse unique** — comprendre, analyser, valoriser, surveiller, relier au portefeuille — pour répondre à une question concrète : *quelle décision d'analyse l'utilisateur peut-il mieux structurer grâce à l'application, et comment est-ce prouvé ?*

---

## Sommaire

- [Aperçu](#aperçu)
- [Parcours & thèses](#parcours--thèses)
- [Lancement rapide](#lancement-rapide)
- [Les 16 pages](#les-16-pages)
- [Sources de données et transparence](#sources-de-données-et-transparence)
- [États financiers](#états-financiers)
- [Renseigner les données fondamentales](#renseigner-les-données-fondamentales)
- [Agent IA](#agent-ia)
- [Architecture du projet](#architecture-du-projet)
- [Performance et cache](#performance-et-cache)
- [Hypothèses financières](#hypothèses-financières)
- [Limites et avertissement](#limites-et-avertissement)

---

## Aperçu

MARKET MIND réunit dans une seule interface :

| Domaine | Ce que fait l'application |
|---|---|
| **Parcours d'analyse** | Un fil conducteur en 5 étapes (comprendre → analyser → valoriser → surveiller → portefeuille) autour d'une même valeur, avec l'état de chaque étape et les manques à combler |
| **Marché BVC** | 81 valeurs cotées, 24 indices sectoriels, indices MASI / MASI 20, capitalisation, volumes, secteurs officiels |
| **Screener** | Filtres par secteur, signal, capitalisation, score, P/E, dividende, volume, Sharpe, volatilité ; export CSV |
| **Analyse société** | Chandeliers, moyennes mobiles, RSI/MACD, niveaux clés, plan d'entrée, ratios interprétés, actualités, analyse IA |
| **États financiers** | Bilan, compte de produits et charges, tableau de trésorerie sourcés (jeu vérifié AMMC, API EODHD/FMP/Yahoo, import CSV, documents officiels AMMC) ; aucun poste extrapolé |
| **Valorisation** | **Valuation Lab** : PER × BPA, EV/EBITDA, EV/EBIT, P/B, P/S, rendement du dividende, prix théorique, marge de sécurité et **prix d'entrée** ; DCF complet, sensibilité, trois scénarios, Monte-Carlo (4 000 simulations), valorisation relative sectorielle |
| **Thèses & surveillance** | **Valuation & Trigger Engine** : enregistrement d'une thèse (multiple cible, marge, métrique de référence, exercice, source) puis suivi des deux conditions — prix d'entrée atteint et mise à jour de la métrique (BPA, EBITDA, fonds propres, dividende) |
| **Profil investisseur** | Revenus (salaire), charges, patrimoine, dettes, horizon, tolérance au risque, positions détenues |
| **Simulateur** | Projection déterministe, 2 000 trajectoires Monte-Carlo, comparaison de 9 classes d'actifs, frontière efficiente |
| **Portefeuille & alternatives** | Allocation actuelle vs cible, plan de rééquilibrage chiffré, comparaison de chaque ligne à la meilleure opportunité |
| **Actualités** | Agrégation RSS, déduplication, sentiment par article et par secteur |
| **Market Mind AI** | Analyse directe d'une valeur (tendance, support/résistance, RSI, actualités, macro), chat, briefing, analyse complète, **rapport PDF téléchargeable** ; LLM détecté automatiquement ou analyste local hors-ligne ; facteurs favorables/défavorables, contradictions, données manquantes et confiance explicites |
| **Alertes & surveillance** | Scanner local : support/résistance, RSI, drawdown, variation journalière, plus haut/bas 52 semaines et VIX ; seuils modifiables, export CSV, aucune notification push |
| **Outils** | Comparateur de projets VAN / TRI / payback (outil historique conservé), sources et méthodologie |

Le design s'inspire de la densité analytique de Bloomberg et de la clarté éditoriale de Reuters, avec une identité propre : fond blanc cassé, bleu marine, vert turquoise, typographie serif pour les titres et graphiques Plotly lisibles sur fond clair (template `marketmind`).

---

## Parcours & thèses

Le cœur du produit n'est pas un assemblage de modules : c'est un **parcours reproductible** qui relie les données à une hypothèse, puis à sa surveillance.

| Étape | Question à laquelle elle répond | Où |
|---|---|---|
| **1. Comprendre** | Que disent le marché, l'actualité et le contexte ? | Vue globale, Actualités, Analyse société |
| **2. Analyser** | Que disent les états financiers et les ratios ? | États financiers, Données fondamentales, Screener |
| **3. Valoriser** | Quel prix correspond à mes hypothèses ? | Valuation Lab, Market Mind AI |
| **4. Surveiller** | Mes conditions de suivi sont-elles réunies ? | Alertes & surveillance (thèses actives) |
| **5. Relier au portefeuille** | Quelle exposition et quel risque ? | Mon patrimoine, Simulateur, Portefeuille |

La page **Parcours d'analyse** matérialise ces cinq étapes pour une valeur sélectionnée et affiche, pour chacune, ce qui est disponible, ce qui manque et où le compléter.

### Valuation & Trigger Engine

Le **Valuation Lab** transforme vos hypothèses en conditions de suivi. Exemple purement illustratif (pas une cotation réelle) : cours 400 MAD, BPA de référence 10 MAD, PER actuel 40×, PER cible 30× → prix théorique `30 × 10 = 300 MAD`. Avec une marge de sécurité de 10 %, le prix d'entrée de surveillance est 270 MAD.

Trois précautions sont affichées en permanence :

1. un PER cible de 30 n'est pas « un bon prix » en soi — il dépend de la croissance, de la rentabilité, du secteur et des taux ;
2. le prix cible **change si le BPA change** : la thèse est recalculée dès que la métrique ou l'exercice comptable évolue ;
3. atteindre le seuil est une **condition de surveillance, pas une prédiction** ni une recommandation.

Une thèse enregistrée conserve la méthode, le multiple cible, la marge, la métrique de référence, l'exercice, la source et vos notes. Elle est stockée localement dans `data/user/theses.json` et suivie dans la page Alertes.

---

## Lancement rapide

```bash
cd app-VAN
python3 -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt
python3 -m streamlit run app.py
```

L'application s'ouvre sur `http://localhost:8501`.

**Clés API** : ne jamais écrire une clé dans le code ou dans un fichier versionné. Utilisez `.env` (ignoré par Git) ou la configuration locale de l'application. Exemple Anthropic : `ANTHROPIC_API_KEY=…` et éventuellement `ANTHROPIC_MODEL=…`.

### Précharger les données (recommandé avant une démo)

```bash
python scripts/refresh_data.py
# ou, pour forcer le rechargement :
python scripts/refresh_data.py --force --days 750
```

Le script télécharge les indices, les 81 valeurs, les dividendes, le VIX, les marchés internationaux et les actualités, puis écrit un rapport de couverture dans `data/seed/fundamentals_coverage.csv`.

### Prérequis

- Python **3.9+**
- Connexion Internet pour les données de marché (l'application reste consultable hors-ligne avec le dernier cache)
- Aucune clé d'API n'est nécessaire — y compris pour l'agent IA (mode analyste local)

---

## Les 16 pages

| Page | Contenu |
|---|---|
| 🧭 **Accueil** | Centre de pilotage : hero éditorial, recherche d'une valeur, **parcours en 5 étapes**, Market Pulse (indices, VIX, largeur), graphique MASI, mouvements, actualités et lecture explicable |
| 🧭 **Parcours d'analyse** | Les 5 étapes pour une valeur : statut de chaque étape, conditions de la thèse (prix d'entrée, mise à jour de la métrique), dossier de preuve (sources, dates, statuts) |
| 🏠 **Vue globale du marché** | MASI, largeur de marché, VIX, sentiment des news, capitalisation ; graphique MASI 6 mois ; jauge VIX et décomposition du régime ; treemap sectorielle ; hausses/baisses et volumes ; nuage risque/rendement ; briefing IA à la demande ; marchés internationaux et macro |
| 🔍 **Screener BVC** | Filtres complets, KPI de sélection, synthèse par secteur, tableau interactif (sélection d'une ligne → ouverture de la fiche société), export CSV, top opportunités |
| 🏢 **Analyse société** | En-tête cours/secteur/signaux, KPI, onglets Synthèse / Technique / Fondamentaux / Actualités / Agent IA ; comparaison Base 100 vs MASI ; radar multifactoriel ; plan d'entrée |
| 🧾 **États financiers** | Compte de résultat, bilan (actif/passif) et trésorerie par exercice, avec source, devise, unité et statut ; import API (EODHD, FMP, Yahoo), CSV vérifié, documents officiels AMMC, couverture par société |
| 📰 **Actualités & sentiment** | Sentiment 7 jours, sentiment sectoriel, répartition par source, filtres (recherche, source, tonalité, fenêtre), cartes d'articles cliquables |
| 🧮 **Valorisation & thèses** | **Valuation Lab** en tête de page (PER cible × BPA, EV/EBITDA, EV/EBIT, P/B, P/S, rendement exigé, marge de sécurité, prix d'entrée, sensibilité), **enregistrement d'une thèse**, puis DCF complet, hypothèses ajustables, projection des FCF, scénarios, Monte-Carlo et comparaison sectorielle |
| 📊 **Données fondamentales** | Saisie par société, import CSV en masse, modèle téléchargeable, rapport de couverture, mode d'emploi détaillé |
| 👤 **Mon profil** | Revenus et charges, patrimoine et dettes, objectifs, tolérance au risque, diagnostic patrimonial, éditeur de positions avec valorisation aux cours réels |
| 📈 **Simulateur** | Capital initial, versements mensuels, horizon, rendement et volatilité ; projection, éventail Monte-Carlo, comparaison des placements classée selon le profil, frontière efficiente, effort d'épargne nécessaire |
| 💼 **Portefeuille & arbitrage** | Allocation actuelle vs cible, donuts comparés, plan de rééquilibrage en MAD avec frais estimés, recommandation argumentée, opportunités du marché, comparaison des lignes détenues |
| 🧠 **Market Mind AI** | Analyse directe (cours, tendance, support/résistance, RSI, actualités, macro), scénarios haussier/baissier, contradictions, données manquantes, confiance, **rapport PDF** ; chat, briefing, analyse complète, configuration du fournisseur LLM avec test de connexion |
| 🔔 **Alertes & surveillance** | **Thèses de valorisation** (prix d'entrée atteint, métrique à actualiser, suppression) puis scan de la liste de suivi ou du marché complet : support/résistance 120 j, RSI, drawdown, variation, proximité des extrêmes 52 semaines, VIX ; seuils réglables, tableau et export CSV |
| 🌿 **Projets VAN / TRI** | Comparateur Projet A vs Projet B : VAN, TRI, payback simple et actualisé, contrôle budgétaire, scénarios, sensibilité au taux, export |
| 📚 **Sources & méthodologie** | Tableau des sources, statut (temps réel/différé/annuel), licences, limites, formules de valorisation et avertissements |

---

## Sources de données et transparence

### Données de marché — réelles et automatiques

| Donnée | Source | Détail |
|---|---|---|
| Cours, volumes, OHLC, capitalisation | **Bourse de Casablanca** — `casablanca-bourse.com/api/boursenova` | Historique ajusté (`isCoursAjuste=true`) pour les splits et attributions |
| Indices, compositions, secteurs officiels | API BVC + pages `drupalSettings` | MASI, MASI 20, MASIMS, ESGI et 24 indices sectoriels |
| Nombre de titres, ISIN, compartiment | Page publique « actions » de la BVC | Récupéré automatiquement, sans clé |
| Dividende par action (DPS) | Calendrier financier de la BVC | Dernier dividende détaché, avec exercice et type |
| VIX, S&P 500, Nasdaq, or, pétrole, EUR/MAD, USD/MAD | **Yahoo Finance** (`yfinance`) | Séries et cotations publiques |
| Actualités | Flux **RSS publics** (BVC, presse économique marocaine et internationale) | Dédupliquées, datées, analysées en sentiment |
| Macro Maroc : PIB, inflation, chômage | **World Bank Open Data** (`api.worldbank.org`) | Séries **annuelles différées**, avec année et date de mise à jour ; ne remplacent pas HCP/BAM |

### Données fondamentales — BVC, AMMC et API

La BVC **ne publie pas** de P/E, résultat net, chiffre d'affaires, capitaux propres ni flottant via son API. En revanche, deux champs sont récupérés **automatiquement et réellement** :

- le **nombre de titres** (page « actions ») ;
- le **dividende par action** (calendrier financier).

Les états financiers proviennent de trois voies, toutes traçables et jamais inventées :

1. un **jeu vérifié** (`data/seed/bvc_statements.json`) repris des rapports financiers annuels publiés par l'**AMMC**, avec l'URL du document ;
2. des **API** externes (EODHD, Financial Modeling Prep) ou Yahoo Finance, configurées par variable d'environnement ;
3. un **import CSV** ou la **saisie manuelle**, qui restent prioritaires sur les données importées.

Tout champ non renseigné reste vide et s'affiche « — » : **aucune valeur n'est extrapolée**.

### Signaux

Chaque valeur porte la mention **« technique seul »** tant que ses états financiers ne sont pas renseignés. Le score composite combine alors uniquement marché et technique. Dès que des données comptables sont disponibles, les dimensions valorisation et qualité sont activées et la complétion des données est affichée.

---

## États financiers

La page **États financiers** présente, pour chaque société, le **compte de résultat**, le **bilan** (actif/passif) et le **tableau de trésorerie**, exercice courant et précédent, avec devise, unité, source, exercice et statut.

### Sources disponibles

| Source | Accès | Couverture | Remarque |
|---|---|---|---|
| **Jeu vérifié AMMC** | embarqué | Quelques sociétés (ex. TotalEnergies Marketing Maroc, Maghreb Oxygène) | Chiffres repris des rapports annuels, URL du PDF conservée |
| **EODHD** | `EODHD_API_KEY` (+ `EODHD_EXCHANGE`) | Mondiale, à vérifier pour Casablanca | États annuels et trimestriels |
| **Financial Modeling Prep** | `FMP_API_KEY` | Mondiale, à vérifier pour le Maroc | Compte de résultat, bilan, trésorerie |
| **Yahoo Finance** | sans clé (`yfinance`) | Surtout international | Couverture marocaine limitée |
| **CSV vérifié** | fichier local | Toutes | Modèle téléchargeable depuis la page |
| **Documents AMMC** | public | Émetteurs cotés | Liste et PDF officiels ; extraction de lignes à titre de preuve, saisie humaine |

### Ce qui n'est pas fait

- Aucune **extraction automatique enregistrée** : la lecture d'un PDF AMMC affiche les lignes brutes pour vérification, mais rien n'est écrit sans validation. Les mises en page comptables sont hétérogènes et une extraction naïve produirait des chiffres faux.
- Aucun **scraping** de contenus protégés : seules les pages publiques de l'AMMC sont lues, avec cache de 24 h.
- Les états sont **sociaux (non consolidés)** par défaut ; les comptes consolidés doivent être importés explicitement.

### Rattachement à la valorisation

Les ratios (PER, P/B, ROE, EV/EBITDA, rendement du FCF…) et le **Valuation Lab** utilisent automatiquement le dernier état connu. Une thèse enregistrée suit la métrique de référence : si le BPA (ou l'EBITDA, les fonds propres, le dividende) change, la thèse est signalée « à actualiser ».

---

## Renseigner les données fondamentales

### Saisie manuelle

1. Ouvrir **Données fondamentales → Saisie**.
2. Choisir la société.
3. Renseigner les champs disponibles (les champs vides sont ignorés).
4. Cliquer sur **Enregistrer** : les ratios, scores et signaux sont recalculés immédiatement.

Les pourcentages se saisissent en clair : `8` pour **8 %** (converti en `0,08`).

### Import CSV

- Télécharger le modèle depuis **Données fondamentales → Import CSV**.
- Une ligne par société, première colonne `symbol`.
- Colonnes acceptées (tout ou partie) :

```text
symbol, revenue, ebitda, ebit, net_income, eps, fcf, operating_cf, capex,
equity, total_debt, cash, total_assets, current_assets, current_liabilities,
shares, dps, payout, revenue_growth, net_income_growth, fcf_growth, beta,
fiscal_year, source, as_of
```

- Séparateur `;` ou `,` détecté automatiquement, encodage UTF-8 (BOM accepté).
- Les pourcentages peuvent être saisis `8` ou `0,08`.
- Les données sont stockées **localement** dans `data/user/fundamentals_overrides.json`.

### Ratios calculés automatiquement

P/E, P/B, P/S, EV/EBITDA, rendement du dividende, payout, ROE, ROA, marges brute et nette, dette nette / fonds propres, levier, ratio de liquidité, rendement du FCF, croissance du CA et du résultat, bénéfice par action, valeur comptable par action — chacun avec **appréciation et interprétation** (seuils adaptés au marché marocain), puis comparaison à la **médiane sectorielle**.

---

## Agent IA

Deux modes, transparents dans l'interface :

1. **Mode LLM** — si une clé est détectée, les données réelles de l'application sont injectées dans le prompt et le modèle rédige l'analyse.
2. **Mode analyste local** — sinon, un moteur de règles déterministe répond en langage naturel à partir des mêmes données, **100 % hors-ligne**.

Fournisseurs supportés (détection automatique) : **OpenAI, Anthropic, DeepSeek, Groq, Google Gemini, Mistral, Ollama**.

Configuration, sans redémarrage :

- **Dans l'application** : *Agent IA → Configuration* (clé stockée dans `data/user/ai_config.json`).
- **Par variables d'environnement** : copier `.env.example` en `.env` et renseigner une clé, ou exporter directement `OPENAI_API_KEY`, etc. Forcer un fournisseur avec `ECOINVEST_LLM_PROVIDER`.

L'agent ne dispose **que** des données chargées par l'application : marché, régime, secteurs, ratios disponibles, profil et positions. Aucun chiffre n'est inventé. L'analyse directe ajoute les niveaux techniques, le RSI, les actualités sourcées et la macro Maroc ; chaque affirmation doit être reliée à une donnée ou signalée comme manquante.

Le bouton **« Télécharger le rapport PDF »** produit un document daté avec les données de marché, la macro, l'analyse, les actualités utilisées, les sources, les limites et l'avertissement. `reportlab` est utilisé lorsqu'il est installé ; sinon un rapport Markdown structuré est proposé, sans masquer l'erreur.

**Confidentialité** : par défaut, les montants personnels (revenus, patrimoine, dettes, objectifs) **ne sont pas transmis** au modèle. Seuls le profil de risque, les ratios d'épargne, l'horizon et les poids du portefeuille sont envoyés. Un réglage explicite dans *Market Mind AI* permet d'autoriser le partage des montants ; il est sans effet en mode analyste local, où aucune donnée ne quitte la machine. Les données restent dans `data/user/`, jamais versionnées.

---

## Valuation Lab — du multiple au prix d'entrée (et à la thèse)

La page **Valorisation & thèses** commence par un laboratoire de prix théorique :

```text
prix théorique = multiple cible × métrique de référence
prix d'entrée  = prix théorique × (1 − marge de sécurité exigée)
```

Méthodes disponibles : **PER cible × BPA**, **EV/EBITDA**, **EV/EBIT**, **P/B**, **P/S** et **rendement du dividende**. Les passages EV → capitaux propres utilisent la dette nette et le nombre d'actions. Le rendement implicite et la marge de sécurité sont affichés.

Règles de transparence :

- si le BPA, l'EBITDA, les fonds propres, les ventes ou le dividende sont absents ou non pertinents (négatifs/nuls), la méthode est marquée **indisponible** avec la raison ;
- une donnée de référence peut être saisie manuellement pour un calcul ponctuel, mais elle **n'est pas enregistrée** et doit être justifiée par un rapport annuel ou un communiqué ;
- le prix théorique et le prix d'entrée sont **conditionnels aux hypothèses** ; ce ne sont ni des objectifs de cours ni des recommandations ;
- le tableau de sensibilité montre l'effet du multiple et de la marge de sécurité.

Le bouton **« Enregistrer cette hypothèse pour la surveiller »** crée une **thèse** : la méthode, le multiple cible, la marge, la métrique de référence, l'exercice comptable, la source et vos notes sont conservés dans `data/user/theses.json`. La page **Alertes & surveillance** réévalue chaque thèse au cours courant et signale :

- le **prix d'entrée atteint** (ou proche) ;
- une **métrique de référence modifiée** (BPA, EBITDA, fonds propres, dividende) ;
- un **nouvel exercice comptable** disponible.

Ces signaux invitent à **recalculer** la thèse ; ils ne sont pas des recommandations et ne promettent aucun prix.

---

## Architecture du projet

```text
app-VAN/
├── app.py                        # Point d'entrée : thème, navigation en 5 étapes, sidebar
├── requirements.txt
├── .env.example
├── scripts/
│   └── refresh_data.py           # Préchauffage des caches + rapport de couverture
├── data/
│   ├── cache/                    # Cache SQLite (généré automatiquement)
│   ├── seed/bvc_universe.json    # Univers BVC de secours (généré)
│   ├── seed/bvc_statements.json  # États financiers vérifiés (AMMC)
│   └── user/                     # Profil, positions, fondamentaux, états, thèses, watchlist
└── ecoinvest/
    ├── config.py                 # Chemins, palette, TTL, hypothèses de marché
    ├── theme.py                  # CSS, template Plotly « marketmind », setup_page
    ├── data/
    │   ├── bvc.py                # API BVC, historiques, référentiel, dividendes
    │   ├── market.py             # Yahoo Finance : VIX, indices, macro, devises
    │   ├── news.py               # Flux RSS, déduplication, sentiment
    │   ├── statements.py         # États financiers : magasin, API (EODHD/FMP/Yahoo), AMMC, CSV
    │   └── fundamentals.py       # Ratios, interprétation, dérivation depuis les états
    ├── analytics/
    │   ├── technical.py          # SMA/EMA, RSI, MACD, Bollinger, niveaux, signaux
    │   ├── risk.py               # Volatilité, Sharpe, Sortino, VaR, bêta, drawdown
    │   ├── scoring.py            # Tableau de marché, score composite, régime
    │   ├── valuation_lab.py      # Prix théorique, prix d'entrée, sensibilité
    │   ├── thesis.py             # Valuation & Trigger Engine : thèses et conditions
    │   ├── alerts.py             # Règles d'alerte locales et explicables
    │   └── forecast.py           # DCF, sensibilité, scénarios, Monte-Carlo, objectifs
    ├── portfolio/
    │   ├── profile.py            # Profil, diagnostics, positions, synthèse
    │   ├── optimize.py           # Classes d'actifs, frontière, allocation cible
    │   └── simulate.py           # Comparaison de placements, recommandation
    ├── ai/
    │   ├── llm.py                # Fournisseurs, détection, repli local
    │   ├── prompts.py            # Prompts système et contextes
    │   └── agent.py              # Briefing, analyse société, chat
    ├── ui/
    │   ├── components.py         # Cartes KPI, badges, tableaux, notes, verdicts
    │   ├── charts.py             # Toutes les figures Plotly
    │   └── pages/                # Les 16 pages + shared.py (chargements cachés)
    └── utils/
        ├── cache.py              # Cache SQLite + mémoire
        ├── formatting.py         # Formatage français (MAD, %, multiples)
        └── finance.py            # VAN, TRI, payback, DCF, rentes
```

---

## Performance et cache

- **Cache SQLite** : `data/cache/ecoinvest_cache.sqlite`, avec TTL par source (cours 3 min, snapshot 15 min, historiques 1 h, fondamentaux 24 h, actualités 15 min, macro 24 h, états financiers 24 h, documents AMMC 24 h).
- **Cache Streamlit** (`st.cache_data`) au-dessus du cache disque pour éviter tout recalcul entre les interactions.
- **Téléchargements parallèles** des historiques BVC (jusqu'à 10 requêtes simultanées).
- **Repli hors-ligne** : en cas d'échec réseau, la dernière copie locale est restituée.
- **Rafraîchissement manuel** : bouton « 🔄 Rafraîchir les données » dans la barre latérale, ou `python scripts/refresh_data.py --force`.

Après une modification des fondamentaux, seuls les caches de scoring sont purgés — les historiques de cours sont conservés.

---

## Hypothèses financières

Valeurs par défaut, modifiables dans `ecoinvest/config.py` et, pour le taux sans risque, via `ECOINVEST_RISK_FREE_RATE` :

| Paramètre | Valeur |
|---|---|
| Taux sans risque | 2,75 % |
| Prime de risque actions | 6,5 % |
| Rendement long terme MASI | 9,5 % (volatilité 14,5 %) |
| Inflation | 2,1 % |
| Fiscalité plus-values (TPCVM) | 15 % |
| Fiscalité dividendes | 13 % |
| Frais de courtage (aller-retour) | 0,60 % |

Le coût des fonds propres du DCF est estimé par le CAPM : taux sans risque + bêta × prime de risque actions.

---

## Limites et avertissement

- Les **performances passées ne préjugent pas des performances futures**.
- Les projections DCF et Monte-Carlo dépendent entièrement des hypothèses saisies ; plus de 75 % de la valeur provenant de la valeur terminale est explicitement signalé.
- Les **données fondamentales manquantes ne sont jamais estimées** : les ratios concernés restent vides.
- Les **états financiers importés via API** dépendent du fournisseur (couverture et exactitude) ; le jeu vérifié provient des rapports annuels AMMC. Un PDF AMMC n'est pas une API et son extraction automatique n'est jamais enregistrée sans vérification.
- Les **thèses de valorisation** sont des conditions de surveillance : atteindre le prix d'entrée ne prouve pas que la société est sous-évaluée, et le seuil peut ne jamais être atteint.
- Le sentiment des actualités est un lexique indicatif, pas une analyse éditoriale.
- Les **alertes sont locales et calculées à la demande** : aucun e-mail, SMS ou push n'est envoyé. Une alerte de support/RSI n'est pas un ordre.
- La macro Maroc est **annuelle et différée** (World Bank) ; elle ne remplace pas les publications trimestrielles du HCP ni les taux de Bank Al-Maghrib.
- Le **VIX** mesure la volatilité implicite des options sur le S&P 500 ; il n'est pas une mesure directe de la volatilité du MASI.
- Le **backtesting** avec coûts de transaction et validation hors échantillon n'est pas encore intégré ; les simulations Monte-Carlo ne constituent pas un backtest.
- Les frais réels (courtage, conservation, taxes) varient selon l'intermédiaire ; les hypothèses sont affichées dans les simulations.
- **Cette application est un outil d'analyse et de simulation. Elle ne constitue pas un conseil en investissement.** Les décisions restent sous la responsabilité de l'utilisateur.
