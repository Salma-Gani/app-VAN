# Lot A — Diagnostic des régressions et plan de restauration ciblé

**Date :** 20 octobre 2026  
**Version :** 3.8.0  
**Référence de comparaison :** `6448b83` — « ATLAS FINANCE v3 : accueil, identité claire et analyses explicables » (18/10/2026), première version institutionnelle aboutie.  
**HEAD au début du Lot A :** `4d809d4` — « Comparaison sectorielle : sources des ratios explicites » (20/10/2026).  
**Branche :** `main`, alignée sur `origin/main`, arbre de travail propre avant les correctifs.

> Ce document répond aux trois questions posées avant toute refonte :
> 1. quels fichiers et commits sont responsables des régressions ;
> 2. pourquoi les états financiers et les ratios sont vides ;
> 3. pourquoi le fournisseur IA du briefing échoue.
>
> Il propose ensuite un plan par lots, avec critères d'acceptation. Aucune donnée
> financière n'a été inventée, aucun PDF n'a été auto-validé, aucun module n'a été
> réécrit intégralement.

---

## 1. Inventaire de l'existant

### Ce qui fonctionne

| Domaine | État vérifié |
|---|---|
| Accueil | Structure, navigation, Market Pulse, mouvements de séance, carte du marché. |
| MASI | Historique réel BVC, variation, YTD, graphique. |
| Carte du marché | Rendu réparé en v3.5, couleurs et largeur de marché. |
| Screening technique | Filtres, tri, indicateurs calculés sur l'historique BVC. |
| Analyse société | Cours, volumes, technique, actualités, backtest. |
| Comparaison sectorielle | 13 métriques, médianes, rangs, exclusions banques/assurances. |
| Actualités | 113 articles, 6 sources, sentiment lexical, déduplication. |
| Portefeuille / simulateur | Journal d'opérations, coût moyen pondéré, frais, benchmark MASI. |
| Sources & méthodologie | Statut, licence, période, limites de chaque source. |

### Ce qui est dégradé

| Problème visible | Cause | Statut |
|---|---|---|
| HTML brut (`</div>`, `class="ei-muted"`) dans le fil d'actualités | Indentation Markdown + résumés RSS multilignes | **Corrigé** |
| VIX présenté comme risque du marché marocain | Le VIX S&P 500 alimente encore l'accueil, les alertes et 30 % du régime de marché | **À corriger (Lot B)** |
| Briefing IA en erreur | Modèle Gemini `gemini-2.0-flash` retiré par Google (404) | **Corrigé** |
| Tableaux financiers vides pour IAM, ATW, etc. | Couverture documentaire : seuls TMA et MOX ont des états vérifiés | **À traiter (Lot C)** |
| Étapes du parcours génériques | Aucune donnée financière pour la valeur sélectionnée par défaut (ATW) | **À traiter (Lot D)** |

### Ce qui n'est pas couvert

- 79 des 81 valeurs cotées n'ont pas d'états financiers vérifiés dans le seed.
- Les banques n'ont ni résultat net ni capitaux propres dans les données BVC : PER, P/B, ROE et marges restent indisponibles.
- La macroéconomie ne contient que les séries World Bank (PIB, inflation, chômage) ; Bank Al-Maghrib, HCP et ministère des Finances ne sont pas branchés.
- Aucun paiement / abonnement n'existe.
- L'authentification reste mono-utilisateur locale.

---

## 2. Réponse 1 — Fichiers et commits responsables des régressions

### 2.1 HTML brut dans les actualités

**Commit d'introduction :** `e6306b4` — « EcoInvest Pro v2 : analyse BVC, simulation et agent IA » (18/10/2026).  
**Commit qui a exposé le bug :** `3a45e19` — « MARKET MIND v3.5 : erreurs HTTP classifiées, carte thermique réparée, actualités 5 niveaux, macropage » (19/10/2026).

**Fichiers :**

