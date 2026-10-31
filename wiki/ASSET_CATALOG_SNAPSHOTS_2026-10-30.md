# Vérification — catalogue sauvegardé — 2026-10-30

Objectif : rendre les rapports de perception/classification reprenables dans un
catalogue portable, avec sélection courante par source et recherche avec revue.
Cette proposition est empilée sur la PR #24, tête
`e1f4a82dc77e35242f3622243973cfe42259f11a`, sans fusion ni activation.

## Réalisation

- Un snapshot JSON versionné, fermé et haché : génération, parent déclaré et
  rapports complets triés par identité de source.
- Fonctions pures d'insertion, remplacement, retrait et export, avec tête attendue,
  hash du rapport remplacé et copies indépendantes. Une révision reste opaque.
- Cinq commandes CLI : initialiser, ajouter/remplacer, retirer, exporter et
  rechercher avec un journal explicite. Les fichiers de sortie sont nouveaux et
  créés exclusivement. Les sources et journaux restent inchangés.
- Les rapports et états de revue existants sont réutilisés, notamment les rapports
  enrichis OCR/PDF ; les contrats des anciennes commandes restent inchangés.

## Vérification locale

**1 725 tests passent sur Python 3.12.14**, dont les 1 571 tests de la base et
154 nouveaux : 91 cœur de snapshots, 63 CLI/persistance. Les deux intégrations
natives héritées ont réellement tourné ici. L'avertissement pytest provient du
plugin `anyio` de l'environnement, sans échec de test.

Les tests vérifient notamment :

- préconditions de tête et de rapport, réessai exact sans nouvelle génération,
  rejet d'un réessai avec tête périmée et isolation par copies profondes ;
- source unique et ordre stable, révisions opaques, retrait et réimport exact ;
- conservation des acceptations des rapports inchangés et absence de transfert
  à un rapport changé, avec reprise de l'ancien état à partir de l'ancien fichier ;
- JSON exact sans coercition, cycles, NaN, booléens de génération, hachages,
  champs fermés et fichiers/liens existants protégés contre l'écrasement ;
- bornes exactes de 256 rapports, 2 MiB par rapport, 16 MiB par snapshot,
  200 000 nœuds et profondeur totale 64, avec aller-retour JSON aux limites.

La revue indépendante a comparé 500 mutations à un modèle simple et contrôlé
les limites avec le lecteur existant. Un défaut a été reproduit puis corrigé :
six rapports Unicode représentant environ 9 MiB en UTF-8 pouvaient dépasser
16 MiB après échappement ASCII sur stdout. `catalog-export --out` écrit désormais
une liste UTF-8 compacte et relisible ; l'export stdout refuse avant impression
si sa taille réelle dépasse le budget. Les tests relisent l'export avec `search`
et `search-reviewed`, sans modifier leur contrat.

Le démonstrateur a réellement écrit et relu cinq fichiers temporaires : génération
zéro, deux insertions, remplacement d'une révision et retrait d'une entrée.
Acceptation initiale : 1 résultat ; nouvelle révision acceptée : 0 ; proposée : 1.
L'acceptation de la carte inchangée reste applicable. Le point géographique passe
de 1 à 0 résultat après retrait ; l'ancien snapshot et le journal sont inchangés.

Un [rejeu des rapports natifs sauvegardés](ASSET_CATALOG_NATIVE_REPORT_REPLAY_2026-10-30.json)
de fixtures Tesseract/PDF a aussi été persisté et relu. Les deux rapports partagent
volontairement la même identité/révision de démonstration ; remplacer exactement
l'OCR par le PDF exige le hash de l'OCR et ne transfère pas son acceptation.
L'export reproduit exactement le rapport PDF sélectionné. Ce rejeu ne relance
aucun outil natif et ne qualifie pas leur qualité.

## Reproduction et limites

```bash
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python examples/asset_catalog_snapshot_demo.py
```

Guide : [ASSET_CATALOG_SNAPSHOTS.md](../docs/ASSET_CATALOG_SNAPSHOTS.md).
Le catalogue n'est pas une base de données ni un index accéléré. Pas de scanner,
de dédoublonnage de fichiers, de nouvelle perception, de reclassement physique
ou de gain de performance mesuré. Les décisions restent déclarées et les rapports
fournis ne sont pas authentifiés. Les liens de hash assurent une cohérence locale,
sans vérification récursive de l'historique, pointeur global, verrou distribué ou
protection contre une réécriture cohérente. Une interruption d'écriture peut
laisser un nouveau fichier partiel ; l'entrée précédente reste disponible.

Repli : continuer à utiliser les tableaux de rapports et commandes de recherche
existants, sans appeler les nouvelles fonctions. Aucune activation automatique.
