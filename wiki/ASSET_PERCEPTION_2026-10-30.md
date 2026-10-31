# Perception et classification des fichiers — 30 octobre 2026

## Mission

Ouvrir un axe de classification des fichiers texte, images, vidéo, audio, 3D,
code et données géographiques pour proposer des tags de recherche et faciliter
le classement ultérieur. « Gaussian splatting » reste une interprétation
provisoire du terme oral reçu.

Base inspectée : `zedarvates/parcimonia/main`, commit
`83f40ebd715d09add32c45a73c44dc48e88a472a`, arbre
`b90f1c6e9043646a3b81b36a7f034ab87d19313b`.
Cette branche est indépendante des PR #20 et #21. Les travaux existants sur
les diagnostics, réductions et doublons ne sont pas considérés comme fusionnés.

## Réalisation

Le [guide](../docs/ASSET_PERCEPTION.md) décrit un premier socle déterministe :

- inspection d'octets complets ou d'un préfixe borné, identités et empreintes ;
- signatures et métadonnées PNG/GIF/JPEG, WAV PCM, FLAC/Ogg/ISO-BMFF, GLB/PLY ;
- texte UTF-8, JSON, déclaration glTF et indices lexicaux sur vocabulaire fourni ;
- réutilisation des rôles et règles Python présents sur la base ;
- GeoJSON avec coordonnées, ordre des axes, CRS et enveloppe recalculée ;
- tags uniquement proposés et sourcés, recherche exacte et par enveloppe spatiale ;
- CLI explicite et démonstration de sept assets construits en mémoire.

Les coordonnées x/y/z d'un PLY ne deviennent pas du GPS. Un en-tête PLY complet
peut proposer une représentation gaussienne candidate selon ses propriétés,
sans valider les valeurs ou rendre une scène. Un conteneur vidéo ne prouve pas
ses pistes. Aucun label sémantique d'image ou son n'est simulé.

Les copies Botte inspectées possèdent une mémoire de rapports de qualité et des
outils lexicaux/ingestion ; leur ancien chargeur multimédia contient aussi des
sorties simulées. L'observation concerne ces copies, pas une qualification du
plugin déployé. Ces sorties ne servent pas de perception réelle dans ce socle.

## Vérifications

Python 3.12.14 : **1 091 tests réussis**, dont les 809 tests de la base et
**282 nouveaux tests**. Commande : `PYTHONPATH=src python -m pytest -q`.
L'avertissement observé provient du plugin anyio de l'environnement.

Les nouveaux tests couvrent formats trompeurs, en-têtes tronqués/préfixes,
métadonnées invalides, coordonnées ambiguës ou contradictoires, schémas de
représentation PLY, code inspecté sans exécution, provenance, preuves connues,
recherche AND/bbox, bornes et refus de fichiers non réguliers ou modifiés.
Les pipes ASCII avec identifiants français sont exercés en sous-processus.

La démonstration JSON relue identifie sept formats et retrouve un asset pour
chacune des trois recherches illustrées : image, thème lexical et enveloppe.
Il s'agit de fixtures, pas d'un inventaire de fichiers personnels ni d'une
évaluation de reconnaissance sémantique.

La grammaire Python 3.10 des cinq modules et de l'exemple, les liens locaux de
la documentation modifiée et le contrôle des espaces passent.

## Revue et corrections

La revue indépendante a reproduit un faux tag de texte : le préfixe `robot`
pouvait être suivi de `ics!` dans le fichier complet. Le bord droit d'un préfixe
n'est plus pris comme une frontière de mot observée. Quatre régressions couvrent
préfixe coupé, séparation visible, fichier complet et caractère UTF-8 incomplet.

Le catalogue refuse désormais les incohérences CRS84 entre nombre de positions
et enveloppe, ainsi que les tailles d'échantillon dépassant le contrat du
producteur. La revue média a aussi corrigé la qualification d'indices flottants
de faces PLY et la distinction entre en-tête tronqué et non observé dans un
préfixe. Aucun défaut bloquant restant n'a été identifié dans ces revues bornées.

## Limites et reprise

Ce premier socle observe formats, déclarations et structures. Les tags sont des
propositions ; les indices lexicaux ne comprennent pas la négation ni le sens.
La recherche géographique donne des candidats d'intersection d'enveloppes,
sans reprojection, géocodage ou validation topologique générale.

OCR, transcription, reconnaissance visuelle ou sonore, rendu 3D, recherche
sémantique, acceptation/rejet persistant des tags et organisation physique
restent à qualifier. Aucun modèle, service, lecteur ou déplacement n'est lancé,
et aucune économie de tokens, de coût ou de durée n'est mesurée.

Les sources originales restent intactes. La prochaine étape est un petit corpus
réel autorisé, avec formats, labels attendus et cas réservés, puis la qualification
de chaque extracteur. La proposition reste en brouillon ; vérifier la CI du
commit proposé avant toute intégration ou activation.
