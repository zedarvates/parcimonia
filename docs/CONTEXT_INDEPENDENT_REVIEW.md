# Revue indépendante : dossier et provenance retrouvée

État du 7 octobre 2026. Le dossier de 120 demandes possède désormais une
provenance exacte pour chaque cas : **141 occurrences, 98 conversations et
89 composantes de source**. Les annotations réelles restent vierges.

## Provenance et limites

La récupération a d’abord utilisé l’index des messages utilisateur de
`thread_history_1.sqlite`, en lecture seule et avant la date de constitution du
corpus. Cela a retrouvé 116 cas, avec 134 occurrences. Les quatre autres cas ont
été retrouvés dans sept lignes de fichiers JSONL anciens.

La correspondance reprend le nettoyage du corpus : retrait de l’enveloppe du
harness, normalisation des espaces, masquage puis comparaison exacte en
minuscules. Aucun titre de conversation ou score de similarité n’établit une
correspondance. Les demandes trop longues, timestamps inconnus et occurrences
postérieures au corpus ne servent pas à établir cette provenance.

L’exploration initiale de repli a parcouru 786 fichiers anciens, environ 6,34 Go.
Elle a été plus large que nécessaire. Les chemins et lignes exacts sont maintenant
conservés ; la préparation courante ne relit que les messages SQLite identifiés
et les sept lignes anciennes, avec une borne de lecture par fichier.

Chaque occurrence conserve son tour/message ou son fichier/ligne, timestamp,
hash et métadonnées d’entrée. Les réponses du modèle, prédictions de type et
labels ne figurent pas dans le formulaire. Les métadonnées de l’entrée ne
prouvent pas l’accès à une pièce jointe ou la complétude du contexte :
`context_snapshot` reste nul tant que la revue ne l’établit pas.

Toutes les occurrences sont conservées, y compris lorsqu’une même demande est
présente dans plusieurs conversations. Les cas qui partagent une conversation
sont réunis transitivement dans une composante pour éviter une séparation
artificielle entre développement et test. Les filiations de conversations et
paraphrases sémantiques restent à vérifier par revue.

Le filtre lexical conservateur n’a proposé aucune paire sur ce lot. Cela ne
signifie pas qu’il n’existe aucune paraphrase : le formulaire permet de définir
manuellement un même groupe pour des demandes apparentées.

## Formulaire local

Le livrable est `runs/signature-corpus/review-20261007-final/review.html`, avec
`review-packet.json`, `provenance.json` et un manifeste de hashes dans le même
répertoire, ignoré par Git. Il fonctionne sans ressource externe. Le serveur de
prévisualisation n’écoute que sur `127.0.0.1` et n’offre aucun endpoint d’écriture.
Le fichier HTML peut aussi être ouvert directement hors ligne dans un navigateur.

1. Indiquer l’identité de l’annotateur et consulter les occurrences source.
2. Confirmer langue et opération. Définir un groupe de paraphrases seulement
   lorsqu’il est étayé par la comparaison des demandes.
3. Pour chaque dimension de contexte, choisir explicitement « non établi »,
   « aucun » ou une liste de champs. Le premier produit `null`, le deuxième
   une liste vide : ils ne sont pas interchangeables.
4. Décrire le contexte retrouvé ou la limite de capture, la base de l’annotation
   et sa justification. Une annotation fondée sur un résultat exige sa référence.
5. Marquer le cas revu, puis exporter le JSON. Les brouillons restent dans le
   navigateur ; l’export est la copie à conserver dans le dossier local.

L’import accepte uniquement le même dossier et ses identifiants de cas. Les
annotations conservent leur auteur par cas. Modifier l’identité courante ne
réattribue pas silencieusement les autres cas déjà revus. Une annotation ne
devient pas indépendante simplement parce qu’un nom a été saisi.

La revue est humaine et distincte des prédictions. Elle n’est pas automatiquement
une issue de tâche vérifiée : `label_origin=human_review` reste distinct de
`outcome`. Le système ne certifie ni l’indépendance du jugement, ni une précision,
ni une calibration générale sur la seule base de ce formulaire.

## Importer et figer le découpage après revue

```powershell
rtk proxy .venv/Scripts/python.exe examples/finalize_context_review.py --packet runs/signature-corpus/review-20261007-final/review-packet.json --review runs/signature-corpus/ma-revue.json --output runs/signature-corpus/revue-finalisee.json
```

Une revue incomplète est refusée. `--draft` permet de conserver un état partiel
sans figer de split. Les groupes de source, groupes manuels et paires confirmées
restent ensemble ; le gel existant conserve aussi les doublons normalisés.
Un seul groupe restant ne permet pas de produire un test tenu à l’écart.

Le découpage est choisi par groupes et ne promet pas un ratio exact de cas.
Les identifiants et hashes des cas sont conservés. Aucune métrique de qualité,
autorisation ou économie n’est produite par l’import ou le gel.

## Reproduire la préparation avec les locateurs conservés

```powershell
rtk proxy .venv/Scripts/python.exe examples/prepare_context_review.py --pack runs/signature-corpus/context-review-20261007.json --sql-index runs/context-provenance-20261007/probe-matches.json --legacy-index runs/context-provenance-20261007/probe-missing.json --output-dir runs/signature-corpus/nouvelle-preparation
rtk proxy .venv/Scripts/python.exe examples/serve_context_review.py --directory runs/signature-corpus/nouvelle-preparation
```

Ces commandes relisent les sources ciblées et vérifient les correspondances.
Elles ne modifient pas les bases d’historique et n’écrasent aucun dossier existant.

## Vérifications et limites de l’interface

Les tests couvrent correspondance exacte, borne temporelle, types de messages,
identité des cas, transitivité des groupes et garde-fous d’import/finalisation.
Le JavaScript généré est testé avec un DOM synthétique : labels vierges, distinction
`null`/liste vide, attribution, sauvegarde et refus d’un dossier étranger.

Le test interactif a rencontré une indisponibilité du connecteur navigateur
(délai dépassé puis détachement). Le rendu visuel et le téléchargement via un
navigateur réel ne sont donc pas attestés. Le serveur local, les fichiers et les
tests de code sont vérifiés séparément. Aucun cas réel n’a été annoté pendant
ces tests ; les vérifications de formulaire utilisent des demandes synthétiques.
