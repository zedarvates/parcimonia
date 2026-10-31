# Préparer un travail avec Parcimonia

Premier pilote local du 20 octobre 2026 : trouver des capacités et des fichiers
utiles, sans exécuter la tâche proposée ni appeler de modèle. La préparation
produit un paquet compact, un audit complet et un index réutilisable.

Pour noter quels fichiers ont été utiles, ajouter les manquants et conserver le
contexte pour l'étape suivante, voir [utilité et continuité](FILE_USEFULNESS_AND_FOLLOWUP.md).
Ces observations sont les indicateurs prioritaires ; les millisecondes du
préparateur restent secondaires.

## Utilisation immédiate

Depuis `C:\TiberiumAI` :

```powershell
$env:PYTHONPATH = 'C:\TiberiumAI\src'
rtk python examples/prepare_development_task.py --goal 'Verifier les profils outils et le rejeu des appels' --constraint 'Travail local uniquement' --output-dir runs/preparation-ma-tache-01
```

Le dossier de sortie doit être nouveau et sous `runs/`. Lire `packet.md` pour
les propositions et `packet.json` pour l'audit. `packet.json.compact_context`
est la partie à donner à l'agent après revue ; le fichier JSON entier conserve
aussi toutes les raisons d'exclusion.

Pour réutiliser l'index lors de la tâche suivante :

```powershell
rtk python examples/prepare_development_task.py --goal 'Verifier le contexte manquant' --previous-index runs/preparation-ma-tache-01/index.json --output-dir runs/preparation-ma-tache-02
```

`--engineering-skills-root <dossier>` ajoute explicitement les quatre sources
du plugin engineering lorsqu'il est installé. Aucun chemin personnel n'est
enregistré dans l'inventaire : seuls les alias `workspace` et `engineering`
sont utilisés. Une racine absente est signalée et n'est pas devinée.
Le paramètre `--strict` exige des propriétés vérifiées ; cette CLI n'émet aucune
attestation hôte, donc les fiches déclaratives restent exclues. L'API Python
accepte séparément les attestations déjà examinées par l'hôte.

Depuis l'essai réel du 20 octobre, `--policy` permet de fournir les contraintes
structurées dans un fichier JSON :

```powershell
rtk python examples/prepare_development_task.py --goal 'Verifier les profils outils' --policy examples/fixtures/development_local_policy.json --output-dir runs/preparation-politique-01
```

Cette politique déclarative limite les propositions au domaine code, local,
lecture et hors réseau. Elle ne donne aucune permission d'exécuter. Les champs
requis sont `version`, `required`, `allowed`, `require_verified` ; clés ambiguës,
tags inconnus et valeurs invalides sont refusés avant la création de la sortie.
`--strict` valide d'abord le fichier, force ensuite `require_verified=true` et
ajoute `+strict` à sa version. Un fichier permissif ne désactive donc pas ce mode.
La politique effective est conservée dans le paquet et l'évaluation.

## Inventaire initial

L'inventaire v1 `examples/fixtures/development_capabilities.json` contenait 24
fiches : 20 mécanismes Python de Parcimonia et quatre références de skills engineering
(debug, code-review, testing-strategy, architecture). Il ne s'agit pas de 24
outils MCP installés ni d'un nouvel inventaire global du poste.

