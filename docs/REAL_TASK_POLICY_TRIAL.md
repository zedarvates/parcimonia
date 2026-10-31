# Essai réel : politique structurée dans la CLI Parcimonia

Le 20 octobre 2026, une tâche de développement réelle a été réalisée dans
TiberiumAI : ajouter `--policy <JSON>` au préparateur de tâches, conserver la
priorité de `--strict` et vérifier les entrées invalides. Le code, les tests et
la documentation sont modifiés ; aucune proposition de route n'est exécutée.

## Protocole et résultats

Le premier paquet a été conservé avant la modification fonctionnelle et avant
la correction de l'inventaire. Les critères étaient : appliquer les contraintes
structurées, ne pas désactiver strict via un fichier permissif, refuser les
politiques ambiguës/invalides avant de créer la sortie et conserver l'usage sans
fichier de politique. Le premier test échouait avec `--policy` non reconnu.

Le même agent connaissait déjà la CLI avant de figer l'objectif. Il a implémenté
la modification et examiné les suggestions ; ce cas n'est donc pas une évaluation
en aveugle ou indépendante. Une recherche ciblée par identifiants connus a été
chronométrée pour retrouver les fichiers, sans la présenter comme le temps d'un
agent sans Parcimonia.

| Observation | Paquet initial, inventaire v1 | Après correction, inventaire v2 |
| --- | ---: | ---: |
| Fiches inventoriées | 24 | 28 |
| Candidats proposés | 5 | 5 |
| Fichiers proposés | 14 | 10 |
| Trois fichiers centraux présents | 0 / 3 | 3 / 3 |
| Indexation + préparation internes | 72,4 ms | 93,5 ms |
| Appels de modèle par le préparateur | 0 | 0 |

Les trois fichiers de référence sont la CLI, le module `task_preparation.py` et
son fichier de tests existant. Le nouveau test de politique n'existait pas lors
du premier paquet ; il n'est pas ajouté rétroactivement à ce dénominateur.
La recherche ciblée a retrouvé les trois références en environ 315 ms, durée de
processus comprise. Sa portée et sa mesure diffèrent des temps internes du
préparateur : aucune accélération relative n'en est calculée.

**Le premier paquet n'a pas apporté le bon aiguillage sur cette tâche.** Il a
fallu une recherche supplémentaire. Le paquet corrigé couvre les fichiers
attendus mais coûte légèrement plus de préparation ; ce passage bénéficie de
l'ajout des capacités précisément découvertes sur ce cas. Il ne prouve pas une
amélioration sur de nouvelles tâches.

Le jalon de premiers tests fonctionnels a été observé 116 secondes après le
premier paquet. Le jalon de validation élargie et de correction d'inventaire a
été observé après 278 secondes, soit 4 min 38 s. Ces durées UTC grossières
incluent raisonnement de l'agent et attentes d'outils ; elles excluent la
rédaction finale du présent bilan. Elles ne sont ni un temps humain économisé
ni un résultat accepté par l'utilisateur ou en production. Aucun temps de tâche
indépendante sans Parcimonia n'a été mesuré ; le gain global reste inconnu.

## Choix examinés et corrections

| Proposition initiale | Constat sur cette tâche | Correction |
| --- | --- | --- |
| `profiles.assess` | API existante utile pour valider la politique | Conservée comme soutien |
| `profiles.routes` | Filtrage des routes superflu pour charger une politique de préparation | Reste trop bien classé après correction ; à tester sur un autre cas |
| `profiles.validate` | Valide une fiche, pas une politique | Ajouter la capacité réelle `preparation.policy` |
| `json.canonical` | Sérialiseur déjà utilisé, sans modification requise | Soutien incident, pas cible principale |
| `registry.filter` | Filtrage de routes sans rapport direct avec la nouvelle option CLI | Privilégier les capacités du préparateur |

L'inventaire v2 ajoute validation de politique, construction de paquet,
indexation et CLI, avec les références de code, documentation et tests. La CLI
déclare des écritures de rapports ; elle reste correctement hors des candidats
admissibles en lecture seule et apparaît dans la file de revue. Son fichier
source peut néanmoins être proposé à la lecture pour travailler sur son code.

Le nouveau classement commence par `preparation.policy` et
`preparation.packet`, puis propose `profiles.assess`, `preparation.index` et
encore `profiles.routes`. La prochaine amélioration de classement devra
distinguer l'intention de modifier une CLI de celle d'exécuter un routage ; ce
seul cas ne suffit pas à choisir un nouvel algorithme ou entraîner un modèle.

## Validation fonctionnelle

**170 tests ciblés passent**, sans échec ni erreur. Les nouveaux tests couvrent
les filtres de domaine, effets et réseau, la conservation de la politique dans
les traces, la priorité de strict, le rejet des clés dupliquées, nombres non
finis, champs inconnus et types invalides. Les tests existants de préparation,
profils, registre, recettes, banc et contrats repassent également.

La CLI a aussi été exécutée avec une politique locale personnalisée puis avec
la même politique et `--strict` : le premier mode propose des candidats et le
second les exclut faute d'attestations séparées. Les comptes rendus de test ne
constituent pas une autorisation d'agir.

## Preuves conservées localement

Le dossier ignoré `runs/task-policy-real-20261020` contient :

- `registration.json` : objectif, critères, exposition préalable et recherche ;
- `before/` : paquet initial, catalogue, index et manifeste complets ;
- `source-before/` et son manifeste : état des fichiers avant le correctif ;
- `custom-policy/`, `strict-policy/` : exercices réels de la CLI ;
- `after-final/` : paquet corrigé avec instantané de l'inventaire v2 ;
- `validation.xml` : résultat JUnit des 170 tests ;
- `outcome.json`, `outcome-manifest.json` : mesures, avis par choix, limites et hashes.

Ces fichiers peuvent contenir le texte des demandes et du code local : ils ne
sont pas destinés à la publication. Les métriques de gain global, coût API et
usage de tokens de l'agent restent nulles lorsqu'elles ne sont pas mesurées.
Zéro appel de modèle dans le préparateur ne signifie pas zéro appel pour le
travail de l'agent qui a réalisé cette modification.

## Prochaine mesure utile

Garder ce cas comme régression de développement. Choisir une autre tâche réelle,
figer le paquet avant d'ouvrir les fichiers cibles, puis enregistrer les mêmes
observations sans adapter l'inventaire avant la première notation. Une série de
cas distincts, avec examen séparé et tâches comparables, permettra d'évaluer un
gain de travail ; aucune conclusion de SFT ou de routage automatique n'est prise.
