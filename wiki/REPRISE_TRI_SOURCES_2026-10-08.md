# Reprise : pilote attention et nouveaute

- Demande : continuer l'analyse des videos Jev par le pilote local recommande.
- Module ajoute : `src/tiberium_ai/agent_recipes/source_triage.py`.
  Contrats stricts de source/contexte, attention.triage@1, knowledge.novelty@1,
  recherche lexicale sur snapshot fourni, source.recipe.structure@1.
- Integration : exports et commandes `attention`, `novelty`, `source-search`
  ajoutes aux fichiers existants `agent_recipes/__init__.py` et `__main__.py`.
  Le manifeste des neuf recettes precedentes et leur verifier restent compatibles.
- Corpus synthetique ajoute : `examples/fixtures/source_triage.json`, douze cas
  authored, reponses injectees, annotations non independantes.
- Pilote ajoute : `examples/source_triage_pilot.py`. Baseline process-all et
  candidat mesures sur memes hashes d'entree ; verification structurelle et
  conservation des originaux. Pas de generation observee.
- Rapport local ignore : `runs/source-triage/pilot-20261008.json`.
  Douze cas, six process, quatre defer, deux skip_candidate, douze originaux
  recuperables, quinze appels de backend fixture ; aucune source supprimee.
  Aucun des dix cas declares must_retain par l'auteur n'est propose a l'ecartement.
- Qualite et economies restent null ; model_inference_executed=false,
  claim_allowed=false, auto_act_allowed=false. Les compteurs ne mesurent pas
  une precision de modele ni des appels LLM effectivement economises.
- Tests ajoutes : `tests/test_source_triage.py`, `tests/test_source_triage_pilot.py`.
  Verification complete : `rtk proxy .venv/Scripts/python.exe -m pytest -q` :
  **1098 tests passent**. `git diff --check` et controle des espaces finaux passent.
  Le JSON du rapport a ete relu : douze verificateurs de politique passent,
  metriques qualite/cout non renseignees, aucune inference modele.
- Documentation : `docs/SOURCE_TRIAGE_PILOT.md`, lien ajoute a AGENT_RECIPES.md.
- Les sources protegees ne sont pas proposees a l'ecartement dans la politique
  composee ; un doublon sur une shortlist limitee est reporte. Aucun candidat
  signifie uncertain, jamais preuve de nouveaute. Les mises a jour et contradictions
  restent traitables ; les sources et objectifs sont dans les etats transmis.
- Limites : recherche lexicale, aucune garantie de rappel semantique, seuils non
  calibres, confiance declaree par backend, verifier structurel seulement,
  temps locaux hors generation/facturation/energie. Deadline sans preemption.
- Travail local non commite. Modifications concurrentes anterieures conservees.
  Aucun hook, poids, nouveau compte payant, activation de route, publication,
  service partage ou configuration globale modifies.
- Prochaine porte : sources reelles et contextes explicites pour ces familles,
  labels independants sans reponses candidates visibles, groupes d'evenements/
  versions et split developpement-test. Comparer baseline/regles/backend disponible,
  avec captures, verificateurs et cout de chaine complet. Les 114 demandes de
  signature existantes sont un chantier d'annotation distinct, non relabelle ici.
