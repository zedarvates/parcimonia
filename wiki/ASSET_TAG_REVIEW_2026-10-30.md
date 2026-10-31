# Revue persistante des tags — 30 octobre 2026

## Mission et base

Poursuivre le catalogue multimodal en conservant les décisions sur les tags :
acceptation, rejet et retour à la revue, avec provenance et recherche par état.
Les propositions et fichiers analysés restent intacts.

Base inspectée : PR #22 de `zedarvates/parcimonia`, tête
`557c902945693e70f54d90efca070d8fc03fcad2`, arbre
`4087edf0796d6efbd23bdf47966eb7ccde51007c`. La PR était ouverte et en
brouillon ; elle n'est pas traitée comme fusionnée. Cette suite cible sa branche
pour montrer seulement les changements de revue des tags.

## Résultat

- Journal de décisions lié à la source, sa révision et au hash du rapport entier.
- États proposés/acceptés/rejetés, dernière décision applicable et reset conservé.
- Reprises idempotentes et tête attendue pour éviter un ajout sur un instantané périmé.
- Événements historiques non appliqués explicités quand le rapport ou la révision change.
- Recherche des tags acceptés par défaut, autres états explicitement demandés.
- Commandes CLI pour créer de nouveaux instantanés, revoir, projeter et rechercher.

Le [guide](../docs/ASSET_TAG_REVIEW.md) décrit contrats, commandes, bornes et
limites de confiance. Une acceptation est une déclaration enregistrée, pas une
preuve de vérité sémantique ou une permission d'exécution. Les tags de candidats
conservent leur valeur ; accepter un candidat ne renomme pas sa catégorie.

## Validation exécutée

Python 3.12.14 : **1 233 tests réussis**, soit les 1 091 tests de la base et
**142 nouveaux tests** : 76 pour le journal, 52 pour la projection/recherche,
14 pour les commandes et la persistance. Commande :
`PYTHONPATH=src python -m pytest -q`. L'avertissement observé provient du
plugin anyio de l'environnement.

Les tests couvrent les transitions, reprises d'un ancien accept après rejet,
modification de révision/rapport/préfixe, identifiants et hashes altérés, types
stricts, limites, mutations/alias, filtres d'états/bbox, Unicode et écritures
exclusives. Les fichiers existants, y compris journal et rapport d'entrée,
ne sont jamais écrasés par les commandes de revue.

La démonstration relue produit zéro résultat accepté avant revue, un après
acceptation, un tag rejeté avec le filtre explicite et zéro après reset. Elle
conserve trois événements dans l'historique et signale l'ancienne révision
comme non appliquée. Les déclarations sont des fixtures.

La grammaire Python 3.10 des modules modifiés et de l'exemple, les liens
documentaires et les espaces passent. La CI de la tête publiée doit être lue
séparément pour l'installation et l'exécution sous les autres versions.

## Revue et corrections

La revue indépendante a exécuté un oracle de transitions et de recherche sur
des journaux construits, sans faux héritage observé. Elle a identifié un défaut
de contrat entre écriture et lecture : un journal Unicode valide pouvait
dépasser 8 Mio après sérialisation, tout en étant annoncé créé. La taille UTF-8
est désormais contrôlée avant la création, avec une régression sur un journal
de 900 événements. Le fichier refusé n'est pas créé.

Une autre revue a reproduit des conversions Python vers JSON masquant un
changement : tuple vers liste, clés entières vers texte. Une validation commune
de JSON pur précède désormais le hash à l'ajout comme à la projection. Les
cycles, subclasses, types particuliers et nombres non finis sont refusés ; les
partages acycliques sont admis. La borne de 256 propositions est également
commune au producteur et au consommateur de décisions.

## Limites et reprise

La chaîne vérifie sa cohérence interne, sans signature des acteurs ou protection
contre une réécriture cohérente de tout l'historique. La tête attendue n'est pas
un verrou de stockage partagé. Les instantanés sont écrits exclusivement sur
de nouveaux chemins ; une interruption peut laisser un nouveau fichier incomplet,
que la lecture refuse, tout en conservant le journal d'entrée.

Aucun tag n'est approuvé automatiquement, aucun modèle n'est entraîné, aucun
fichier source n'est déplacé et aucune route ou plugin n'est activé. Les décisions
ne deviennent pas des labels étalons sans qualification supplémentaire. Il n'y a
pas de mesure de gain de tokens, de durée ou de coût.

La proposition reste en brouillon. Pour reprendre : vérifier la tête de #22 et
la CI de cette proposition, puis qualifier les corrections sur un petit corpus
réel autorisé avant de brancher des extracteurs sémantiques.
