# Reprise Parcimonia–REA/LeanREA — 28 octobre 2026

## Livré localement

- Modules : `src/tiberium_ai/re_investigation.py` et `re_investigation_bench.py`.
- CLI : `examples/prepare_re_investigation.py` et `compare_re_investigations.py`.
- Trois manifestes d'exemple `examples/fixtures/re_investigation_*.json` ; catalogue dédié avec empreintes des sources réelles.
- Documentation : `docs/RE_INVESTIGATION.md`.
- Tests : `tests/test_re_investigation.py` et `test_re_investigation_cli.py`.
- Les exports globaux et les modifications préexistantes du dépôt sont préservés. Aucun commit, publication ou installation globale du pilote.

Le pilote réutilise préparation, profils et continuité des fichiers existants.
Il propose trois décisions bornées : fichier à lire, prochaine analyse, preuve
manquante. Les contrats de décisions typées existants contrôlent capture/rejeu.
Les preuves sont séparées par cible, révision, propriété, scénario et niveau ;
les contradictions restent ouvertes. Les rapports ne donnent aucune autorité
d'exécution et ne certifient pas les artefacts déclarés par l'hôte.

## Vérifications

- 168 cas ciblés distincts réussis sur deux campagnes : adaptateur, CLI, reprise,
  contrats, profils et préparation. Première campagne 167 cas, puis six tests CLI
  dont cinq rejoués et un nouveau rejeu hors réseau.
- Exécution réelle de la CLI sur les sources Parcimonia : huit fichiers proposés,
  quatre exigences de preuve encore ouvertes.
- Reprise réelle de cette livraison avec revue enregistrée ; six puis sept
  artefacts relus et vérifiés par empreinte ; première livraison conservée.
- Exemple comparatif : trois fichiers attendus retrouvés sur huit propositions
  pour les bras règles et index réutilisé. Exemple écrit à la main ; aucune
  généralisation ni économie de temps sur une tâche indépendante démontrée.
- Aucun appel de modèle externe, entraînement, application cible ou publication.
- `git diff --check` passe ; vérification séparée des espaces des nouveaux fichiers.

Preuves locales : `runs/re-investigation-20261028/first/`, `followup/` et
`comparison/`. Bilan détaillé et JUnit dans
`C:/Users/redga/Documents/Codex/2026-10-28/gr-ce-toutes-les-discussions-employant/` :
`parcimonia-rea-delivery.json`, `parcimonia-rea-tests.xml`,
`parcimonia-rea-cli-tests.xml`.

## Limites et prochaine action

- Jev, modèle local et SFT restent `not_run`. Le transport est une dépendance
  explicitement injectée et versionnée ; aucun fournisseur n'est activé.
- Les prochains essais utiles portent sur un corpus indépendant BD Composer,
  Aion et Spore avec labels tenus hors du contexte du conseiller, et un coût
  mesuré jusqu'au résultat validé. Entraînement seulement si les erreurs
  résiduelles des baselines le justifient.
- Les anciennes erreurs des inspecteurs génériques du wiki ne sont pas corrigées
  par cet adaptateur. Il n'exécute pas ces outils et ne transforme pas leur
  diagnostic en preuve de disponibilité ou de réussite.
- Les empreintes du catalogue dédié doivent être réévaluées après changement
  d'une fonction source ; une modification de source peut demander une nouvelle
  revue ou une nouvelle révision de cible.
- Les sorties et éventuelles données privées restent sous `runs/`, sans publication.

## Coordination

La limite Odin a été portée à huit sur demande humaine explicite ; une seule
opération lourde reste autorisée. Version installée `v4-eight-417b7c5cbea2`,
huit tests de capacité/non-régression et six automatisations actives actualisées
sans changement d'horaire, de statut ou de destination. Les anciens reçus et
propriétaires incertains restent protégés ; aucun service partagé redémarré.

Reçu utilisé : `82fffbad53ac3c741ece1b262c5ec425`, propriétaire
`01a1831f-a23a-78c2-ba3c-b6cc9b9cc2cf`. Vérifier sa libération dans le bilan final.
Une prochaine reprise exige une observation fraîche et un nouveau reçu.
