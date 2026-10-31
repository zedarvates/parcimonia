# Relations similaires et complémentaires — 31 octobre 2026

Demande : commencer à appliquer aux projets le principe de séparation entre
similarité et complémentarité étudié par MAGE. Premier périmètre : Parcimonia,
catalogue existant, exemple d'architecture Ultimate Odycer. Base inspectée :
`e7a69ea3f4789f2ea96ec6e829a49882d5876325`.

## Comportement obtenu

Un fichier annexe fermé et versionné conserve des relations dirigées avec
références, révisions et localisateurs. Chaque extrémité est liée à la révision
et au hash exact de son rapport. Les recherches `similar` et `complementary`
restent distinctes. Les liens périmés sont signalés comme inapplicables ; une
incompatibilité courante de la même paire bloque sa proposition complémentaire.
Une incompatibilité isolée n'est pas une proposition et n'est pas listée comme
candidat bloqué. Les résultats ne certifient aucune compatibilité géométrique.

La CLI prépare explicitement un lot à une tête de catalogue attendue et écrit
un nouveau fichier, puis recherche dans les documents fournis. Le catalogue,
les assets et le journal de tags ne sont pas modifiés. Aucun modèle, service,
routeur actif ou moteur documentaire du PC n'est lancé.

Guide et contrats : [ASSET_RELATIONS.md](../docs/ASSET_RELATIONS.md).

## Preuves réellement exécutées

- Base : 3 574 tests et 34 sous-tests passent sur Python 3.12.14.
- Lot complet : **3 640 tests et 34 sous-tests passent**, dont 52 tests du cœur
  et 14 tests CLI. Durée de la suite finale : 31,03 s dans cet environnement.
- Revue indépendante et probes supplémentaires : ordre des déclarations,
  conflits, rapport modifié à révision constante, absence d'inverse et de
  transitivité, hashes altérés, types stricts et absence d'alias de sortie.
- Grammaire Python 3.10, liens relatifs de documentation et `git diff --check`
  vérifiés. La grammaire ne remplace pas une exécution sur Python 3.10.
- Démonstrateur réellement exécuté sur des textes authorés : une variante
  similaire, un toit complémentaire, un escalier bloqué ; changement de révision
  du toit → zéro complément courant ; requête inverse → zéro résultat.
  [Sortie conservée](ASSET_RELATIONS_DEMO_2026-10-31.json).

```bash
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python examples/asset_relations_demo.py
```

L'avertissement pytest du plugin `anyio` était déjà présent dans la base.
Les temps ci-dessus décrivent une suite logicielle locale, sans gain produit.

## Limites et reprise

Les relations restent `caller_declared` ; les preuves externes ne sont ni lues,
ni authentifiées, ni contrôlées en fraîcheur. Il n'y a ni score appris, ni
dédoublonnage sémantique, ni réseau MAGE entraîné. Source scientifique :
[préprint MAGE](https://arxiv.org/abs/2610.37409) et
[dépôt des auteurs](https://github.com/Alex-bupt/mage). La vidéo d'origine
`x4_Vu-jumW8` n'était accessible que par ses métadonnées ; les mécanismes
proviennent des sources primaires, pas de démonstrations vues ou entendues.

Prochaine épreuve : collecter 30 demandes métier, réserver 20 cas sans réglage,
comparer utilité des cinq premiers résultats, faux rapprochements, manques
retrouvés et durée. Les 30 demandes ne sont pas encore collectées. Le raccord
aux recettes et validateurs géométriques réels reste à réaliser. Aucune
activation ni fusion n'est effectuée par ce lot. Repli : utiliser le catalogue
et les recherches existants sans les deux nouvelles commandes.
