# Reprise : provenance et atelier de revue indépendante

- Provenance retrouvée pour les 120 demandes : 141 occurrences, 98 conversations,
  89 composantes de source. SQLite utilisateur indexé retrouve 116 cas ; sept lignes
  anciennes retrouvent les quatre autres. Contrôle exact du texte nettoyé et de
  la borne temporelle du corpus, bases d’historique ouvertes en lecture seule.
- Le premier repli a lu 786 fichiers / 6,34 Go. Ne pas le répéter : les locateurs
  exacts sont dans `runs/context-provenance-20261007/probe-matches.json` et
  `probe-missing.json`. `prepare_context_review.py` relit uniquement ces locateurs.
- Livrables privés : `runs/signature-corpus/review-20261007-final/` contient
  `review.html`, `review-packet.json`, `provenance.json`, manifeste de hashes.
  Le paquet initial est conservé ; aucun prompt réel n’est dans les fichiers suivis.
- Nouveaux modules : `context_provenance.py`, `context_annotations.py`,
  `context_review_ui.py`. Scripts : préparation, finalisation et serveur local.
- Formulaire : annotations vierges, sources visibles, inconnu distinct d’aucun,
  auteur par cas, groupes manuels de paraphrases, recherche, sauvegarde navigateur,
  import/export JSON. Aucun label de modèle ou réponse d’assistant affiché.
- Dossier réel : zéro label, groupes non ratifiés, aucun split figé. Zéro paire
  proposée par le filtre lexical conservateur ; cela ne prouve pas l’absence
  de paraphrases. Les groupes manuels restent à établir lors de la revue humaine.
- Validation : **972 tests passent**, dont logique JS sur DOM synthétique.
  Sources des incréments précédents conservées par contrôle de hashes ;
  `git diff --check` passe. Import/finalisation refusent une revue incomplète.
- Prévisualisation : serveur dédié à `127.0.0.1:50352`, session d’exécution 42637,
  URL `/review`, route `/fixture` pour les tests synthétiques ; aucun endpoint
  d’écriture. Contenu HTTP identique au fichier vérifié. Copie HTML hors ligne
  disponible. Ne pas confondre avec un service partagé.
- Limite : contrôle interactif CUA indisponible (timeout puis détachement).
  Pas de preuve de rendu visuel ou téléchargement dans un navigateur réel.
- Documentation : `docs/CONTEXT_INDEPENDENT_REVIEW.md`. Preuves agrégées dans
  `runs/context-provenance-20261007/completion-manifest.json`.
- Prochaine action : l’annotateur humain examine les sources, langue, groupes,
  contexte, labels et justifications ; exporte sa revue. Ensuite importer via
  `examples/finalize_context_review.py`, figer le split et préparer la comparaison.
  La provenance, une identité saisie ou un split ne certifient pas la qualité.
- Aucun commit, inférence nouvelle, publication, routage activé ou redémarrage
  de service partagé. Le serveur de revue est le seul helper local lancé.
