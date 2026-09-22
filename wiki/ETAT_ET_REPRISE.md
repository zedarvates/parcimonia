# État et reprise — 22 septembre 2026

## Ce qui tourne aujourd'hui

Ombre uniquement : rien n'est exécuté, aucune baseline n'est remplacée. Ce qui est
implémenté et exercé par les tests et les exemples : mesures et provenance,
vérificateurs déterministes, politique d'escalade et budgets, registre de routes,
vecteur de ressources et claim de banc, mode actif sous autorisation, audit
statique déterministe, horloge et transport de décision typée, signatures de
tâche (règle, cadre verbe+objet, KNN, micro-NN derrière un protocole unique),
ingestion versionnée des prompts réels, taxonomie et pont d'escalade.

`795` tests passent, sur Python 3.10 et 3.14.

## Ce qui est mesuré, et ce qui ne l'est pas

Le relevé daté ([RELEVE_2026-09-22.json](RELEVE_2026-09-22.json)) porte les
chiffres de ce jour avec leurs commandes et la révision de corpus qu'ils ont lue.
En résumé :

- **Demandes réelles**, volume puis distincts : règle `0.403` / `0.326`, cadre
  `0.565` / `0.748`, cadre plus signal interrogatif `0.570` / `0.755`.
- **Triage** de ces demandes : `0.5598` du volume est unanime entre candidats et
  `0.0071` attend une étiquette humaine, donc l'arbitrage humain n'est pas le coût
  — l'atteinte l'est.
- **Voie publique** (Dolly-15k, tranches disjointes) : la règle couvre `0.75` à
  `0.79`, la récupération est la plus exacte (accord `0.72` à `0.75`, précision et
  rappel de champs autour de `0.69`).
- **Audit statique** : `45` fichiers dans `src/tiberium_ai`, tous `sound`, déficit
  moyen `4.18`, onze `rule.god-function`.

Ce qui n'est pas mesuré, et ne peut pas l'être en l'état : l'**exactitude**, faute
d'étiquettes d'issue ; le **coût** d'une route réelle, faute de baseline mesurée
sur les mêmes tâches ; et la **généralité** de la couverture, qui reste en
échantillon puisque le vocabulaire a été déclaré après lecture d'un recensement.

## Ouvert, par ordre d'intérêt

- **TASK-097** — ratifier le vocabulaire proposé (`vocabulary-to-ratify.json`) :
  une vingtaine de lignes, avec des candidats à rejeter mêlés (`true`, `sans`,
  `autre`, `puis`, `apres`, `oui`, `https`, `2026`). C'est un geste humain.
- **TASK-102** — remesurer la couverture sur une révision postérieure à
  l'artefact. Bloquée faute de contenu neuf dans la dernière ingestion : le
  critère reste valable, l'échantillon ne l'est pas encore.
- **TASK-087** — le vocabulaire de la classe `propose`, goulot mesuré d'un
  sixième du volume.
- **TASK-090 / TASK-088** — plancher par type de question, puis prolonger la
  courbe de mémoire pour trouver le palier.
- **Lacune connue** — le relevé de la voie réelle n'enregistre pas la révision
  qu'il a lue ; le nom du fichier ne remplace pas le champ.

Le reste des cartes ouvertes vit dans `kanban.md` : ce wiki ne les duplique pas.

## Pièges de reprise

- **Ne pas baser une branche sur `codex/static-audit`** : la PR correspondante est
  fusionnée et `main` a avancé, une telle branche apparaîtrait comme supprimant le
  démo `examples/flagship.py`.
- Les sorties de banc vont dans `runs/`, ignoré par git ; les révisions de corpus
  y vivent aussi et ne sortent jamais du poste.
- Les notes de `kanban.md` pour TASK-097 et TASK-102 citent la mesure d'avant la
  déclaration des verbes manquants (moins de 30 % du volume) ; l'état courant est
  celui du relevé daté.
- Un retour « delta identique » de l'ingestion n'est pas une erreur : c'est
  l'idempotence de la révision adressée par contenu.
