# Vérification — attentes explicites sur les assets — 2026-10-31

Objectif : détecter des écarts par rapport à des attentes choisies, en
distinguant contradiction, information inconnue et rapport manquant.
Proposition empilée sur la PR #29, tête
`fc9ac7402db26ad2b88f516a73360ebbfb81a4ac`, sans fusion ni activation.

## Comportement obtenu

Un contrat fermé `parcimonia.asset-expectations/v1` désigne les sources par leur
paire exacte ID/révision et liste les contrôles. L'API pure
`audit_asset_expectations` compare une liste explicite de faits aux rapports
fournis, sans lire les sources. Elle réutilise la validation JSON, les limites
de taille, les empreintes et les contrats des rapports existants.

L'audit possède un schéma distinct ; il n'ajoute aucun champ aux rapports
d'inspection. Chaque résultat conserve toutes les comparaisons, leurs valeurs,
leurs bases et leurs chemins dans le rapport, ainsi que les références de
preuves disponibles. Le hash d'entrée lie tous les rapports fournis, leur
ordre, le contrat complet et l'identité versionnée de l'analyseur.

La CLI `audit-expectations` prend soit un tableau de rapports, soit un snapshot
avec `--catalog`. Dans ce dernier cas, une enveloppe distincte lie aussi la
génération et le hash exact du catalogue. Le code 0 signifie audit produit,
même en présence d'écarts ; une erreur de contrat, lecture ou budget donne le
code 2 et aucun JSON partiel sur stdout. Les entrées ne sont pas réécrites.

## Critères et validation locale

**2 487 tests passent sur Python 3.12.14**, sans test ignoré : les 2 378 tests
de la base et **109 nouveaux cas**, répartis en 96 pour l'API et ses frontières
et 13 pour la démonstration, la CLI et les snapshots. Un avertissement de
dépréciation provient du plugin pytest `anyio` installé, sans échec.

Critères exercés :

- Une valeur zéro observée peut contredire une exigence positive ; un corps
  PLY refusé ne devient pas un compte zéro. Une valeur absente ou `null` reste
  inconnue. Les coordonnées locales ne deviennent pas un CRS géographique.
- Les seuils entiers sont inclusifs et strictement typés. Pas de coercition
  booléen/entier/flottant/texte, de conversion d'unités ou de chemin arbitraire.
- Une proposition présente conserve ses bases, y compris un simple indice
  d'extension. Une proposition absente ne produit pas de négation du contenu.
- Une autre révision ou un même nom de fichier ne remplace pas la source
  demandée. Les identités dupliquées et métadonnées sélectionnées ambiguës
  sont des erreurs. Tous les rapports, même non sélectionnés, sont validés.
- Les formats image/audio/PLY/GeoJSON traversent leurs vrais producteurs puis
  le consommateur d'attentes. Les références de métadonnées sont résolues et
  les chemins de valeurs vérifiés dans les rapports produits.
- Une contradiction et une inconnue restent toutes deux visibles. La synthèse
  privilégie la contradiction sans effacer les contrôles inconnus.
- Modifier le contrat, un rapport ou même un rapport non sélectionné change
  l'empreinte globale. Les retours sont indépendants des entrées et se
  sérialisent en JSON strict. Les appels de fichier/processus/réseau sont
  interdits dans le test de l'API pure.
- La CLI réelle et son exemple sont exécutés. Le parcours sauvegarde un
  catalogue, audite ses trois rapports, remplace une révision puis vérifie
  que l'ancien snapshot reproduit exactement son audit et reste inchangé.
- JSON à clés dupliquées, schémas étrangers, liens, entrées manquantes,
  snapshot corrompu, faute tardive et budgets dépassés sont refusés sans
  sortie partielle. Les plafonds d'assets et de contrôles sont vérifiés.

Le profil borne aussi chaque preuve sélectionnée à 16 KiB avant de l'ajouter
aux résultats, pour limiter la répétition de grosses propositions entre les
contrôles. Un rapport acceptable par le catalogue peut donc dépasser le budget
de preuve d'une sélection particulière ; l'audit échoue explicitement, sans
tronquer la justification. La sortie complète et stdout ont aussi leur plafond.

## Démonstration conservée

Les [fixtures et résultats](ASSET_EXPECTATIONS_DEMO_2026-10-31.json) se
reproduisent à l'identique après sérialisation et relecture :

| Source attendue | Attente | Résultat |
| --- | --- | --- |
| Image fabriquée, PNG 1×1 | Format PNG et largeur au moins 1 | `satisfied` |
| Nuage PLY fabriqué, trois sommets et zéro face | Au moins une face observée | `contradicted` |
| Note fabriquée, sans classificateur de scène | Proposition `topic:forest` | `unknown` |
| Source sonore non fournie dans les rapports | Rapport complet de révision v1 | `missing_report` |

Il ne s'agit pas d'un inventaire personnel ou d'une livraison réelle. Aucun
contenu utilisateur n'a été inspecté, aucun modèle ni rendu n'a été exécuté.
La source sonore pourrait exister ailleurs : l'exemple prouve seulement
l'absence de son rapport dans le tableau fourni.

## Reproduction et limites

```bash
PYTHONPATH=src python -m examples.asset_expectations_demo --summary
PYTHONPATH=src python -m pytest -q
```

Guide : [ASSET_EXPECTATIONS.md](../docs/ASSET_EXPECTATIONS.md). La grammaire
Python 3.10, les liens locaux modifiés et les espaces du patch sont vérifiés.

Ce premier profil utilise les faits listés dans le guide : formats, échantillon,
dimensions, quelques champs audio/PLY/géographiques et présence de propositions.
Il n'applique pas le journal de revue et ne certifie pas l'authenticité des
rapports. Il ne rejoue pas les lecteurs ou leurs preuves sur les fichiers.
Une attente satisfaite ne signifie ni qualité globale, ni livraison exhaustive,
ni absence de bugs. Les propriétés non demandées restent hors audit.

Pas de solveur général d'impossibilité, de diagnostic de stabilité, de
reconnaissance sémantique ou de correction automatique. Aucun déplacement,
reclassement, acceptation de tag ou gain de coût/vitesse n'est annoncé.
Les plafonds sont des limites de profil, pas des garanties absolues de durée
ou mémoire. Repli : conserver les rapports et omettre la nouvelle commande.
