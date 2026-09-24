# État et reprise — 24 septembre 2026

## Ce qui tourne aujourd'hui

Ombre uniquement : rien n'est exécuté, aucune baseline n'est remplacée. Ce qui est
implémenté et exercé par les tests et les exemples : mesures et provenance,
vérificateurs déterministes, politique d'escalade et budgets, registre de routes,
vecteur de ressources et claim de banc, mode actif sous autorisation, audit
statique déterministe, horloge et transport de décision typée, signatures de
tâche (règle, cadre verbe+objet, KNN, micro-NN derrière un protocole unique),
ingestion versionnée des prompts réels, taxonomie, pont d'escalade, pont de
consommation `turn_dispatch` (une continuation va au directeur, une demande au
chemin de signature, et un message court ambigu reste `unresolved`), expérience
de route contrôlée et plan quotidien persisté sans écrasement.

Les tests passent localement sur Python 3.14 ; la CI de cette branche n'a pas
encore été exécutée. Le nombre évolue avec les travaux concurrents du dépôt.

## Ce qui est mesuré, et ce qui ne l'est pas

Les relevés datés ([22 septembre](RELEVE_2026-09-22.json),
[24 septembre](RELEVE_2026-09-24.json)) portent les chiffres de leur jour avec
leurs commandes et la révision de corpus qu'ils ont lue. En résumé, sur la
révision `22de4af5` :

- **Demandes réelles**, volume puis distincts : règle `0.403` / `0.330`, cadre
  `0.568` / `0.746`, cadre plus signal interrogatif `0.573` / `0.753`.
- **Triage** de ces demandes : `0.5624` du volume est unanime entre candidats et
  `0.0081` attend une étiquette humaine, donc l'arbitrage humain n'est pas le coût
  — l'atteinte l'est.
- **Hors de l'échantillon de déclaration** : sur les `154` demandes absentes de la
  révision de déclaration, le cadre tient `0.7128` en volume et `0.8247` en
  distinct, et le seuil préannoncé `> 0.50` est atteint, tandis que la règle tombe
  à `0.1590`. Ce résultat passe la porte de couverture préannoncée sur le groupe
  nouveau, avec la réserve sur sa composition portée par `ENSEIGNEMENTS.md`.
- **Voie publique** (Dolly-15k, tranches disjointes) : la règle couvre `0.75` à
  `0.79`, la récupération est la plus exacte (accord `0.72` à `0.75`, précision et
  rappel de champs autour de `0.69`).
- **Audit statique au 22 septembre** : `45` fichiers dans `src/tiberium_ai`, tous
  `sound`, déficit moyen `4.18`, onze `rule.god-function`. Ce relevé précède les
  modules ajoutés depuis.

Ce qui n'est pas mesuré, et ne peut pas l'être en l'état : l'**exactitude**, faute
d'étiquettes d'issue ; le **coût** d'une route réelle, faute de baseline mesurée
sur les mêmes tâches ; et la **généralité** de la couverture aux demandes
ordinaires, car le groupe nouveau est dominé par des textes longs.

## Ouvert, par ordre d'intérêt

- **TASK-097** — ratifier le vocabulaire proposé (`vocabulary-to-ratify.json`) :
  une vingtaine de lignes, avec des candidats à rejeter mêlés (`true`, `sans`,
  `autre`, `puis`, `apres`, `oui`, `https`, `2026`). C'est un geste humain.
- **TASK-109 puis TASK-110** — comparer les routes Astra/LLM, jugement Jev-like,
  Needle-like, règle et KNN sur les mêmes tâches, puis évaluer une piste
  géométrique. Protocole dans `docs/ASTRA_JEV_NEEDLE_RESEARCH.md` ; aucune de ces
  cartes n'autorise d'appel quota-bearing ni de téléchargement de poids.
- **TASK-087** — le vocabulaire de la classe `propose`, goulot mesuré d'un
  sixième du volume.
- **TASK-090 / TASK-088** — plancher par type de question, puis prolonger la
  courbe de mémoire pour trouver le palier.
La couverture hors échantillon de TASK-102 est vérifiée. Le relevé de la voie
réelle enregistre désormais sa révision au lieu de la laisser deviner par le
nom du fichier.

Le reste des cartes ouvertes vit dans `kanban.md` : ce wiki ne les duplique pas.

## Pièges de reprise

- **Ne jamais baser une branche sur une branche déjà fusionnée** (`codex/static-audit`
  et `codex/decision-signature-line` le sont toutes les deux) : `main` a avancé, et
  une telle branche apparaîtrait comme supprimant ce que `main` a gagné entre-temps.
  Repartir de `main` et rejouer les commits sur une branche neuve.
- Un commit non poussé sur une branche fusionnée n'est pas perdu, mais il n'est
  pas sur `main` : vérifier `git log --oneline HEAD` contre `origin/main` avant de
  conclure que le travail est en ligne.
- Les sorties de banc vont dans `runs/`, ignoré par git ; les révisions de corpus
  y vivent aussi et ne sortent jamais du poste.
- Les notes de `kanban.md` pour TASK-097 citent la mesure d'avant la déclaration
  des verbes manquants (moins de 30 % du volume) ; l'état courant est celui des
  relevés datés.
- Un retour « delta identique » de l'ingestion n'est pas une erreur : c'est
  l'idempotence de la révision adressée par contenu.