La v2 contient **28 fiches** après l'essai réel : indexation, paquet de travail,
validation de politique et CLI de préparation ont été ajoutés avec leurs sources
et tests. La CLI déclare des écritures et reste dans la file de revue sous une
politique de lecture seule. Ce correctif vient du constat que la v1 omettait ses
propres fichiers de préparation. Voir [l'essai réel](REAL_TASK_POLICY_TRIAL.md).

La v3 porte l'inventaire à **30 fiches** avec `files.review` et `task.continue`,
leurs sources, tests et CLI. Elles permettent de préparer les étapes suivantes
à partir d'observations explicites sur l'utilité des fichiers.

Les descriptions bilingues sont rédigées pour ces familles : JSON canonique,
vérification, registre, contexte, profils, audit des skills, calibration et banc
d'épisodes. Les sources et symboles sont repérés structurellement ; ce contrôle
ne démontre ni la disponibilité d'un runtime ni la qualité du comportement.
Les tags sont **déclarés**, et les propriétés inconnues restent nulles. Le
backend de cache et les workflows de skills dont les effets peuvent dépendre
d'un fournisseur sont conservés avec des propriétés inconnues : le filtre local
ne les assimile pas à des opérations hors réseau.

Chaque fiche épingle le hash des octets source. Après modification d'un module,
ses fiches passent en `source_changed_review_required`. Revoir les propriétés,
mettre à jour les empreintes et les révisions de fiche/inventaire explicitement
avant de les réutiliser. Ne pas actualiser ces empreintes automatiquement pour
faire disparaître une exclusion. Les imports et fichiers de support ne sont
pas intégralement attestés par ces fiches initiales : elles servent à préparer
une revue, pas à garantir une exécution.

## Contenu du paquet

- Objectif fourni par l'utilisateur et contraintes libres, conservés comme
  données. Les contraintes libres demandent une interprétation par l'agent ;
  seuls les critères structurés de la politique sont appliqués par le filtre.
- Au plus cinq candidats par défaut, classés par recouvrement lexical après
  filtrage des profils. Une normalisation FR/EN bornée facilite les recherches.
- Références versionnées, chemins relatifs, symboles et lignes source.
- Fichiers à lire, références documentaires et tests suggérés, avec leurs hashes.
  La recherche de fichiers reste bornée aux fichiers explicitement inventoriés.
- File séparée de candidats à revoir, contrôles conseillés et inconnus explicites.

Un score lexical n'est pas une probabilité de pertinence. Sans correspondance,
aucune capacité n'est choisie arbitrairement. Le résultat demande toujours une
revue de l'agent ; `auto_act_allowed=false`, `execution=not_run`, `model_calls=0`.
Lire les instructions applicables et le skill choisi avant toute utilisation.

## Index et fraîcheur

La préparation ne parcourt pas tout le dépôt : elle lit uniquement les sources
et fichiers de support de l'inventaire fourni. Limites : 30 fiches, cinq fichiers
associés par fiche, 128 fichiers indexés, 256 Kio lus au maximum par fichier,
19 candidats au maximum et 16 références de fichiers dans le paquet.

Les chemins doivent rester sous les racines explicitement fournies, y compris
après résolution des liens. Les répertoires cachés, `runs/`, chemins absolus et
traversées de répertoires sont exclus. Les sources sont analysées en tant que
texte/AST, jamais importées ou exécutées.

Le second passage relit les octets et contrôle les hashes ; il réutilise les
termes et positions de symboles si la clé de cache correspond. Il économise le
calcul d'index, pas la relecture des fichiers. Le cache est local et fourni par
l'hôte : son empreinte détecte les modifications accidentelles mais n'est pas
une signature d'authenticité. Ne pas charger un cache fourni par une source
externe comme une preuve fiable. L'index est un instantané : recontrôler les
sources avant une action ultérieure.

Le pilote écrit `index.json`, `catalog.json`, `packet.json`, `packet.md`, puis un
`manifest.json` final avec les empreintes. Un dossier interrompu sans manifeste
complet ne prouve pas que la préparation a abouti. Les sorties sont locales et
ignorées par Git ; elles peuvent contenir le texte de la demande et des termes
issus du code, donc restent dans le périmètre privé du travail.

## Premier résultat observé

Demande : préparer une revue des profils d'outils locaux, des dépendances
versionnées et du rejeu des appels. Les quatre sources de skills proviennent du
même dossier engineering fourni explicitement à la commande.

| Observation | Premier passage | Avec index précédent |
| --- | ---: | ---: |
| Fichiers lus | 30 | 30 |
| Octets lus | 219 138 | 219 138 |
| Dérivations construites / réutilisées | 30 / 0 | 0 / 30 |
| Durée d'indexation interne | 166,5 ms | 31,7 ms |
| Durée de préparation interne | 38,1 ms | 37,9 ms |

Les deux passages proposent les mêmes cinq mécanismes : évaluation, validation,
liaison d'appel, rejeu et filtrage de routes par profils. Six fichiers sont
cités. Le skill code-review est signalé à examiner ; ses propriétés d'exécution
inconnues empêchent son admission par le filtre local.

Le contexte compact sérialisé contient 6 347 caractères, contre 98 519 pour
l'alternative consistant à transmettre **tout l'index**. Cette comparaison est
une taille de sérialisation face à une référence hypothétique : elle ne mesure
ni des tokens économisés sur nos agents actuels ni la conservation de qualité.
Les durées viennent d'une seule paire d'exécutions et excluent démarrage Python,
lecture de la CLI, chargement de l'ancien JSON et écriture des livrables.

Rapports conservés dans `runs/task-preparation-20261020-cold` et
`runs/task-preparation-20261020-warm`. L'accélération de tâches réelles, les
économies d'API et la qualité restent **non mesurées**.

Le paquet final avec contraintes et contrôles visibles dans le Markdown est
conservé sous `runs/task-preparation-20261020-final`. Validation : 157 tests
ciblés passent ; les 16 tests du préparateur repassent après ajustement du rendu.

## Prochaine preuve à collecter

Utiliser ces paquets sur des tâches de développement réelles et conserver, par
tâche, les candidats proposés, le choix effectif de l'agent, les fichiers utiles
ou manquants, les corrections et le temps jusqu'au résultat accepté. Prévoir une
comparaison avec le travail habituel sur des tâches comparables ; ne pas rejouer
la même tâche déjà résolue comme si elle était indépendante. Cette collecte
permettra de choisir où brancher automatiquement la préparation et si un modèle
local apporterait un gain sur les ambiguïtés restantes.
