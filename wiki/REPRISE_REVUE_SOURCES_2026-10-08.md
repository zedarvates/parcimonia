# Reprise : revue des sources reelles

- Demande : continuer apres le pilote attention/nouveaute ; preparer sources,
  contexte explicite, provenance et annotations independantes sans labels de modele.
- Ajouts : `agent_recipes/source_review.py`, `source_review_ui.py`,
  `examples/prepare_source_review.py`, `examples/finalize_source_review.py`,
  deux modules de tests Python et `tests/source_review_browser_checks.cjs`.
  Documentation : `docs/SOURCE_TRIAGE_REVIEW.md`, lien dans SOURCE_TRIAGE_PILOT.md.
- Captures preexistantes relues : quatorze fichiers, 111080 octets, trois lignages
  declares Cloudflare/clef, Cloudflare/clef-flash, autotrust/GEV-26B-Decide.
  Source : `runs/research-clef-gev-20261007/sources-manifest.json`.
  SHA-256 du manifeste :
  `625105a6e146551c883ebe99eae083e287bddf83c4bdbe7dbcc48384c10fc133`.
  Pins/URLs/hashes/tailles verifies ; aucun code externe execute, aucune collecte reseau.
- Dossier courant : `runs/source-triage/review-20261008-v3/` : review.html,
  review-packet.json, review-template.json, capture-provenance.json,
  comparison-readiness.json et manifeste des hashes. Les dossiers initial/v2
  restent conserves ; v3 inclut le retour a la ligne mobile et le JS verifie.
- Paquet : `f30e72aae9e77999fb8991bd6fa48129208bb9148b644299a9a7bddd2a82387f`.
  Quatorze cas, objectifs de protocole declares, sources et candidats complets,
  zero revue humaine et labels vierges. Candidats du meme snapshot : pas de preuve
  de connaissance anterieure de l'utilisateur ni de nouveaute au fil du temps.
- Preparation bornee : 32 fichiers, 64 KiB/fichier, 1 MiB cumule ; sortie nouvelle
  sous runs uniquement. Les octets des originaux ne sont pas modifies.
- Finalisation : annotations liees au hash de cas, auteur, justification,
  provenance/langue revues, relations explicites. Inconnus preserves. Split par
  lignages, contenus, candidats et evenements transitifs ; hashes des cas finaux.
  Identite declaree et completion ne certifient pas l'independance des labels.
- Verification : **1134 tests passent**, dont 36 nouveaux tests Python. Diff check
  et controle des espaces finaux passent. Aucune revendication de qualite/cout.
- Chromium isole : desktop 1366x900 et mobile 390x844, captures inspectees,
  aucun debordement, erreurs de page ou requete externe ; import/export,
  telechargement et persistence locale verifies.
  Preuves : `runs/source-triage/browser-checks-20261008-v2/`.
  Son export porte des annotations authored de test, jamais importe au dossier reel.
  Le premier essai navigateur a detecte le debordement mobile ; evidence initiale
  dans `browser-checks-20261008/`, aucun succes suppose pour ce premier essai.
- Porte reelle : human_review_incomplete, split_not_frozen,
  insufficient_labelled_heldout. Minimum de pilote : vingt cas de test etiquetes ;
  le lot de quatorze ne peut pas le satisfaire. Liens communs peuvent aussi rendre
  impossible un split source-disjoint ; ne pas les separer artificiellement.
- Aucun modele charge/appele, hook installe, route activee, service partage
  redemarre, publication ou commit. Travaux concurrents anterieurs conserves.
- Prochaine action : revue humaine dans le HTML courant et export JSON, puis
  finalisation via `examples/finalize_source_review.py`. Agrandir/diversifier le
  lot avec origines et cutoff explicites avant comparaison appariee des backends.
  Ne pas prendre l'export navigateur de test pour une revue humaine reelle.
