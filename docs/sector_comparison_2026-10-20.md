# Comparaison sectorielle — 20 octobre 2026

## Objectif

Ajouter une comparaison sectorielle **rigoureuse et traçable** entre les valeurs
de la Bourse de Casablanca, sans dupliquer les modules existants et sans jamais
remplacer une donnée absente par zéro.

La page est accessible dans **3 · Entreprises → Comparaison sectorielle**
(`/secteurs`). Elle s'appuie sur le snapshot de marché déjà utilisé par le
screener, afin de garantir la cohérence des cours, capitalisations et
performances affichés ailleurs dans l'application.

## Ce qui a été livré

### Moteur `ecoinvest/analytics/sector_compare.py`

- **13 métriques** réparties en deux familles :
  - *marché* : capitalisation, cours, performance 12 mois, volatilité
    annualisée, drawdown maximal, rendement du dividende ;
  - *états financiers* : P/E, P/B, EV/EBITDA, ROE, marge nette,
    dette/fonds propres, croissance du chiffre d'affaires.
- **Médianes non pondérées**, calculées uniquement sur les valeurs réellement
  disponibles, avec le nombre de valeurs utilisées (`count` / `total`).
- **Rang relatif 0–100** par société, en tenant compte du sens de chaque
  métrique (P/E bas = meilleur, ROE haut = meilleur, etc.).
- **Synthèse par secteur** : nombre de valeurs, capitalisation médiane,
  performance médiane, volatilité médiane, rendement médian, P/E médian,
  ROE médian et nombre de valeurs disposant de ratios.
- **Notes de comparabilité** : exercices différents, mélange comptes sociaux /
  consolidés, absence d'états vérifiés, secteur financier.
- **Aucune valeur inventée** : les données absentes restent `NaN` / `None` et
  sont affichées « — ».

### Interface `ecoinvest/ui/pages/sector_page.py`

- Sélecteur de secteur annoté avec la couverture réelle :
  `Chimie — 2 valeur(s) · 1 avec ratios`.
- Cinq indicateurs clés : sociétés, capitalisation médiane, P/E médian,
  ROE médian, rendement médian — chacun avec le nombre de valeurs utilisées.
- Quatre onglets :
  1. **Tableau comparatif** : marché, fondamentaux, ligne « Médiane du
     secteur », détail par société (valeur, rang, formule, statut, exercice,
     source) ;
  2. **Risque / rendement** : nuage volatilité × performance 12 mois, taille =
     capitalisation, couleur = présence de données fondamentales ;
  3. **Tous les secteurs** : tableau de synthèse et graphique comparatif
     (performance, P/E, ROE ou volatilité) ;
  4. **Méthode & sources** : formules, conventions, limites.
- État vide explicite lorsqu'aucun ratio n'est calculable, avec la cause et
  l'action à effectuer (importer les états dans « États financiers »).

### Corrections de rigueur apportées au passage

1. **EV/EBITDA calculé pour une banque** : la banque ATW apparaissait avec un
   EV/EBITDA de 9,57 ×. `compute_ratios` neutralise désormais, pour les banques,
   assurances et sociétés de financement, les multiples d'entreprise
   (`ev_ebitda`, `ev_sales`, `net_debt_to_ebitda`) et le levier
   (`debt_to_equity`, `current_ratio`, `interest_coverage`).
2. **Zéro de remplissage** : la dette et la trésorerie manquantes étaient
   assimilées à `0`, ce qui produisait un EV et un levier artificiels.
   Désormais, l'EV n'est calculé que si la dette **et** la trésorerie sont
   connues ; une dette déclarée à `0` reste traitée comme un vrai zéro.
3. **Cohérence des colonnes de synthèse** : le graphique « Tous les secteurs »
   utilisait des clés anglaises alors que la synthèse expose des libellés
   français ; corrigé et couvert par un test.

## Sources et statuts

| Donnée | Source | Statut |
|---|---|---|
| Cours, capitalisation, volumes | Bourse de Casablanca (snapshot) | observé |
| Performance, volatilité, drawdown | historique de cours réel | calculé |
| DPA / rendement | référentiel BVC ou états | déclaré / calculé |
| P/E, P/B, ROE, marges, levier, croissance | référentiel BVC ou états vérifiés | calculé, si données compatibles |
| Exercice, périmètre, source | magasin d'états vérifiés | déclaré |

Une société peut donc avoir des **métriques de marché** sans aucun ratio
fondamental. C'est le cas de la majorité des 81 valeurs : seuls TMA, MOX et
quelques fiches BVC disposent de données fondamentales exploitables.

## Formules

- **P/E** = capitalisation / résultat net (ou cours / BPA). Non calculé si le
  résultat est négatif.
- **P/B** = capitalisation / fonds propres.
- **EV/EBITDA** = (capitalisation + dette nette) / EBITDA. Dette nette =
  dette financière − trésorerie ; non calculé si l'une des deux manque.
- **ROE** = résultat net / fonds propres.
- **Marge nette** = résultat net / chiffre d'affaires.
- **Dette / fonds propres** = dette financière / fonds propres.
- **Croissance du CA** = (CA N − CA N−1) / CA N−1.
- **Rendement du dividende** = DPA / cours.
- **Volatilité** = écart-type des rendements quotidiens × √252.
- **Performance 12 mois** = variation du cours sur 12 mois glissants.

## Tests

- `tests/test_sector_compare.py` : **22 tests**
  - détection des secteurs financiers ;
  - exclusion d'EV/EBITDA et du levier pour les banques/assurances ;
  - absence de zéro de remplissage ;
  - médianes et comptages ;
  - synthèse par secteur ;
  - rangs (haut/bas, valeurs uniques, manquantes) ;
  - notes de comparabilité ;
  - cohérence des colonnes du graphique de synthèse.
- `tests/test_ratios.py` : **3 tests ajoutés**
  - exclusion des multiples d'entreprise pour un secteur financier ;
  - dette/trésorerie manquantes ⇒ EV et levier indisponibles ;
  - dette déclarée à zéro ⇒ EV et levier calculés.

Suite complète : `python3 -m unittest discover -s tests -q`.

## Limites assumées

- **Couverture fondamentale partielle** : le référentiel BVC ne fournit pas,
  pour la plupart des valeurs, le résultat net et les fonds propres. Les ratios
  restent « — » tant que les états financiers ne sont pas importés et validés.
  Les banques, en particulier, n'ont ni résultat net ni fonds propres dans le
  référentiel : P/E et ROE y sont indisponibles.
- **Classification sectorielle** : elle provient de la BVC et n'est pas
  recalculée. Les conglomérats peuvent relever de plusieurs secteurs.
- **Médianes non pondérées** : une petite capitalisation pèse autant qu'une
  grande. C'est un choix explicite, adapté à une comparaison de valorisation.
- **Pas de prévision** : aucune performance future n'est estimée. Les
  graphiques décrivent uniquement l'historique observé.
- **Pas d'agrégation comptable** : les ratios ne sont jamais reconstruits à
  partir de rubriques de natures différentes ; ils utilisent les champs
  normalisés du magasin d'états.

## Fichiers concernés

- `ecoinvest/analytics/sector_compare.py` (nouveau)
- `ecoinvest/ui/pages/sector_page.py` (nouveau)
- `ecoinvest/data/fundamentals.py` (neutralisation financière, EV honnête)
- `ecoinvest/analytics/scoring.py` (transmission du secteur)
- `app.py` (navigation)
- `tests/test_sector_compare.py` (nouveau)
- `tests/test_ratios.py`
- `ecoinvest/config.py` (version 3.8.0)
