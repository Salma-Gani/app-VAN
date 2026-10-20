# Lot B — États AMMC, capitaux propres part du groupe et ratios sectoriels

Date : 20/10/2026 · Version : 3.8.2

## Objectif

Rendre la comparaison sectorielle réellement exploitable, en particulier pour les banques,
et corriger les ratios calculés sur des capitaux propres incluant les intérêts minoritaires.

## Causes identifiées

1. **Capitaux propres totaux au lieu de la part du groupe.** Les enregistrements IAM, ATW et
   CSR utilisaient le total des capitaux propres (minoritaires inclus), alors que le résultat
   net retenu était la part du groupe. Le ROE et le P/B étaient donc sous-estimés.
   - IAM 2024 : total 18 702 M MAD, part du groupe 14 908 M MAD.
   - ATW 2024 : total 72 503 M MAD, part du groupe 62 456 M MAD.
   - CSR 2024 : total 5 885,6 M MAD, part du groupe 5 878,5 M MAD.
2. **Couverture bancaire insuffisante.** Le secteur Banques ne comptait qu'ATW avec des ratios.
   BCP et BOA n'avaient pas d'états vérifiés dans le seed.
3. **Ratios non pertinents encore calculés dans la page États financiers.** La couverture des
   intérêts, la liquidité générale, le levier et le FCF/CA restaient calculés pour les banques
   alors qu'ils sont exclus de la comparaison sectorielle.
4. **Unité du document non exposée.** Les PDF AMMC sont exprimés en millions ou milliers de MAD,
   mais l'interface indiquait seulement « unité source : MAD ».
5. **Rendement du dividende ambigu.** Le DPA du référentiel BVC peut concerner un exercice
   postérieur à l'exercice comptable affiché.
6. **Graphique de multiples peu lisible.** P/E, P/B et rendement étaient tracés sur le même axe,
   avec des unités différentes.
7. **VIX encore susceptible d'être confondu avec la volatilité marocaine** sur l'accueil et
   dans les alertes.

## Correctifs

- Seed : ajout de BCP 2024/2023 et BOA 2024/2023 (comptes consolidés IFRS, AMMC).
  - BCP : bilan p. 30, compte de résultat p. 31.
  - BOA : bilan et compte de résultat p. 96, résultat par action p. 111.
- Seed : `balance.equity` pointe désormais sur la **part du groupe** pour IAM, ATW, CSR, BCP et BOA.
  Les lignes détaillées conservent le total, la part du groupe et les intérêts minoritaires.
- Seed : ajout de `source_unit` (`millions MAD`, `milliers MAD` ou `MAD`). L'interface affiche
  l'unité du document et précise que les valeurs sont converties en MAD.
- États financiers : libellé « Produit net bancaire » et « part du groupe » pour les banques.
- États financiers : les ratios non pertinents pour les banques/assurances sont marqués
  « Non pertinent » avec une raison explicite.
- Parcours : graphique des écarts à la médiane en %, unité homogène, au lieu de barres de
  multiples et de rendements sur le même axe.
- Parcours : formules et statuts repliés dans un panneau lisible ; mention explicite de la
  part du groupe et de l'exercice du DPA.
- Secteur : le détail société affiche l'unité du document, la part du groupe et les champs
  saisis par l'utilisateur.
- Accueil / alertes : libellés « VIX S&P 500 » et rappel qu'il ne mesure pas le MASI.
- Conformité éditoriale : les textes de régime de marché ne donnent plus de consignes
  (« réduisez », « privilégiez », « n'entrez pas »). L'agent IA ne produit plus de
  « verdict Achat / Éviter » ni de « plan d'exécution » (entrée, stop, objectif, taille de
  position) : il fournit une lecture d'ensemble, ce qui la soutient, ce qui la contredit,
  les données manquantes et les niveaux observés.

## Vérifications

- `python3 -m unittest discover -s tests -q` : **248 tests OK** (1 ignoré), dont
  `tests/test_ai_advice.py` pour l'absence de libellés « Achat / Éviter » et de plan d'exécution.
- `record_issues` : aucun problème pour IAM, ATW, CSR, BCP et BOA (2022-2024).
- Banques : 3 sociétés avec ratios (ATW, BCP, BOA).
  - P/E médian : 12,01x.
  - P/B médian : 1,34x.
  - ROE médian : 11,8 %.
- IAM 2024 : ROE 12,1 %, P/B 5,20x, P/E 43,0x (résultat net 2024 faible, contexte à vérifier).
- ATW 2024 : ROE 15,2 %, P/B 2,31x, P/E 15,2x.
- CSR 2024 : ROE 14,5 %, P/B 2,81x, P/E 19,4x.
- BCP 2024 : ROE 11,2 %, P/B 1,34x, P/E 12,0x.
- BOA 2024 : ROE 11,8 %, P/B 1,33x, P/E 11,3x.
- Routes vérifiées : `/secteurs` (Banques par défaut), `/parcours` (étapes 1 à 4),
  `/etats-financiers` (AMMC en premier, unités, part du groupe).

## Limites

- Couverture : 7 émetteurs sur 81 valeurs. Les 74 autres n'ont pas d'états vérifiés.
- L'extraction AMMC reste une aide à la saisie : validation humaine obligatoire.
- Les overrides manuels d'EBITDA pour IAM et ATW restent non rattachés à un document ; l'UI
  les signale. Pour ATW, l'EBITDA n'est pas utilisé dans les ratios bancaires.
- Le DPA BVC peut être postérieur à l'exercice comptable ; le libellé le précise désormais.
- Pas d'OCR pour les PDF scannés.
- Authentification locale mono-utilisateur ; pas de comptes multiples.
- Les données de marché restent différées et dépendantes de l'API BVC.

## Prochaines étapes

1. Importer d'autres émetteurs AMMC pour élargir les secteurs (banques, assurances, industrie).
2. Vérifier ou supprimer les overrides manuels d'EBITDA.
3. Ajouter un contrôle automatique « total vs part du groupe » dans l'extraction.
4. Documenter la rotation de la clé Gemini et la révocation de l'ancien jeton GitHub.