- `ecoinvest/ui/pages/news_page.py`, fonction `_card()` ;
- `ecoinvest/ui/pages/company.py`, fonction `_news_card()` ;
- `ecoinvest/ui/pages/alerts_page.py`, cartes d'alertes et de thèses.

**Mécanisme exact :**

Le HTML est passé à `st.markdown()` dans une chaîne indentée de 8 à 12 espaces.
Markdown interprète une ligne indentée de 4 espaces ou plus comme un **bloc de code**
lorsqu'elle suit une ligne vide. Les résumés RSS contiennent des retours à la ligne
et des lignes vides (`"… pour le lire. \n\nLire la suite"`). Dès qu'un résumé
multiligne est interpolé, le bloc HTML est coupé ; la suite est rendue dans
`<pre><code>` et l'utilisateur voit le code source de la carte.

**Preuve avant correction :** 17 balises `<pre>` sur `/actualites`, 47 cartes générées.  
**Preuve après correction :** 0 balise `<pre>`, 47 cartes, aucun `ei-muted` brut.  
**Correctifs :** normalisation des textes dynamiques en une seule ligne + `textwrap.dedent()`
avant `st.markdown()` dans les trois fichiers.

### 2.2 VIX affiché comme volatilité marocaine

**Commit d'introduction :** `6448b83` — l'accueil « Market Pulse » et la carte de régime
affichent le VIX. Ce n'est donc pas une régression d'un commit ultérieur : c'est un
défaut conceptuel présent dès la première version institutionnelle.

**Fichiers concernés :**

- `ecoinvest/data/market.py` : `vix_series()`, `vix_level()`, `vix_regime()` sur `^VIX` Yahoo ;
- `ecoinvest/analytics/scoring.py` : `market_regime()` pondère le VIX à **30 %** du `entry_gate` ;
- `ecoinvest/ui/pages/home.py` : lignes `VIX` dans `_pulse_html()` et `_regime_card()` ;
- `ecoinvest/ui/pages/dashboard.py` : bloc `_vix_block()` et jauge VIX ;
- `ecoinvest/ui/pages/alerts_page.py` : alerte `vix_high` ;
- `ecoinvest/ai/prompts.py`, `agent.py`, `report.py` : le VIX est cité dans le briefing.

**Ce qui existe déjà :** `dashboard._masi_volatility()` calcule une volatilité réalisée
du MASI (écart-type des rendements quotidiens sur 60 séances × √252), mais **uniquement
pour l'affichage** ; elle n'entre ni dans le régime, ni dans l'accueil, ni dans les alertes.

**Décision :** le VIX ne doit plus être un composant du régime marocain. La volatilité
réalisée du MASI devient l'indicateur principal, avec méthode, fenêtre et date. Le VIX
peut rester dans un bloc « contexte international » explicitement étiqueté, ou être retiré.

### 2.3 États financiers et ratios vides

**Ce n'est pas une régression de code.** C'est un **défaut de couverture documentaire**.

**Preuve mesurée le 20/10/2026 :**

| Valeur | États trouvés | Ratios calculés | Source |
|---|---:|---:|---|
| TMA | 2 (2023, 2024) | 18 / 19 | états financiers vérifiés + BVC |
| MOX | 1 (2024) | 16 / 19 | états financiers vérifiés + BVC |
| IAM | 0 | 1 / 19 | référentiel BVC seul |
| ATW | 0 | 1 / 19 | référentiel BVC seul |

**Fichiers / causes :**

- `data/seed/bvc_statements.json` ne contient que `TMA` et `MOX` (clé `companies`).
- `ecoinvest/data/statements.py` : `FETCHERS = {"eodhd", "fmp", "yahoo"}` ; l'AMMC est
  un onglet d'import de documents, pas un connecteur API.
- `ecoinvest/ui/pages/statements_page.py` : l'onglet « API externe » ne propose que
  EODHD/FMP/Yahoo ; sans clé EODHD/FMP, seul Yahoo reste, avec une couverture marocaine
  limitée et non vérifiée.
- `ecoinvest/ui/pages/parcours_page.py` : la valeur par défaut est ATW (banque sans états),
  ce qui donne immédiatement l'impression d'une page vide.

