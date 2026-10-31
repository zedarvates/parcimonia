# Reprise : analyse CLEF / GEV du 7 octobre 2026

- Livrable : `docs/ANALYSE_CLEF_GEV_2026-10-07.md` ; proposition, aucune intégration activée.
- Sources figées : CLEF `2f3de3dd85f379784083b0814d997ab627200f0c`,
  CLEF-Flash `17f0b0ad64efb65d273590632833508766b2aae6`,
  GEV `7c89590ead085bf77630b4bf68264ea30b6ddc78`.
- Preuves locales ignorées : `runs/research-clef-gev-20261007/` ; petits fichiers
  publics, manifeste des hashes, sondes synthétiques, agrégats et rejeux.
- Constats reproduits : Reflex perd les clés d’un mapping ; calibration d’une
  autre famille appliquée à une réponse ; tolérance aux arrondis différente entre
  transport TypeSafe et normaliseur Laya. Aucun résultat ne donne autorisation.
- Vérification : 65 tests ciblés passent. Rejeu des six fixtures : Laya 4/6,
  Jeff 5/6 types corrects acceptés, deux secours chacun. Pas d’inférence nouvelle.
- Limites : aucune qualité de CLEF/GEV mesurée localement ; corpus authored de
  six cas ; labels de champs ambigus ; économies et calibration générale inconnues.
- Fichiers de travail partagés préexistants conservés ; pas de modification du
  code de bibliothèque, pas de commit, pas de service ou GPU lancé.
- Prochaine action proposée : corriger liaison de calibration, JSON et arrondis,
  versionner les contrats ; clarifier les champs puis comparer sur test indépendant.
