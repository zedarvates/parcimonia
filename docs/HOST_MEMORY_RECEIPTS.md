# Relier un précontrôle à la réservation RAM de l'hôte

Ce raccord de TASK-114 consomme le snapshot du gestionnaire existant. Il ne
crée ni verrou, ni registre de réservations, ni ordonnanceur. Le fournisseur
reste propriétaire de l'acquisition, de la revalidation et de la libération.

## Fournisseur réellement inspecté

Le garde `HostMemoryGuard` est proposé dans la
[PR Botte Secrète #166](https://github.com/zedarvates/botte-secrete/pull/166),
au commit inspecté `c10d0f1a3e24103b89c805a2b03ed4afd2e77d67`.
Il n'était pas fusionné dans le main Botte inspecté
`7b8d73ae7526c6fc369e7f5f1734144671774f81`.

Ses opérations sont `reserve(key, requested_bytes)`, `check(key)`, `release(key)`,
`retain_many(...)` et `snapshot(include_reservations=True)`. Le snapshot et les
budgets sont lus sous le verrou de fichier du fournisseur. L'état natif conserve
des clés et des `requested_bytes` ; il ne comporte pas de propriétaire, de tâche,
de poste, d'expiration, de génération ou de token de fencing.

Dans le candidat Odin, la clé existante vient de `Queue.memory_key(job_id)` :
chemin absolu du spool, séparateur `:`, identifiant du job. L'adaptateur ne
remplace pas cette convention par une nouvelle identité de réservation.

## Deux étapes explicites

`build_host_memory_expectation(...)` construit une attente privée depuis le
précontrôle courant, le candidat et la requête de calcul. L'appelant fournit une
empreinte du précontrôle détenue séparément, ainsi que son consommateur, le
fournisseur épinglé, la portée et la clé native choisie par l'hôte.

Le budget demandé est le maximum des incréments RAM et engagement déclarés.
Cette règle conservatrice ne mesure pas la consommation réelle. Une réservation
de taille nulle n'est pas créée artificiellement pour un mécanisme sans besoin
mémoire déclaré. Le hash de charge conserve sa convention antérieure.
Le budget natif est un comptage, pas une limite mémoire imposée par le système.

Après acquisition par le gestionnaire existant, l'hôte appelle
`snapshot(include_reservations=True)`, puis transmet ce snapshot à
`review_host_memory_snapshot(...)` avec l'empreinte d'attente qu'il détient et le
temps de son observation. Une nouvelle attente ne doit pas être reconstruite
depuis un reçu non reconnu pour lui fabriquer une ancre de confiance.

Le contrôle porte sur la liaison exacte, les dates, la présence de la clé,
le budget, les compteurs et la cohérence des métriques et de la décision native.
Les booléens ne deviennent pas des quantités de mémoire. Une mesure Windows
doit fournir son engagement disponible. Les autres ressources du parcours
restent à vérifier par l'hôte.

Une empreinte recomputée contrôle la cohérence des octets fournis ; elle
n'authentifie pas le fournisseur. Le résultat conserve cette limite. Le rapport
public ne reproduit ni clé native, ni chemin de spool, ni réservations des autres
jobs ; il garde les empreintes et les métriques nécessaires.

## Fraîcheur sans expiration inventée

Le précontrôle et les observations doivent être actuels selon la durée de
validité choisie, deux secondes par défaut. Cette durée borne la réutilisation
d'un constat : elle ne fait pas expirer une réservation du fournisseur.
Le temps UTC du snapshot reste distinct de l'horloge monotone utilisée dans le
garde. Une horloge incompatible ou future n'est pas corrigée silencieusement.
La chronologie doit respecter précontrôle ≤ mesure native ≤ observation ≤ revue.
Les dates natives sont UTC, à la seconde ou avec au plus six décimales ; une
précision supérieure est refusée plutôt que tronquée par le parseur.

Un refus, une réponse absente ou `resource_state_unavailable` ne déclenche
aucune libération ou nouvelle acquisition. Une opération interrompue demande
réconciliation. Les réservations de travaux occupés ou incertains restent sous
la responsabilité de l'hôte. Le contrôle n'invente aucun propriétaire natif,
TTL, fencing token ou garantie d'exclusivité multi-postes.

`consistent_host_memory_snapshot` signifie que les rapports respectent ce
contrat. `auto_act_allowed`, `reservation_performed` et `execution_performed`
restent faux. L'hôte doit revalider sa réservation et les ressources avant
départ. Un état `heavy_busy=True` ne doit pas être transformé en état libre
pour faire repasser le conseiller du précontrôle.

## Démonstrateur avec le vrai backend candidat

L'exemple charge uniquement un fichier source explicitement choisi et dont
l'empreinte a été vérifiée. Il exécute ce code local sélectionné ; il ne télécharge
pas le fournisseur. Les états sont écrits dans un nouveau répertoire temporaire.
Le précontrôle, la capacité et les mesures de charge sont construits pour l'essai.
Aucun modèle, workload, service ou fichier de réservation actif n'est lancé.

Depuis le dépôt installé, adapter le chemin réel :

```sh
python examples/host_memory_receipt_demo.py \
  --host-memory-source /chemin/botte-secrete/skills/host_resources.py \
  --expected-source-sha256 0059525498d74c65255e538105dc0f6b7efa8cc3517bce78a7262cbf8a7cc7f5
```

Cette empreinte correspond au blob Git inspecté
`2a4a2324f27c3aab259acd3c57bfca02b3d7b642` de la PR #166. Un autre fichier
doit être inspecté et épinglé à nouveau. Le démonstrateur contrôle l'absence de
réservation, son acquisition native, puis sa disparition après libération du seul
état temporaire qu'il possède.

Le test concurrent existant du backend a également été exécuté sur la copie
conforme à cette révision : quatre processus synchronisés tentent chacun 4 Gio,
avec 8 Gio disponibles et 16 Gio totaux construits pour l'essai. Exactement une
admission et 4 Gio de budget durable ont été constatés. Cette preuve porte sur
l'exclusion locale et le comptage du candidat ; elle ne qualifie ni la RAM
physique d'Odin, ni une installation, ni un protocole multi-postes.

Qualification locale sur Python 3.12.14 : **4 259 tests et 100 sous-tests passent**,
dont 59 cas du nouveau contrôle. La revue indépendante a fait corriger les
horodatages tronqués au-delà de six décimales et la réutilisation d'un snapshot
antérieur au précontrôle. Le démonstrateur passe en Python normal et optimisé
(`-O`) ; une empreinte de source différente est refusée avant chargement.

Voir [précontrôle](RUNTIME_PREFLIGHT.md), [observations](VERIFIED_OBSERVATIONS.md)
et [backlog](../kanban.md). La qualification de l'admission réelle de l'hôte et
du parcours Ultimate Odycer reste distincte.
