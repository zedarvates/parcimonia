# Reprise : domaines et profils d'exécution versionnés

- Demande : mettre en place les tags/versionnements discutés pour outils,
  skills et autres mécanismes dans Parcimonia.
- Ajouts : `src/tiberium_ai/execution_profiles.py`, `profiled_selection.py`,
  `examples/execution_profiles_pilot.py`, fixture de skill sous
  `examples/fixtures/skills/offline_table_review/SKILL.md`, trois fichiers de
  tests et `docs/EXECUTION_PROFILES.md`.
- Modification ciblée de `agent_recipes/recipes.py` : conserver la fiche
  optionnelle dans l'état de sélection ; comportement ancien conservé sans fiche.
  `docs/REGISTRY.md` relie la documentation du nouvel adaptateur.
- Schéma 1, taxonomie `execution-tags/1`, révision, hash octets source, hash de
  fiche et catalogue ; dépendances épinglées, traces d'arguments hachés et rejeu.
- Propriétés inconnues refusées si demandées ; toutes les expositions doivent
  être compatibles. Attestation hôte séparée pour les propriétés vérifiées.
  Métadonnées et propositions ne donnent jamais l'autorisation d'agir.
- Démonstration confirmée dans `runs/execution-profiles-20261020-v1` : catalogue
  relu, mode déclaratif 1 candidat, mode strict 0, rejeu identique. Aucune
  inférence réelle ou exécution du skill choisi ; tags de démonstration déclarés.
- Validation finale : 141 tests ciblés passés, incluant le parcours de
  dépendances borné. `git diff --check` sans erreur.
- Pas de migration automatique des catalogues installés, ni service modifié,
  ni commit. Nombreux travaux locaux antérieurs conservés.
- Suite : fiches revues pour capacités utilisées, contraintes d'appel réelles
  fournies par l'hôte, intégration de ces facettes au banc avant un éventuel SFT.
