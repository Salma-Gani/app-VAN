# Cas vérifiable — TotalEnergies Marketing Maroc (TMA)

Ce document sert de **preuve méthodologique** : chaque chiffre peut être recalculé à la main
à partir des états financiers publiés. Il illustre le parcours *Comprendre → Analyser →
Valoriser → Surveiller → Relier au portefeuille* sur une société réellement cotée à la
Bourse de Casablanca.

---

## 1. Source des données (traçable)

| Élément | Valeur |
|---|---|
| Société | TotalEnergies Marketing Maroc (TMA) |
| Document | Rapport financier annuel 2024 (comptes consolidés) |
| Source | AMMC — `https://www.ammc.ma/sites/default/files/Total_RFA_2024_0.pdf` |
| Exercice | 2024 (comparable 2023) |
| Devise / unité | MAD / unités |
| Nombre d'actions | 8 960 000 |
| Statut | `official` (extrait ligne à ligne, vérifié) |

Extraits clés (MAD) :

| Ligne | 2024 | 2023 |
|---|---:|---:|
| Chiffre d'affaires | 18 348 026 022,08 | 17 984 198 998,17 |
| Résultat d'exploitation | 1 332 671 876,68 | 929 808 736,67 |
| EBITDA | 1 649 117 943,79 | 1 241 889 210,05 |
| Résultat net | 844 618 182,50 | 58 746 379,71 |
| Capitaux propres | 2 595 923 623,32 | 2 253 065 440,82 |
| Dette financière totale | 697 106 199,43 | 737 390 238,56 |
| Trésorerie | 1 402 976 634,40 | 1 284 726 913,54 |

Ces montants sont stockés dans `data/seed/bvc_statements.json` et exposés dans la page
**États financiers** (onglets Compte de résultat / Bilan / Trésorerie).

---

## 2. Valorisation vérifiable à la main (méthode PER cible × BPA)

**Bénéfice par action (BPA)**
`BPA = Résultat net / Nombre d'actions = 844 618 182,50 / 8 960 000 = 94,2654 MAD`

**Prix théorique pour un PER cible de 12×**
`Prix = 12 × 94,2654 = 1 131,19 MAD`

**Prix d'entrée avec une marge de sécurité de 20 %**
`Entrée = 1 131,19 × (1 − 0,20) = 904,95 MAD`

Ces trois résultats sont produits par le **Valuation Lab** (méthode « PER cible »), avec
la marge de sécurité saisie par l'utilisateur. Ils ne dépendent que des deux données
publiées ci-dessus.

---

## 3. Deuxième méthode (EV/EBITDA) — calcul détaillé

Cours utilisé pour l'exemple : **1 345 MAD** (clôture du 16/10/2026).

- Capitalisation = `8 960 000 × 1 345 = 12 051 200 000 MAD`
- Dette nette = dette − trésorerie = `697 106 199,43 − 1 402 976 634,40 = −705 870 434,97 MAD`
  (position de trésorerie nette)
- Valeur d'entreprise (EV) actuelle = `12 051 200 000 − 705 870 434,97 = 11 345 329 565,03 MAD`
- Pour un multiple cible de **8× EBITDA** : `EV cible = 8 × 1 649 117 943,79 = 13 192 943 550,32 MAD`
- Valeur des fonds propres = `13 192 943 550,32 − (−705 870 434,97) = 13 898 813 985,29 MAD`
- Par action = `13 898 813 985,29 / 8 960 000 = 1 551,21 MAD`

Le module renvoie bien **1 551,21 MAD** pour ces paramètres, avant application de la
marge de sécurité.

> Limite méthodologique : au 31/12/2024, la dette nette est négative. EV/EBITDA reste
> calculable ici, mais un multiple d'EV n'a de sens que si l'EBITDA est positif et si la
> structure de bilan est comparable à celle des pairs — ce qui n'est **pas** le cas entre une
> banque et une entreprise industrielle. Le module ne mélange donc pas ces secteurs.

---

## 4. Comparaison de scénarios (DCF)

La page **Valorisation & prévisions** propose en plus :

- un **DCF** explicite (croissance, marge, taux d'actualisation, valeur terminale) ;
- un tableau de **sensibilité** (taux × croissance) ;
- des **scénarios** défavorable / central / favorable ;
- une **distribution Monte-Carlo** (P5–P25–P50–P75–P95) des valeurs intrinsèques.

Toutes les hypothèses sont affichées et **modifiables** ; aucune valeur cachée n'est injectée.

---

## 5. Simulation de trajectoires de prix (Monte-Carlo)

Sur l'historique réel des cours, l'application calcule un mouvement brownien géométrique :

- dérive et volatilité **annualisées, estimées sur l'historique** (ou saisies) ;
- un graphique de **trajectoires simulées** avec bandes **P5–P25–P50–P75–P95** ;
- la **distribution des prix finaux** et la **probabilité de finir au-dessus du cours initial** ;
- la **graine** (seed) est exposée : la simulation est reproductible.

Le modèle et ses limites (indépendance des rendements, volatilité constante) sont affichés.

---

## 6. Apport de l'IA, sans invention

L'agent IA produit une synthèse **uniquement à partir des données fournies** (cours, ratios,
signaux, actualités sourcées). Il ne cite jamais un chiffre absent des données et n'émet pas
de recommandation d'achat/vente. En l'absence de clé API, un analyseur local déterministe
prend le relais.

---

## 7. Limites et connecteurs encore nécessaires

- **Couverture comptable** : seules les sociétés dont les états sont saisis/importés
  disposent de ratios. Connecteurs EODHD / FMP disponibles (clé requise) ; couverture
  marocaine par ces fournisseurs **non vérifiée**. Yahoo Finance ne fournit **pas** d'états
  financiers marocains.
- **Macro** : Maroc via la Banque mondiale ; BAM/HCP non connectés (pas d'API publique ouverte
  documentée).
- **Actualités** : flux RSS publics ; sentiment et impact sont **heuristiques**.
- **Backtest** : illustratif (historique court, hors fiscalité et liquidité réelle).
- Aucune donnée n'est inventée : un champ manquant reste « non disponible ».
