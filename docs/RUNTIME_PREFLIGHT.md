# Préparer une réservation à partir de l'état observé

TASK-114 relie les filtres existants avant qu'un consommateur ne demande une
réservation à son propre ordonnanceur. Le premier raccord est une fonction pure :
il ne réserve pas de slot et ne lance ni outil, ni modèle, ni processus.

## Trois contrôles réunis

- `filter_profiled_routes` conserve les contraintes du registre, les capacités
  demandées, les profils exacts, leurs dépendances et les attestations fournies
  par l'hôte. La disponibilité `available` est exigée dans ce préflight.
- `review_observations` vérifie que les rapports de disponibilité correspondent
  à la tâche, au poste, au matériel, au manifeste de route et aux références de
  profils actuels, avec une durée de validité explicite.
- `local_compute.advise` examine le seul candidat choisi, avec ses mesures et le
  snapshot de ressources inchangés. Un autre candidat ne le remplace pas
  silencieusement. Les réserves et le refus d'une opération lourde occupée restent
  ceux du conseiller existant.

Le raccord refuse aussi les contradictions explicites : un profil ou une
dépendance demandant un GPU ne peut pas être représenté par un candidat CPU ;
les mentions `ram-heavy` et `vram-heavy` exigent un candidat déclaré lourd.
Un besoin VRAM positif exige un candidat GPU. Ces mentions ne donnent aucune
quantité de mémoire ; les facettes absentes ou inconnues restent signalées dans
`resource_declarations.unknown_profile_ids`. L'absence d'un tag ne prouve pas
l'absence d'un besoin. Les échéances de 60 secondes pour le snapshot et de
86 400 secondes pour la mesure sont comparées sans perte d'arrondi.

Les exigences de disponibilité sont construites par
`build_runtime_requirements`, à partir des références exactes. Le consommateur
ne peut pas substituer une liste d'exigences omettant une dépendance. Une closure
trop grande ou invalide est refusée explicitement.

## API du consommateur

Le module `tiberium_ai.runtime_preflight` expose :

- `build_runtime_requirements(...)` pour obtenir les exigences de disponibilité,
  les références des profils et leur empreinte de contexte ;
- `review_runtime_preflight(...)` pour recalculer les trois contrôles à partir
  des sources et rapports actuels.

Le consommateur fournit notamment une `Task`, l'identifiant de route choisi,
la révision de tâche, l'identité du poste, le registre, le catalogue, les bindings,
la politique, les empreintes de contenu observées et les attestations qu'il
reconnaît. Les observations, la requête de calcul, le snapshot et le candidat
restent des entrées explicites. L'API ne découvre pas les services installés.

Le hash de charge `workload_sha256` conserve le sens du conseiller existant :
il doit correspondre aux mesures de la charge sélectionnée. Une empreinte de
contexte supplémentaire lie les observations ; elle ne remplace pas ce hash
de charge ni le hash des octets d'un outil.

Le statut `eligible_for_host_reservation` signifie seulement que les rapports
fournis satisfont les contrôles. Sinon, le statut est `blocked`, accompagné des
diagnostics. Dans les deux cas, `auto_act_allowed` et `reservation_performed`
restent `false`. Les rapports hôte ne sont pas authentifiés par cette fonction.

## La réservation reste une opération de l'hôte

Le parcours à qualifier est :

1. Réunir des observations actuelles et effectuer le préflight.
2. Demander une acquisition atomique au mécanisme de réservation existant.
3. Faire vérifier par l'hôte la liaison à la tâche, la route, le poste et les
   ressources réellement réservées. Si le fournisseur ne porte ni propriétaire
   ni échéance, conserver ces limites au lieu de lui attribuer ces garanties.
4. Revalider les conditions utiles juste avant le lancement, puis libérer selon
   le protocole de l'hôte et réconcilier l'état après interruption.

Un snapshot `heavy_busy=True` ne doit pas être réécrit en `False` au motif que
le bail serait détenu par le consommateur. Le conseiller actuel examine un
snapshot disponible avant acquisition ; l'admission finale appartient au vrai
hôte, qui connaît les réservations et les ressources courantes.

La prévention de deux acquisitions simultanées demande un essai du mécanisme
atomique réel. Des reçus compatibles, un verrou simulé ou deux préflights
positifs ne prouvent pas cette propriété. TASK-114 reste ouverte jusqu'à ce
raccord et sa qualification. Aucune réservation multi-postes n'est ajoutée ici.

## Vérifications attendues

Conserver les cas de disparition d'un outil, changement de source ou de profil,
dépendance absente, observation périmée ou future, poste ou matériel différent,
candidat d'une autre route, manque de mémoire et opération lourde occupée.
Une nouvelle entrée doit conduire à un nouveau contrôle plutôt qu'au rejeu
aveugle d'un ancien rapport.

Les exemples construits et les tests hors ligne vérifient le contrat et son
raccordement. Ils ne qualifient pas le matériel d'Odin, Eurekaï, Thor ou Glyph,
ni la reconnexion d'Ultimate Odycer. La surface MCP du plugin reste celle de la
PR #40 ; ce raccord de bibliothèque n'ajoute pas de nouvel outil MCP.

Le raccord suivant des [reçus RAM](HOST_MEMORY_RECEIPTS.md) réutilise le snapshot
atomique du garde candidat existant. Son démonstrateur utilise de vrais fichiers
temporaires avec une capacité construite ; le test concurrent natif a été
exécuté. La qualification sur l'hôte cible et le slot lourd reste ouverte.

Voir [observations](VERIFIED_OBSERVATIONS.md),
[profils](EXECUTION_PROFILES.md), [V1](V1_GATES.md) et
[backlog](../kanban.md).

Qualification du premier raccord sur Python 3.12.14 : **4 200 tests et
100 sous-tests passent**, dont 34 cas du nouveau préflight. La revue
indépendante a fait corriger une contradiction entre ressources déclarées et
candidat, ainsi que l’arrondi d’une mesure trop ancienne. Les cas racine et
dépendance, les bornes temporelles et 17 mutations d’identité/état ont été
examinés séparément. Grammaire Python 3.10 et liens relatifs contrôlés.
Les tests de l’hôte cible et du jeu restent à réaliser.
