# Conseiller de calcul local et plugin Parcimonia Local

La candidate 0.4.0 reconnaît `log_compact` et partage le plafond MCP de 1 Mio
par requête/réponse. La nouvelle tâche requiert les mêmes preuves de qualité,
fraîcheur et ressources ; elle ne donne aucune autorisation d'exécution.

Depuis la candidate 0.2.0, `parcimonia_local_context` ajoute la proposition de
fichiers utiles et un cache de dérivations vérifiées par hash. Botte fournit la
lecture locale bornée de sources explicitement désignées. Voir
[sélection de contexte](CONTEXT_SELECTION.md) pour les mesures et limites.

`src/tiberium_ai/local_compute.py` ajoute `advise(request, snapshot, candidates)`.
La fonction produit une proposition sans importer, lancer ou autoriser une route.
Elle ne modifie pas les contrats d'exécution ni les profils existants.

Le plugin indépendant est dans `plugins/parcimonia-local/`. Ses outils sont
`parcimonia_local_hardware` et `parcimonia_local_plan`. Les sources minimales
embarquées sont liées à leur origine par `SOURCES.json` et `FILES.json`.
Python 3.10+ accessible sous `python` reste requis ; aucune dépendance pip.

## Contrat

- `request` : tâche, SHA-256 exact de la charge, objectif `latency` ou `cloud_spend`, budget de latence éventuel.
- `snapshot` : observation de moins de 60 secondes, clé matérielle, RAM et engagement libres, disque libre sur le volume du plugin, liste des VRAM libres, disponibilité du créneau lourd.
- `candidates` : au plus 32 routes, statut explicite, mémoire incrémentale incluant le chargement, état chaud/froid et mesure liée à la charge.
- `measurement` : même charge, même matériel local, date de moins de 24 heures, au moins trois essais tous réussis, vérificateur nommé, p50/p95 et coût de démarrage, dépense cloud déclarée ou inconnue.

Les mesures sont des rapports de l'hôte, sans attestation indépendante dans cette
version. `evidence_trust` le rappelle. Elles ne constituent aucune autorisation.
Ne pas transformer ce conseiller en filtre strict d'exécution sans utiliser les
attestations et les contrats existants de Parcimonia.

Réserves après la charge proposée : 5 Gio de RAM, 6 Gio d'engagement, 15 Gio de
disque. La VRAM de cartes distinctes n'est pas additionnée. Le créneau lourd
inconnu bloque les propositions lourdes. Le plugin ne connaît pas le registre
Odin et ne réserve rien. Les NPU restent non qualifiés par ce collecteur.

Le coût d'électricité et le gain de tâche global restent inconnus. L'objectif
`cloud_spend` compare exclusivement une dépense cloud déclarée ; il ne compare
pas le coût total. Le temps proposé est la somme du p95 observé et du démarrage
déclaré, pas un percentile bout en bout établi statistiquement.

## Preuves du 29 octobre 2026

Dossier de construction, archives, tests JUnit et bancs :
`C:/Users/redga/Documents/Codex/2026-10-29/goal-d-velopp-et-am-liorer/`.

Le banc synthétique relie les vraies mesures Botte au conseiller. Un second banc
porte sur la syntaxe de 12 sources existantes ; il distingue Python lancé par
fichier, Python traitant le lot, premier passage MCP et répétition via cache.
La bascule locale n'est pas systématiquement plus rapide au premier passage.
Ce ne sont ni des labels de qualité de développement ni des preuves GPU/LLM.

Schémas portables validés contre leurs schémas déclarés ; installation avec la
CLI Codex et lecture native `plugin/read` dans un CODEX_HOME isolé. Cette lecture
déclare bien le MCP ; aucun appel de l'outil dans une nouvelle conversation
Codex équipée n'est encore établi. Les outils stdio extraits sont testés séparément.

## Publication

Candidate locale, aucune publication. Voir `plugins/parcimonia-local/PUBLICATION.md`.
La documentation OpenAI consultée réserve la soumission publique des MCP locaux
aux organisations autorisées. Éligibilité, identité, pages publiques de support,
confidentialité/conditions et parcours natifs restent à qualifier.
https://developers.openai.com/plugins/deploy/desktop-only
