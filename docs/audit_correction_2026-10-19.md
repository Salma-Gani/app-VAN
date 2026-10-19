# Audit et correction — 19 octobre 2026

Document de traçabilité : ce qui bloquait, ce qui a été corrigé, ce qui est réellement
connecté et ce qui reste hors de portée sans licence ou sans clé.

## 1. Causes identifiées

| Symptôme | Cause réelle | Correctif |
|---|---|---|
| Carte thermique vide ou invisible | Le treemap utilisait `parents = secteur` **sans** créer les nœuds secteur, avec `branchvalues="total"` : Plotly ne rendait rien. | Nœuds secteur explicites, somme des capitalisations membres, couleurs par tuile. |
| Carte sans détails | Survol limité au cours et à la variation. | Survol : ticker, nom, secteur, cours, variation, volume, capitalisation. |
| Couleurs contradictoires sur les actualités | Un badge à 3 tons pour 5 niveaux de sentiment. | 5 classes CSS dédiées : vert (positif) → gris (neutre) → rouge (négatif), + liseré de couleur. |
| Dates ambiguës | Une seule date affichée, sans distinguer séance / publication / récupération. | Dates séparées : dernière séance, période comptable, publication de l'article, récupération du flux. |
| Erreurs fournisseurs opaques (401/500) | Messages bruts remontés à l'utilisateur, aucune classification. | Couche HTTP commune : classification, réessais ciblés, message utilisateur, journal sans secret. |
| VIX présenté comme volatilité marocaine | Aucune distinction S&P 500 / MASI. | VIX explicitement étiqueté « S&P 500 » + volatilité réalisée du MASI calculée séparément. |
| Fournisseurs « indisponibles » sans diagnostic | Aucun écran d'état des connecteurs. | Onglet « Sources » : catalogue des connecteurs + journal des derniers appels. |

## 2. Ce qui est réellement connecté

- **Bourse de Casablanca** — API publique Boursenova : cours, OHLC, volumes, capitalisation,
  indices et composition (`MASI`, `MSI20`). Cours différés, cache 15 min.
- **AMMC** — pages publiques et PDF d'états financiers. Ce n'est **pas** une API : vérification
  humaine requise.
- **World Bank Open Data** — séries macro annuelles (PIB, inflation, chômage).
- **Flux RSS publics** — presse marocaine et internationale, avec date de publication et de
  récupération distinctes.
- **Yahoo Finance (yfinance)** — contexte international (indices, VIX, devises, matières premières).

## 3. Ce qui n'est pas connecté (et pourquoi)

- **Bloomberg Data License**, **LSEG / Reuters** : accès payant, licence requise, redistribution
  encadrée. Aucune clé fournie → non branché.
- **Investing.com** : pas d'API publique directe ; seuls des widgets sont proposés. Aucune
  intégration n'a été fabriquée.
- **Bank Al-Maghrib / HCP** : taux directeur et séries trimestrielles non connectés.
- **EODHD / FMP** : nécessitent une clé (`EODHD_API_KEY`, `FMP_API_KEY`) ; couverture marocaine
  non vérifiée sans clé.
- **Moteur LLM** : nécessite une clé de fournisseur ; sinon l'analyste local déterministe répond
  à partir des données chargées, sans jamais simuler une réponse d'IA.

Aucun scraping interdit, aucune donnée inventée : une valeur absente reste « Non disponible ».

## 4. Politique d'erreurs HTTP

| Statut | Comportement |
|---|---|
| 401 | Réessai stoppé, message « clé ou authentification à vérifier », aucune donnée de remplacement. |
| 403 | Réessai stoppé, droits ou abonnement signalés. |
| 404 | Réessai stoppé, identifiant/URL vérifiés. |
| 429 | Réessais avec délai exponentiel, puis message « réessayez plus tard ». |
| 5xx | Réessais bornés, repli explicite sur la copie datée du cache. |
| Délai / réseau | Réessais bornés, état « indisponible » affiché. |
| 200 vide | « Aucune donnée pour cette requête » — pas de zéro inventé. |
| JSON illisible | « Réponse illisible » — jamais remplacée par une valeur simulée. |

Les clés, jetons et corps de réponse bruts ne sont jamais affichés ni journalisés ; les URLs sont
expurgées avant enregistrement du diagnostic.

## 5. Tests

- `tests/test_http.py` — 401/403/404/429/500, délai, réseau, réponse vide, JSON illisible,
  non-répétition des 401, réessai des 429/5xx, expurgation des secrets.
- `tests/test_market_map.py` — structure du treemap, somme secteur = somme membres, gris pour
  donnée manquante, classes de couleur des 5 niveaux de sentiment, horodatage UTC.
- Suite complète : `python3 -m unittest discover -s tests -q` (117 tests).
- 17 pages rendues sans exception via `streamlit.testing.v1.AppTest`.

## 6. Limites restantes

- Le scénario « date de référence » dépend des sources : la dernière séance BVC publiée peut
  précéder la date du jour.
- Les états financiers ne sont couverts que pour les sociétés dont les rapports sont vérifiés
  (TMA, MOX) ; l'ajout se fait société par société, avec import CSV validé.
- La couverture EODHD/FMP des valeurs marocaines reste à confirmer avec une clé réelle.
