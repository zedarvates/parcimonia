# Fichiers utiles et continuité entre étapes

Parcimonia peut désormais recueillir l'utilité observée des fichiers d'un paquet
et préparer l'étape suivante de la même tâche. La priorité est de retrouver et
conserver les bonnes références, décisions et preuves rapportées. Les durées
d'indexation restent des mesures techniques secondaires.

## Ce qui est mesuré

Pour chaque fichier proposé :

- `used` : effectivement utilisé pour travailler, par exemple lu puis modifié ;
- `supporting` : utilisé comme contexte, contrat, exemple ou source de test ;
- `irrelevant` : explicitement jugé inutile pour l'étape examinée ;
- `unreviewed` : pas encore examiné ; aucune conclusion de pertinence.

Un fichier utile absent du paquet est ajouté avec une origine explicite :
`existing` s'il existait auparavant, `created` s'il a été créé pendant le travail.
Cette origine est déclarée par le relecteur, pas déduite automatiquement de Git.
Les nouveaux fichiers ne sont donc pas comptés comme des erreurs de recherche.

Le bilan conserve les nombres de recherches et de lectures supplémentaires
rapportés. `null` signifie inconnu ; il n'est jamais converti en zéro. Le nombre
de lectures/recherches évitées et le temps gagné restent inconnus tant qu'ils
n'ont pas été mesurés. Il n'y a pas de score d'accuracy sur ces observations.

## Recueillir une revue

Le modèle de saisie est
`examples/fixtures/file_review_template.json`. Créer une copie locale sous
`runs/`, identifier tâche, étape et relecteur, puis remplir seulement les
observations connues. Exemple de jugement :

```json
{
  "source": {"root": "workspace", "path": "src/tiberium_ai/task_preparation.py"},
  "status": "used",
  "reason": "Fonction modifiée pour charger la politique structurée."
}
```

Les autres champs du modèle sont obligatoires. `judgments` et `missing_files`
acceptent au plus 16 entrées chacun ; les jugements nomment des fichiers
effectivement proposés par le paquet. Un fichier manquant porte aussi
`origin`, `status` utile et `reason`. Il doit être observable sous une racine
explicitement fournie. `review_complete=true` exige que tous les fichiers
proposés soient annotés ; ce drapeau ne prouve pas une revue indépendante.

Le paquet original n'est pas modifié. La revue est liée à son empreinte entière.
Les fichiers manquants sont liés à leurs octets observés lors de la création de
la revue ; ne pas réutiliser un ancien formulaire pour prétendre avoir relu une
nouvelle version. Utiliser ensuite la revue enregistrée avec `--review` pour
conserver les empreintes historiques.

## Préparer l'étape suivante

```powershell
$env:PYTHONPATH = 'C:\TiberiumAI\src'
rtk python examples/continue_development_task.py --previous-packet runs/ma-tache/packet.json --feedback runs/ma-tache/feedback.json --goal 'Verifier le correctif et sa documentation' --stage-id verification --output-dir runs/ma-tache-suite
```

La CLI écrit un nouveau dossier contenant `file-review.json`, `index.json`,
`packet.json`, `packet.md`, `catalog.json` et un manifeste final avec hashes.
Elle refuse d'écraser un dossier. Les options `--inventory`, `--previous-index`,
`--engineering-skills-root`, `--policy` et `--strict` restent disponibles.
La politique structurée est réappliquée aux capacités ; strict reste prioritaire.

Pour rafraîchir depuis une revue déjà enregistrée, remplacer `--feedback` par
`--review <file-review.json>`. Les deux paramètres sont exclusifs. L'ancienne
revue est conservée à l'identique, ce qui permet de détecter un fichier modifié
après la revue. Une suite exige la même tâche et une nouvelle étape ; les
empreintes du parent et de la revue rendent le chaînage explicite.

## Réutilisation du contexte