**Conséquence :** les tableaux ne sont pas « cassés » ; ils sont honnêtement vides parce
que la donnée source n'a pas été importée et validée. La correction consiste à étendre
la couverture depuis l'AMMC/BVC, document par document, pas à remplir les cases.

### 2.4 Briefing IA en erreur

**Commit d'introduction :** `e6306b4` — modèle par défaut `gemini-2.0-flash`.  
**Cause exacte :** Google a retiré ce modèle. Un appel direct renvoie :

```
404 NOT_FOUND — This model models/gemini-2.0-flash is no longer available to new users.
Please update your code to use models/gemini-3.8-flash ...
```

La clé, elle, est valide : `GET /v1beta/models` répond **200** et liste 46 modèles
`generateContent`. Le problème n'est donc ni l'authentification, ni le réseau, ni le quota.

**Correctifs :**

- modèle par défaut → `gemini-flash-lite-latest` (alias stable, vérifié) ;
- parsing robuste des réponses Gemini (plusieurs `parts`, parties sans texte, prompt bloqué,
  candidat vide avec `finishReason`) ;
- message d'erreur actionnable en cas de 404, avec le modèle demandé et l'alternative
  `GEMINI_MODEL` ;
- test de connexion réel : **OK** ;
- briefing complet réel : **mode `llm`**, 2 002 caractères, fournisseur
  `Google Gemini · gemini-flash-lite-latest`.

---

## 3. Plan de restauration par lots

### Lot B — Interface et volatilité (priorité 1)

**Objectif :** supprimer les rendus bruts et sortir le VIX du régime marocain.

