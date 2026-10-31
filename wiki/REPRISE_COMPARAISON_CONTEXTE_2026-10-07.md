# Reprise : audit d’entrée et porte de comparaison du contexte

- Aucun export de revue humaine trouvé dans `runs/` ni parmi les fichiers
  `context-review-*.json` de Téléchargements. Question de chemin posée ; labels
  réels non inventés. Le dossier original reste à zéro label.
- Contrôle navigateur désormais possible : le dossier original affiche 0/120.
  L’inspection a révélé des enveloppes de capture encore présentes dans le corpus.
- `context_input_audit.py` : audit versionné, détection de balises avec attributs,
  réponses d’interface, délégations, notices de navigateur et en-têtes de fichiers.
  Isolation conservatrice, sans réécriture des originaux ou labels. Une citation
  légitime d’un marqueur peut nécessiter une revue d’origine.
- Résultat : 114 cas candidats, six isolés ; originaux et source/provenance conservés
  dans `review-20261007-final/`. Nouveau lot et quarantaine dans
  `runs/signature-corpus/review-audited-20261007/`, ignoré par Git.
- `context_comparison.py` : garde revue/split/hashes, groupes et conversations
  disjoints, IDs d’entraînement hors test, labels connus vs inconnus, disponibilité
  des bras puis porte `route_experiment`. Aucun score, économie ou modèle appelé.
- Correction : `context_annotations.py` lie désormais les hashes aux cas finaux
  incluant leur affectation dev/test (`case_hash_scope=final_case_record/1`).
  Un test de régression a reproduit l’écart avant correction.
- `examples/context_comparison_pilot.py` prépare audit, lot, quarantaine,
  formulaire et refus de comparaison : split non figé, revue humaine et labels
  absents, captures du candidat non disponibles. Tous les scores restent nuls
  au sens de **non renseignés** (`null`), jamais des performances égales à zéro.
- Validation finale : **988 tests passent**, `git diff --check` passe. Sources
  antérieures contrôlées par hashes, sauf la correction ciblée des annotations.
- Nouveau formulaire vérifié par DOM dans le navigateur : 0/114, 114 lignes,
  identité et labels vierges, groupe de source non ratifié. Onglet marqué livrable.
  Serveur dédié `127.0.0.1:62748`, session d’exécution 6037, route `/review`.
  L’ancien serveur `127.0.0.1:50352` est conservé pour le dossier d’origine.
- Documentation : `docs/CONTEXT_COMPARISON.md`. Manifeste privé de l’incrément
  dans `runs/context-evaluation-20261007/completion-manifest.json`.
- Prochaine action dépendante : revue humaine du lot audité et des cas isolés,
  export JSON, finalisation du split puis captures appariées. Ne pas utiliser
  des labels du modèle évalué comme vérité indépendante. D’autres améliorations
  de contrat peuvent avancer sans prétendre que cette revue a été faite.
- Aucun commit, modèle chargé, routage activé, publication ou service partagé
  redémarré. Deux helpers locaux de revue, distincts des services partagés.