Les fichiers précédemment utilisés ou utiles en soutien passent avant les
nouvelles suggestions. Les références ajoutées à la revue peuvent être conservées
même si elles ne figuraient pas encore dans l'inventaire de capacités. Leur
lecture reste bornée aux chemins autorisés par le préparateur, à 256 Kio par
fichier et aux racines explicites ; aucun fichier n'est importé ou exécuté.

- `unchanged` : mêmes octets ; la référence peut être conservée, sa pertinence
  pour le nouveau but reste à examiner ;
- `changed_requires_reread` : nouvelle empreinte citée, relecture nécessaire ;
- `unavailable` : fichier absent, trop grand ou racine indisponible ; l'ancienne
  référence n'est pas présentée comme une source fraîche.

Le paquet conserve au plus 16 références, avec compteurs de troncature. Les
fichiers jugés inutiles à l'étape précédente ne sont pas bannis : ils sont
signalés et placés après les autres nouvelles suggestions s'ils réapparaissent.
Un test inutile pendant l'implémentation peut devenir utile lors de la validation.
Les capacités et leurs profils sont recalculés, jamais reconduits par la revue.

Les notes `decision`, `test_result` et `open_question` portent texte, références
de sources et éventuellement une référence de preuve. Un résultat de tests
rapporté exige une référence de preuve, mais celle-ci n'est pas exécutée ou
certifiée par le suivi. Une source modifiée rend sa note
`stale_requires_review`. Même avec des sources inchangées, environnement,
dépendances, portée et autorisations doivent être réexaminés. Toutes les notes
restent `reported_not_independently_verified`.

Le module n'affirme pas qu'une lecture a été évitée parce qu'un fichier n'a pas
changé : il conserve les références et observations nécessaires pour le mesurer.
Ni la revue ni sa somme de contrôle ne sont une permission ou une signature.
Les données de retour doivent venir du relecteur/hôte, et non d'une source
externe qui se proclame fiable. `auto_act_allowed` reste faux.

## Application au travail réel sur `--policy`

Une revue rétrospective du premier paquet de cette tâche a été faite par l'agent
qui a réalisé le changement, sans prétendre à une évaluation indépendante :

- 14 fichiers initialement proposés ; quatre explicitement examinés : un utile
  en soutien et trois inutiles pour cette modification ; dix restent non évalués ;
- quatre fichiers utiles déjà existants manquaient : CLI, module de préparation,
  tests existants et documentation du pilote ;
- deux fichiers utiles ont été créés : tests de politique et exemple JSON ;
- une recherche supplémentaire a été enregistrée ; les lectures supplémentaires
  restent inconnues ;
- sept références utiles et deux notes liées aux sources sont transmises à la
  préparation de l'étape de validation/documentation.

La première préparation de suite a observé les sept références inchangées. Une
nouvelle exécution à partir de **la revue sauvegardée** permet ensuite de voir
les éventuels changements de documentation, sans réétiqueter leur nouvelle
version comme celle précédemment examinée.

Les preuves sont sous `runs/task-followup-20261020` : formulaire explicite,
revue liée au paquet initial et paquets de suite. Ce cas démontre la capture et
la continuité des observations ; il ne démontre pas encore combien de lectures
ou recherches ont été évitées sur un travail indépendant.

Le rafraîchissement final confirme six références inchangées et une documentation
modifiée à relire (`docs/TASK_PREPARATION_PILOT.md`). Les deux notes conservent des
sources inchangées, tout en restant rapportées et soumises à revue de portée.
Les sept références utiles tiennent dans le paquet. Deux nouvelles suggestions
de fichiers sont écartées par le plafond de 16 : ce compteur est visible pour
que la conservation de contexte ne masque pas le besoin d'élargir la recherche.

Validation : **188 tests ciblés passent**, dont 18 sur les revues, la fraîcheur,
le chaînage, les limites et la CLI de suite. Le rapport JUnit et le bilan JSON
sont `runs/task-followup-20261020/validation.xml` et `summary.json`.