1. Créer `ui.html_block(markup)` : `textwrap.dedent(markup).strip()` + `st.markdown(..., unsafe_allow_html=True)`.
2. Remplacer les blocs HTML indentés restants dans `home.py`, `dashboard.py`,
   `fundamentals_page.py`, `sources_page.py` (les blocs sans texte dynamique sont sûrs,
   mais l'homogénéisation évite les récidives).
3. Créer `analytics/risk.py` :
   - `realized_volatility(series, window=60, periods=252)` ;
   - `masi_volatility(force=False)` à partir de `bvc.index_history("MASI")` ;
   - retourne `value`, `method`, `window`, `periods`, `as_of`, `source`, `observations`.
4. Brancher cette volatilité dans `scoring.market_regime()` à la place du VIX.
5. Mettre à jour l'accueil, le dashboard, les alertes, les prompts et le rapport.
6. Afficher la méthode : « écart-type des rendements quotidiens du MASI sur 60 séances,
   annualisé × √252, historique BVC au JJ/MM/AAAA ».
7. Si l'historique est insuffisant : afficher « indisponible », jamais une valeur inventée.

**Critères d'acceptation :**

- aucun `VIX` non étiqueté dans l'accueil ou le régime marocain ;
- la volatilité MASI affiche sa méthode, sa fenêtre et sa date ;
- 0 balise `<pre>` sur `/actualites`, `/societe` (onglet Actualités), `/alertes` ;
- tests : calcul de volatilité, historique insuffisant, composantes du régime.

### Lot C — États financiers et couverture (priorité 2)

**Objectif :** rendre les tableaux utiles pour les valeurs qui ont des documents officiels.

1. Retirer Yahoo de la liste des fournisseurs d'états **marocains** ; l'AMMC devient
   le chemin principal, EODHD/FMP restent optionnels si des clés existent.
2. Construire une matrice de couverture : 81 valeurs × exercices × source × statut.
3. Importer IAM 2023/2024 en priorité (Etisalat Maroc), puis ATW et CSR, depuis les
   PDF AMMC/BVC, avec URL, page, exercice, unité, devise et périmètre social/consolidé.
4. Ne jamais auto-valider une extraction : brouillon éditable + validation humaine.
5. Afficher un état vide utile : cause, document manquant, action.

**Critères d'acceptation :**

- IAM affiche au moins deux exercices avec des montants différents et sourcés ;
- un changement d'exercice change réellement les montants ;
- les rubriques répétées, unités et périmètres sont signalés ;
- les valeurs absentes restent « Non disponible », jamais 0.

### Lot D — Fondamentaux, ratios et valorisation (priorité 3)

1. Choisir par défaut une valeur couverte, ou afficher la couverture avant les tableaux.
2. Désactiver les étapes non calculables du parcours avec une raison explicite.
3. Afficher pour chaque ratio : formule, période, entrées, source.
4. Conserver les exclusions banques/assurances (EV/EBITDA, dette/EBITDA, etc.).
5. Ne proposer une valorisation que si tous les champs sont présents ; sinon lister les
   champs manquants et les méthodes alternatives.

**Critères d'acceptation :**

- aucun prix cible sans hypothèses explicites ;
- aucun ratio calculé sur des données incompatibles ;
- les étapes indisponibles sont désactivées, pas remplies de zéros.

### Lot E — IA, actualités et sentiment (priorité 4)

1. Ajouter un réessai court sur 503/429 et un repli explicite vers l'analyste local.
2. Structurer le briefing : faits observés, interprétation, incertitudes, sources, dates.
3. Pour les actualités : titre propre, résumé, source, date, lien, secteur.
4. Relier chaque article à un secteur avec une méthode traçable ; afficher le nombre
   d'articles et la période ; distinguer « aucun article » de « sentiment neutre ».
5. Ne jamais présenter une sortie IA comme une recommandation d'achat/vente.

### Lot F — Macroéconomie, portefeuille et finitions (priorité 5)

1. Macro : Bank Al-Maghrib, HCP, ministère de l'Économie et des Finances ; valeur, unité,
   période, date de publication, source, historique ; distinguer observation/estimation/prévision.
2. Portefeuille : relier positions, opérations, prix et dates ; signaler les cours périmés ;
   distinguer réel et théorique.
3. Design : densité Bloomberg/Investing.com, tableaux lisibles, filtres, fiches détaillées,
   sans cartes décoratives vides ; préserver l'identité marine/turquoise.

---

## 4. Tests exécutés pendant le Lot A

```text
python3 -m unittest discover -s tests -q
Ran 229 tests in 0.375s
OK (skipped=1)
```

- 6 nouveaux tests Gemini (`tests/test_llm_gemini.py`) : parsing multi-parts, partie sans
  texte, prompt bloqué, candidat vide, message 404 actionnable, modèle par défaut non retiré.
- Vérification navigateur : `/actualites` 0 `<pre>`, 47 cartes, aucun HTML brut.
- Vérification navigateur : `/societe` onglet Actualités, 0 `<pre>`.
- Test réel Gemini : connexion **OK**, briefing **mode `llm`**, 2 002 caractères.
- Test réel des données : TMA 18/19 ratios, MOX 16/19, IAM 1/19, ATW 1/19.

---

## 5. Limites et décisions à valider

1. **Yahoo Finance** : le retirer entièrement, ou le conserver uniquement dans un bloc
   « contexte international » (S&P 500, or, pétrole, EUR/USD) clairement séparé du marché
   marocain ? *Recommandation : le conserver uniquement dans ce bloc, jamais dans le régime
   ni dans les états financiers marocains.*
2. **Priorité d'import** : IAM d'abord, puis ATW et CSR ? Ou une autre liste ?
3. **Design** : conserver l'identité marine/turquoise et augmenter la densité
   (recommandé), ou créer une nouvelle identité visuelle ?
4. **Couverture** : les imports AMMC exigent une vérification humaine document par document ;
   aucun seed massif ne sera produit sans contrôle.

---

## 6. Ce que le Lot A n'a pas fait

- Aucune refonte graphique globale.
- Aucune suppression de fichier ou de fonctionnalité.
- Aucune donnée financière inventée ou complétée par l'IA.
- Aucun PDF auto-validé.
- Aucun changement de fournisseur non vérifié.
- Aucune modification des modules sans lien avec les régressions identifiées.
