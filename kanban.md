# Parcimonia Kanban Backlog

Dernière mise à jour : 2026-09-21T00:00:00Z
Mode : Local-First / Résilient (compatible Kanboard Neo et autonome)

## Terminé

- [x] TASK-G1 [P0] [difficulté: déterministe]
  - Intitulé : Baseline measurements & provenance (G1)
  - Reçu : 40 runs enregistrés dans examples/fixture_suite.py

- [x] TASK-G2 [P0] [difficulté: déterministe]
  - Intitulé : Deterministic verifiers (G2)
  - Reçu : shape, exact match, runner result verifiers

- [x] TASK-G3 [P0] [difficulté: déterministe]
  - Intitulé : Escalation budgets and hard stops (G3)
  - Reçu : Budget, EscalationPolicy, EscalationState

- [x] TASK-G4 [P0] [difficulté: déterministe]
  - Intitulé : Route registry and capability manifests (G4)
  - Reçu : RouteManifest, RouteRegistry, candidate filtering

- [x] TASK-G5 [P0] [difficulté: déterministe]
  - Intitulé : Resource vectors and Pareto front (G5)
  - Reçu : ResourceVector (tokens, latency, vram, energy), pareto_front

- [x] TASK-G6 [P0] [difficulté: compact]
  - Intitulé : Active mode with sandbox and kill switch (G6)
  - Reçu : ActiveRouter, ActivePolicy, Sandbox, KillSwitch

- [x] TASK-050 [P0] [difficulté: compact]
  - Intitulé : ContinuationArbiter pour Astral Resonance Director
  - Reçu : Arbitrage sur quotas, difficulté, arrêts consécutifs et WebBrain MCP
  - Preuve : tests/test_continuation.py

- [x] TASK-051 [P1] [difficulté: compact]
  - Intitulé : Parser et ordonnanceur local-first kanban.md
  - Reçu : KanbanBoard, KanbanTask, dépendances DAG sans dépendance externe
  - Preuve : tests/test_kanban.py

- [x] TASK-052 [P1] [difficulté: compact]
  - Intitulé : Pont d'ingestion miroir vers Kanboard Neo
  - Reçu : kanban_to_jobs_payload, export_kanban_mirror, sync_kanban_mirror
  - Preuve : tests/test_kanban.py

- [x] TASK-053 [P0] [difficulté: compact]
  - Intitulé : Implémentation complète de l'Astral Resonance Director
  - Reçu : AstralDirector, DirectorCounters, DirectorMode, DirectorProposal
  - Preuve : tests/test_director.py

- [x] TASK-054 [P1] [difficulté: compact] [outil: webbrain]
  - Intitulé : Intégration adaptateur WebBrain MCP pour actions navigateur
  - Reçu : WebBrainClient, WebBrainCommand, WebBrainResult, build/parse MCP
  - Preuve : tests/test_webbrain.py

- [x] TASK-055 [P2] [difficulté: raisonnement]
  - Intitulé : World Model d'interface prédictif (JEPA-like action gate)
  - Reçu : StateVector, ActionDescriptor, JEPAActionGate, loop & anomaly pruning
  - Preuve : tests/test_world_model.py

- [x] TASK-056 [P2] [difficulté: compact]
  - Intitulé : Scénario d'intégration bout-en-bout (Director + Router + WebBrain + WorldModel)
  - Dépendances : TASK-055
  - Reçu : ContinuityPipeline, TimeBudget, reflex advisory, schema emit, no network
  - Preuve : tests/test_pipeline.py

- [x] TASK-057 [P3] [difficulté: compact]
  - Intitulé : Documentation synthétique dans docs/INTEGRATIONS.md
  - Dépendances : TASK-056
  - Reçu : couches Director / reflex / schema emit / WebBrain, ce qui reste hors scope

- [x] TASK-058 [P2] [difficulté: compact]
  - Intitulé : Calibration mesurée du reflex sur des tâches Parcimonia labellisées
  - Dépendances : TASK-056
  - Reçu : corpus fixture, HintReflexBackend, coverage/Brier, data_origin=fixture fail-closed
  - Preuve : tests/test_reflex_calibrate.py

- [x] TASK-063 [P1] [difficulté: compact]
  - Intitulé : Surface projet, rapport d'usage fin de tour, plan runtime ombre
  - Dépendances : TASK-056
  - Reçu : ProjectSurface, compare_usage, plan_runtime START/IDLE/STOP shadow
  - Preuve : tests/test_surface.py

- [x] TASK-059 [P3] [difficulté: compact]
  - Intitulé : Backend reflex local optionnel (sans téléchargement tant que non autorisé)
  - Dépendances : TASK-058
  - Reçu : probe_optional_local_backend, never download, available stays false
  - Preuve : tests/test_reflex_local.py

- [x] TASK-062 [P3] [difficulté: compact]
  - Intitulé : Capacité locale (VRAM / slots concurrents) dans ContinuationArbiter
  - Dépendances : TASK-056
  - Reçu : LocalCapacity, compact/MCP blocked, frontier still allowed, plan START withheld
  - Preuve : tests/test_continuation.py, tests/test_surface.py

- [x] TASK-064 [P2] [difficulté: compact]
  - Intitulé : Ingest rapport d'usage fin de tour (skills/tools/MCP) vers UsageEvent
  - Dépendances : TASK-063
  - Reçu : ingest_turn_report schema turn_usage, no UI scrape
  - Preuve : tests/test_surface.py

- [x] TASK-065 [P1] [difficulté: compact] [class: feature] [horizon: near]
  - Intitulé : Roadmaps classées sécu/bug d'abord, vues court/moyen/long, plan du jour avec report
  - Dépendances : TASK-051
  - Reçu : WorkClass/Severity/Horizon, plan_day, close_day, export_roadmap_views
  - Preuve : tests/test_roadmap.py

- [x] TASK-066 [P1] [difficulty: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitule : Buts ultimes humains pour l orchestration (buts.md)
  - Dependances : TASK-065
  - Recu : GoalSet, rank fail-closed, tag [goal:], plan_day goal_ranks
  - Preuve : tests/test_goals.py

- [x] TASK-067 [P1] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Route System-1 d'audit statique (rôles de fichier, règles nommées, score, store local)
  - Dépendances : TASK-065
  - Reçu : source_scan / source_role / pattern_rules / audit_score / audit_store / audit, vérificateur audit.recompute, entrée de manifeste sans coût inventé
  - Preuve : tests/test_source_scan.py, tests/test_source_role.py, tests/test_pattern_rules.py, tests/test_audit_score.py, tests/test_audit_store.py, tests/test_audit.py, examples/audit_suite.py
  - Notes : shadow only, aucun modèle appelé ; poids et seuils non calibrés, aucun routage gaté par ce score

- [x] TASK-070 [P2] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Corpus labellisé et harnais de calibration de l'audit statique
  - Dépendances : TASK-067
  - Reçu : audit_corpus.py (31 cas, rôles/bandes/règles attendus), audit_calibrate.py (défauts par règle, precision/recall, accord rôle/bande/règle), examples/audit_calibration.py
  - Preuve : tests/test_audit_calibrate.py ; 31 cas, accords 1.0, precision/recall 1.0 pour les 5 règles
  - Notes : provenance fixture ; threshold_authorized=false et impossible à forcer hors données mesurées ; les 3 faux positifs de développement ont des contrôles négatifs dédiés

- [x] TASK-071 [P1] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Contrat de route décision typée : options larges en deux étages, enregistrement/rejeu, horloge de décision
  - Dépendances : TASK-067
  - Reçu : decision_adapter.py (OptionSetQuestion, plan_two_stage, stage_questions, compose_two_stage, DecisionRequest/Record/Replay/Capture, capture_decision, replay_decision, two_stage_verifier, decision_route_entry) et decision_clock.py (DecisionBudget, DecisionTiming, TimingVerdict, assess_decision_timing)
  - Preuve : tests/test_decision_adapter.py, tests/test_decision_clock.py, examples/decision_suite.py ; 50 tests ; 556 tests préexistants toujours verts
  - Notes : contrat de route, pas une nouvelle porte V1 ; le plafond de 20 options par question reste, les ensembles larges passent par le plan à deux étages ; 255 options maximum, au-delà refus ; le transport est injecté, la bibliothèque ne fait aucun I/O réseau ; aucun modèle appelé et aucun coût déclaré

- [x] TASK-073 [P1] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Décision scorée option par option, vérificateurs de schéma et de score, fichier de record
  - Dépendances : TASK-071
  - Reçu : plan_scored_stages / scored_stage_questions / finalist_question / compose_scored / scored_verifier ; schema_verifier ; two_stage_payload / scored_payload / schema_payload ; write_decision_record / read_decision_record ; batched_round_trips et stage_calls sur les deux plans
  - Preuve : tests/test_decision_scored.py (35 tests), tests/test_decision_adapter.py, examples/decision_suite.py (28 options = 1 appel de score, 2 allers-retours batchés, revendication recalculée acceptée, revendication falsifiée rejetée, schéma accepté) ; 641 tests verts au total
  - Notes : le budget fait maintenant partie de l'identité de la requête, donc un record capturé sous une autre échéance n'est pas rejoué ; un score manquant reste une abstention, jamais zéro ; le mode scoré et le mode groupé coexistent ; aucune route gatée par ces verdicts

- [x] TASK-075 [P1] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Harnais de mesure élargi : comparaison à N routes, agrégation des quatre dimensions, claim par candidat et front
  - Dépendances : TASK-070
  - Reçu : BenchmarkRoute.resources (vecteur ou callable évalué après le run), BenchmarkCase à au moins deux routes avec candidate_route_ids, build_report qui agrège une médiane par dimension mesurée (tokens arrondis à l'entier), claim avec allowed/front/evaluated, REPORT_SCHEMA_VERSION 2
  - Preuve : tests/test_benchmark.py (25 tests, dont une économie de tokens déclarable, une dimension inconnue non comptée comme un gain, un compromis réel rendu comme un front), examples/benchmark_suite.py inchangé et toujours vert ; 652 tests au total
  - Notes : aucune affirmation nouvelle ne porte sur les fixtures, qui n'instrumentent pas les tokens ; une déclaration de ressources doit être réellement observée, sinon elle entre dans le record comme une mesure

## En cours

- [ ] TASK-060 [P3] [difficulté: compact] [class: feature] [horizon: near]
  - Intitulé : Round-trip WebBrain MCP réel en ASK only
  - Dépendances : TASK-054
  - Notes : observation-only, loopback, pas d'ACT

## À faire (Backlog)

- [ ] TASK-109 [P2] [difficulté: raisonnement] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Comparaison contrôlée des routes Astra/LLM, jugement Jev-like, Needle-like, règle et KNN sur les mêmes tâches
  - Dépendances : TASK-075, TASK-102
  - Notes : protocole et matrice dans docs/ASTRA_JEV_NEEDLE_RESEARCH.md ; mesurer séparément mécanisme, vérification, temps, coût total et abstentions ; aucun appel quota-bearing ni téléchargement de poids n'est compris dans cette carte

- [ ] TASK-110 [P3] [difficulté: raisonnement] [class: feature] [horizon: long] [goal: GOAL-PARCIMONIA]
  - Intitulé : Évaluer une piste géométrique sur des représentations accessibles et un test de perturbation apparié
  - Dépendances : TASK-109
  - Notes : distinguer étude des activations publiée et revendication Sophontic ; pas de modèle ou d'activation accessible confirmé pour notre stack ; cette carte est une hypothèse de recherche, pas une route admise

- [ ] TASK-068 [P1] [difficulté: raisonnement] [class: feature] [horizon: near]
  - Intitulé : Calibration mesurée de l'audit statique sur fichiers réels (labels humains)
  - Dépendances : TASK-070
  - Notes : la partie corpus fixture est faite (TASK-070) ; il reste des labels humains sur du code réel ; snapshot data_origin mesuré seulement ; aucun seuil ne gate l'exécution avant ce snapshot

- [ ] TASK-069 [P2] [difficulté: raisonnement] [class: feature] [horizon: medium] [goal: GOAL-PARCIMONIA]
  - Intitulé : Route baseline modèle sur la même question (comparaison de coût honnête)
  - Dépendances : TASK-067, TASK-068
  - Notes : sans baseline mesurée, aucune économie n'est déclarable ; la comparaison se fait sur le vecteur de ressources, pas sur un score scalaire

- [ ] TASK-072 [P2] [difficulté: compact] [class: feature] [horizon: medium] [goal: GOAL-PARCIMONIA]
  - Intitulé : Un appel réel autorisé à un backend de décision typée, enregistré comme record rejouable
  - Dépendances : TASK-071
  - Notes : quota-bearing ; nécessite une autorisation explicite avant tout appel ; transport injecté seulement, aucune clé dans le dépôt ; la réponse devient un record committé et rejoué par examples/decision_suite.py ; aucune économie déclarable avant une baseline mesurée sur les mêmes tâches

- [ ] TASK-074 [P2] [difficulté: raisonnement] [class: feature] [horizon: medium] [goal: GOAL-PARCIMONIA]
  - Intitulé : Backend de décision local documenté (endpoint de décision llama.cpp ou petit modèle ouvert) derrière autorisation explicite
  - Dépendances : TASK-072
  - Notes : toutes les pistes sont tierces et non vérifiées ici (licences annoncées Apache-2.0 et MIT) ; aucun poids téléchargé et aucune branche compilée sans décision explicite ; le point d'injection, le format de capture et le lecteur de record existent déjà, donc l'appel se convertit mécaniquement en fixture rejouable ; la calibration locale resterait à mesurer avant tout auto-act

- [ ] TASK-076 [P2] [difficulté: raisonnement] [class: feature] [horizon: medium] [goal: GOAL-PARCIMONIA]
  - Intitulé : Corpus réel de tâches avec ressources instrumentées (tokens, VRAM, énergie)
  - Dépendances : TASK-075, TASK-069
  - Notes : sans ressources réellement mesurées, les dimensions tokens/VRAM/énergie restent nulles et aucune économie de ce type n'est déclarable ; c'est le préalable à toute comparaison « mécanisme le moins cher qui vérifie » sur des tâches réelles plutôt que sur des fixtures

- [x] TASK-077 [P1] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Signature de tâche : contrat de descripteur prédit, baseline mots-clés et harnais de calibration
  - Dépendances : TASK-071
  - Reçu : SignatureSchema/DeclaredItem (vocabulaire déclaré, plafond 20 types, option none réservée), signature_questions sur le contrat reflex, RuleBasedSignatureBackend (aucun modèle, aucun réseau), TaskSignature avec provenance et abstention comme valeur, calibrate_signatures (couverture, accord de type, précision/rappel de champs, accord de but)
  - Preuve : tests/test_task_signature.py (28 tests, dont « une fixture parfaite ne peut pas autoriser » et « un instantané autorisé ne peut pas être forgé depuis une fixture »), 680 tests au total
  - Notes : le prédicteur est un ReflexBackend, donc un KNN ou un micro-NN se substitue sans changer le contrat ; risque, niveau de preuve et localité ne sont pas prédits (un prompt est une preuve faible et l'erreur irait dans le sens non sûr) ; aucun but n'est inventé, un but non reconnu reste none

- [ ] TASK-078 [P2] [difficulté: raisonnement] [class: feature] [horizon: medium] [goal: GOAL-PARCIMONIA]
  - Intitulé : KNN (ou micro-NN) comme backend de signature, mesuré contre la baseline mots-clés
  - Dépendances : TASK-077, TASK-076
  - Notes : la mémoire du KNN est déjà le format des records de décision (rejouer = entraîner) ; les k plus proches moyennent leurs distributions de réponses, puis les mêmes seuils fail-closed s'appliquent ; promotion seulement si l'accord et la couverture battent la règle sur des issues labellisées, jamais sur des fixtures

- [x] TASK-079 [P1] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Corpus de signatures authoré (moitié alignée, moitié paraphrase) et règle de provenance des étiquettes
  - Dépendances : TASK-077
  - Reçu : signature_corpus.py (24 cas + schéma d'exemple avec hints) ; SignatureCase.situations_origin et label_origin ; labeler_id et independent sur le rapport ; data_origin dérivé des cas au lieu d'être passé en argument
  - Preuve : tests/test_signature_corpus.py (12 tests) ; moitié alignée couverture 1.000 et accord 1.0 ; moitié paraphrase couverture 0.250 et accord 0.0, dont 3 réponses fausses par collision de hints ; agrégat 0.625 / 0.8 qui flatte la règle ; auto-étiquetage refusé même avec des scores parfaits
  - Notes : un LLM peut produire les hints et les étiquettes, mais la mesure devient alors un contrôle d'auto-cohérence ; le rapport porte labeler_id et refuse l'autorisation quand l'étiqueteur est le prédicteur ; les capacités prédites sont enregistrées mais pas encore notées par le harnais

- [x] TASK-080 [P1] [difficulté: raisonnement] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Cadre verbe+objet et backend de récupération KNN, mesurés sur le banc aligné/paraphrase
  - Dépendances : TASK-079
  - Reçu : signature_backends.py (lexique verbal général anglais/français, normalisation sans accents, spans objet/adjoints, pondération par position, VerbFrameSignatureBackend, KnnSignatureBackend à similarité Jaccard, memory_from_cases) et examples/signature_bench.py
  - Preuve : tests/test_signature_backends.py (22 tests) ; hors distribution le cadre passe de 0.25 à 0.75 de couverture et de 0.0 à 0.667 d'accord, supprime le champ deadline inventé par la règle (précision 0.0 vers aucun champ prédit), garde la moitié alignée intacte (1.000 / 1.0) ; le KNN est exact sur la moitié qu'il a mémorisée (accord 1.0, couverture 0.583) et quasi muet sur l'autre (couverture 0.167)
  - Notes : le cadre transporte l'acte mais pas le vocabulaire (rappel de champs 0.0 sur les paraphrases françaises) ; les 3 désaccords restants portent sur mes propres étiquettes, discutables ; un auto-appariement exact est dilué à 0.625 par deux voisins qui ne partagent que le vocabulaire du sujet, donc la métrique est le maillon faible, pas la stratégie

- [ ] TASK-081 [P2] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Alimenter le backend de récupération avec les spans du cadre au lieu des tokens bruts
  - Dépendances : TASK-080
  - Notes : la dilution d'un auto-appariement à 0.625 vient d'une similarité par tokens qui ne distingue pas « même tâche » de « même sujet » ; les spans (action, objet, adjoints) sont déjà la bonne représentation, donc la métrique devrait porter dessus ; à mesurer contre le KNN par tokens sur les mêmes cas tenus à l'écart

- [ ] TASK-082 [P3] [difficulté: compact] [class: bug] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Revoir les 3 étiquettes discutables du corpus de paraphrases
  - Dépendances : TASK-080
  - Notes : « check the spelling » étiqueté format, « reformat the options before deciding » étiqueté decide, « tidy the report then confirm it » étiqueté verify : le cadre donne respectivement verify, format, format, ce qui est défendable ; à trancher à la main, et à ne pas « corriger » pour faire gagner un candidat

- [x] TASK-083 [P1] [difficulté: raisonnement] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Voie publique : mesurer les trois candidats sur des instructions bien formées à étiquettes extérieures
  - Dépendances : TASK-080
  - Reçu : origine de situations « public » (avec la même porte fermée), lexique verbal étendu depuis les noms de catégories, public_corpus.py (mapping déclaré catégorie vers type, schéma, construction des cas, découpage mémoire/évaluation) et examples/public_lane.py (récupère 400 lignes Dolly-15k, CC-BY-SA-3.0, et mesure sur 300 cas disjoints de 100 en mémoire)
  - Preuve : tests/test_public_corpus.py (8 tests) ; sur les 300 cas tenus à l'écart : couverture 0.737 règle / 0.223 cadre / 0.277 KNN, accord 0.715 / 0.597 / 0.723, précision-rappel de champs 0.333-0.081 / 0.188-0.136 / 0.6-0.562 ; data_origin reste fixture et rien n'est autorisé
  - Notes : le résultat inverse le banc authoré, parce que 172 des 300 instructions publiques sont des questions et qu'un cadre piloté par le verbe n'a pas de verbe à lire dans une question ; le KNN gagne en qualité grâce à une mémoire étiquetée de même distribution, ce qui n'existe pas encore sur du travail réel ; les verbes à particule (« come up with », « give me ») échappent à un cadre par tokens

- [x] TASK-084 [P2] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Signal interrogatif pour la classe « answer », mesuré sur une tranche publique neuve
  - Dépendances : TASK-083
  - Reçu : INTERROGATIVE_MARKERS (anglais et français, auxiliaires compris car ils ne sont pas dans le lexique verbal, donc ils ne peuvent se déclencher que faute de verbe tête) et le drapeau interrogative_signal sur le cadre, plus la tranche d'évaluation découplée de la mémoire dans examples/public_lane.py
  - Preuve : tests/test_signature_backends.py (6 tests, dont l'invariance du banc authoré et le témoin signal éteint) ; sur 400 cas jamais lus : classe answer couverture 0.105 vers 0.850 (règle 0.800), exactitude 0.953 contre 0.963 ; couverture globale 0.268 vers 0.825 (règle 0.750) ; accord global 0.486 vers 0.609 (règle 0.630)
  - Notes : la prédiction pré-enregistrée est confirmée sur sa cible ; l'effet de bord est mesuré : le repli se déclenche sur des questions qui ne sont pas des demandes de réponse, propose vers answer passe de 3 à 23 et generate vers answer de 3 à 15, et le rappel de champs tombe de 0.114 à 0.049 ; deux tranches donnent à la règle 0.737-0.715 puis 0.750-0.630, donc quelques points d'écart ne sont pas un classement

- [x] TASK-086 [P2] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Départage par spécificité : un hint déclaré précis bat un marqueur interrogatif générique
  - Dépendances : TASK-084
  - Reçu : drapeau specificity_tie_break et tableau _specific_kind (le hint le plus long gagne, un hint interrogatif ne compte pas comme spécifique, une égalité s'abstient), plus le troisième bras du cadre dans examples/public_lane.py
  - Preuve : tests/test_signature_backends.py (5 tests de plus, 33 au total dans ce fichier) ; sur la tranche 800-1199 jamais lue : prédiction NON confirmée, propose reste à 0 justes sur 37 réponses dans les deux bras, generate reste à 9 sur 17, la classe answer perd 7 réponses justes et l'accord global passe de 0.638 à 0.618
  - Notes : le départage est inerte plutôt que faux, il n'agit que sur un hint qui matche et presque aucune instruction de brainstorming de la tranche n'en contient, donc le goulot est le vocabulaire déclaré de cette classe ; le drapeau est désactivé par défaut car non prouvé, et conservé comme bras reproductible ; ce qui réplique sur trois tranches : signal 0.825 puis 0.850 de couverture, règle 0.75-0.79, KNN le plus exact (0.723, 0.750, 0.734 d'accord, précision et rappel de champs proches de 0.69)

- [ ] TASK-087 [P1] [difficulté: raisonnement] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Vocabulaire déclaré de la classe « propose », goulot mesuré d'un sixième du corpus
  - Dépendances : TASK-086
  - Notes : propose reste à 0-1 juste sur 42 à 49 cas selon les tranches, chez les trois candidats, ce qui n'est pas un défaut de mécanisme mais de vocabulaire ; les hints doivent être écrits depuis la sémantique de la catégorie (proposer des options, des pistes, des possibilités, des variantes) et depuis l'usage général, jamais en lisant les instructions des tranches 0-1199 qui sont désormais connues ; mesure sur la tranche 1200-1599 avec prédiction annoncée d'avance : propose doit dépasser les deux tiers de justes parmi ses réponses, sinon la classe est à redéfinir ou la catégorie publique est mal formée pour ce type

- [x] TASK-085 [P2] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Courbe de la qualité KNN en fonction de la taille de la mémoire étiquetée
  - Dépendances : TASK-083
  - Reçu : mode --seed-curve dans examples/public_lane.py (sous-ensembles imbriqués de la mémoire, tranche d'évaluation non lue, règle et cadre en référence sur les mêmes cas)
  - Preuve : sur la tranche 1200-1599 jamais lue, 400 cas : couverture 0.155 / 0.237 / 0.302 / 0.355 et accord 0.694 / 0.621 / 0.686 / 0.725 pour 25 / 50 / 100 / 200 exemples étiquetés, contre 0.730-0.709 (règle) et 0.833-0.649 (cadre) ; précision et rappel de champs passent de 0.462-0.545 à 25 exemples à 0.629-0.629 à 200
  - Notes : prédiction à moitié confirmée et la moitié qui échoue est la plus instructive, l'accord n'est pas monotone (creux à 50) donc une petite mémoire répond juste sur un sous-ensemble facile puis se charge de cas plus durs avant d'avoir assez de voisins ; la récupération n'est un instrument de précision, jamais de couverture (un tiers des cas contre sept ou huit sur dix) ; rien n'a plafonné à 200, donc cette courbe dit où la récupération commence à gagner, pas où elle s'arrête ; aucun test unitaire ajouté, c'est un chemin d'expérience dans l'exemple et la mesure est la preuve

- [ ] TASK-088 [P3] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Prolonger la courbe de mémoire à 400 et 800 pour trouver le palier
  - Dépendances : TASK-085
  - Notes : la courbe monte encore à 200, donc « combien d'exemples » n'a pas de réponse plafonnée ; une seule exécution sur une tranche neuve (1600-1999) avec les mêmes sous-ensembles imbriqués suffit ; à ne pas confondre avec un réglage, la taille retenue devra être validée sur une tranche ultérieure

- [x] TASK-089 [P1] [difficulté: raisonnement] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Route à deux étages : récupération quand elle répond, règle ou cadre sinon
  - Dépendances : TASK-085, TASK-086
  - Reçu : LayeredSignatureBackend (décision par question, primaire retenu si sa certitude atteint le plancher, un non confiant comptant comme une certitude), monté dans examples/public_lane.py avec le plancher 0.9 que le schéma utilise déjà
  - Preuve : tests/test_signature_backends.py (5 tests de plus, 38 dans ce fichier) ; sur la tranche 1600-1999 jamais lue, 400 cas : couverture 0.820 (annoncé ≥0.80, règle 0.750), accord d'acte 0.689 (annoncé ≥0.70, règle 0.690, KNN pur 0.782), précision de champs 0.822 (KNN pur 0.795) et rappel 0.327 contre 0.118 pour la règle
  - Notes : prédiction à moitié confirmée, et la moitié qui échoue est mesurable : la couche décide par question et le primaire est sûr d'un acte moins souvent qu'il n'accepte d'en répondre, donc l'acte vient du repli dans la plupart des cas et l'étage hérite de son exactitude ; ce que la récupération connaît le mieux est le champ, pas l'acte

- [ ] TASK-090 [P2] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Plancher par type de question dans la route à deux étages
  - Dépendances : TASK-089
  - Notes : un seul plancher pour toutes les questions est ce qui a coûté l'accord d'acte, puisque la confiance du primaire n'est pas la même selon la question ; candidat : plancher plus bas pour les champs que pour les actes, ce qui revient à faire décider le primaire là où il est réellement meilleur ; mesure sur une tranche ultérieure non lue (2000 et au-delà) avec prédiction annoncée d'avance : l'accord d'acte doit passer au-dessus de la règle sans perdre la couverture ni la précision de champs ; ne pas régler sur les tranches 0-1999, désormais connues

- [x] TASK-091 [P1] [difficulté: raisonnement] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Ingestion versionnée des prompts réels avec mise à jour et révision automatiques
  - Dépendances : TASK-079
  - Reçu : signature_ingest.py (sources et configuration par appelant, découverte générique des dépôts de rollouts, lecture des seuls messages utilisateur, retrait du texte injecté par l'assistant, masquage des secrets et adresses, identifiant de révision adressé par contenu, comparaison de révisions, écriture non écrasante) et examples/prompt_ingest.py (essai à blanc par défaut, --update pour écrire, pointeur latest.json)
  - Preuve : tests/test_signature_ingest.py (14 tests, dont l'identité adressée par contenu et l'indépendance à la date, le dédoublonnage avec compteur, le refus d'un corpus vide, et un filtre de ligne qui ne peut pas perdre un vrai message) ; exécution réelle sur 824 fichiers de rollout en 41 s : 7657 messages, 2338 prompts distincts, 1460 textes nettoyés du harnais, 6863 masquages, seconde exécution à delta nul avec le même identifiant
  - Notes : le corpus vit dans runs/signature-corpus (ignoré par git), la configuration est celle de l'appelant et aucun chemin personnel n'est compilé dans le module ; seuls 83 des 135 prompts de l'extraction manuelle survivent tels quels, donc 38 % de ce corpus n'était pas ce que la personne avait tapé ; trois entrées de 9, 15 et 3 caractères font à elles seules 3928 des 7657 messages, donc environ la moitié du volume réel ne porte aucune demande

- [x] TASK-092 [P1] [difficulté: raisonnement] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Partition du corpus réel par volume et artefact de taxonomie depuis les mots de l'utilisateur
  - Dépendances : TASK-091
  - Reçu : signature_taxonomy.py (partition stricte et lâche avec parts de volume, borne supérieure du multi-demande, proposition de hints par action avec ce qu'elle ne couvre pas, tout marqué à ratifier) et tests/test_signature_taxonomy.py
  - Preuve : 9 tests ; sur la révision réelle 68c3f498 : 2338 prompts distincts, 7657 messages, demandes 45 % du volume (3437), continuations lâches 55 % (4220) dont 3561 venant de 4 textes seulement, multi-demande ≤ 8.7 % du volume (595 distincts, 665 messages), 45.8 % du volume des demandes sans aucune action reconnue
  - Notes : la partition est une clé de lecture, pas une présentation ; les étiquettes resteront label_origin model avec labeler_id déclaré, donc fixture et sans autorisation ; la proposition a surtout servi de détecteur de défaut, voir TASK-093

- [x] TASK-093 [P0] [difficulté: raisonnement] [class: bug] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Terminer le nettoyage du texte de harnais avant toute dérivation de vocabulaire
  - Dépendances : TASK-092
  - Notes : la proposition de hints a exposé du texte résiduel comme meilleurs candidats d'actions sans rapport, avec « instructions » dans des demandes portant 797 messages, l'avis « not installed » 665, l'avis « untrusted » 478, « treat » 587 ; le retrait actuel ne couvre que quelques balises et le marqueur de demande, il faut recenser les blocs injectés restants (avis de données non fiables, contextes d'environnement d'une autre forme, listes de fichiers joints) ; critère d'acceptation mesurable : plus aucun mot de la liste de boilerplate (not, but, installed, available, remote, here, treat, instructions, untrusted, environment, distinguish, attached, request) ne doit apparaître dans les six premiers hints proposés d'une action ; à vérifier par une nouvelle révision, et à ne pas dériver de taxonomie avant
  - Reçu : blocs de harnais étendus (objective, in-app-browser-context, recommended_plugins, apps_instructions), sections (conversation référencée), queues rejouées (>>> TRANSCRIPT), et avis retirés partout (revue de conversation, objectif fourni par l'utilisateur, « not part of the user's request », persistance d'objectif) ; plus le classement des hints par pouvoir discriminant et non par fréquence dans signature_taxonomy.py
  - Preuve : 18 tests d'ingestion et 14 de taxonomie ; deux nouvelles révisions (60ebab46 puis 6a82e0bc) ont retiré 539 entrées qui n'étaient que du harnais puis 76 de plus, et le critère modifié PASSE : plus aucun mot-outil dans les six premiers hints d'une action ; le vocabulaire proposé passe de « not, installed, but, available, remote, here, treat » à « codex, session, thread, worktree, commit, zig, token, delegation, brief, projet »
  - Notes : deux corrections importantes. Le compteur de masquages est tombé de 6863 à 206, donc la mesure précédente était portée par du harnais et non par les mots de la personne. Et la part des demandes qu'aucun vocabulaire déclaré n'atteint est montée de 45.8 % à 72.8 % : le harnais fournissait de faux verbes qui gonflaient la couverture. Passer le critère n'est pas avoir un bon vocabulaire : il reste des mots d'environnement (nom de plugin, année) et des adjectifs génériques (full, current, first) que seule une ratification humaine peut trancher, c'est TASK-097

- [ ] TASK-097 [P1] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Ratifier la taxonomie proposée et écarter les mots d'environnement
  - Dépendances : TASK-093
  - Notes : la proposition passe le critère sans être bonne pour autant, elle mélange trois populations : du vocabulaire de domaine réel (commit, zig, delegation, worktree, token, brief, projet), des mots d'environnement (nom de plugin, année, nom d'outil) et des adjectifs génériques (full, current, first, exact) ; le tri demandait un humain dès le départ et c'est exactement son rôle ; critère d'adoption : chaque type déclaré doit avoir au moins trois hints dont l'auteur peut dire pourquoi ils discriminent, et l'artefact doit ensuite être mesuré sur des prompts dont il n'est pas dérivé

- [x] TASK-103 [P1] [difficulté: compact] [class: bug] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Séparer les candidats verbes des termes de domaine
  - Dépendances : TASK-099
  - Reçu : troisième population by_domain_term dans unreached_verb_candidates, alimentée par les mots capitalisés du texte brut, avec la règle documentée qu'un même jeton peut être un faux verbe et du vrai vocabulaire
  - Preuve : 786 tests ; un test vérifie explicitement qu'« Odycer » apparaît dans les deux listes, faux verbe pour la règle de forme et terme de domaine pour le jeu de hints ; sur les 346 demandes non atteintes, la nouvelle liste fait remonter le projet de l'auteur (ultimate, et « f serv ultimate od » via un fragment de chemin) que la liste des verbes écartait
  - Notes : correction reçue de l'auteur, « odycer vient du projet ultimate odycer » ; j'avais écrit « bruit à rejeter » pour un nom de projet, ce qui confondait deux verdicts distincts. Deux conséquences mesurées : la nouvelle liste est polluée par du harnais résiduel (« treat » en tête, 37 messages, encore l'avis de transcription) et par des fragments de chemins (appdata, local, temp, « f serv ultimate od »), donc il faut un filtre de chemins ; et le signal des majuscules reste grossier puisque les majuscules de début de phrase survivent à l'écrasement des espaces. Deux vrais verbes manquants trouvés au passage : finir(6) et jouer(6)

- [x] TASK-104 [P1] [difficulté: compact] [class: bug] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Filtre de chemins dans l'analyse et achèvement des avis de harnais
  - Dépendances : TASK-103
  - Reçu : généralisation de l'avis de transcription (la variante sans le mot « delta » échappait à la règle) et quatre avis supplémentaires retirés (travail arrêté, mise à jour de plan, contenu d'image, blocs d'écriture) ; côté analyse, un retrait des chemins déclaré dans real_asks.py, appliqué au recensement seulement et pas au corpus
  - Preuve : 788 tests ; nouvelle révision cb6f2f39 (+86 / −83) ; liste des termes débarrassée des fragments de chemins (appdata, local, temp, « f serv ultimate od ») et du mot « treat », et liste des verbes débarrassée des mêmes fragments ; le vocabulaire de domaine remonte enfin : codex(26), ultimate(6), commit(5), « codex spark »(5), « gpt 5 »(5)
  - Notes : la séparation des deux endroits est le point de méthode — un avis de harnais se retire du corpus parce qu'il n'a jamais été écrit par la personne, un chemin se retire de l'analyse parce qu'il fait partie de ce qui a été écrit ; ce qui reste est petit et nommable : « salon » vient d'un avis de navigateur citant un élément de page, et development, comment, pass, failed sont des mots génériques ; remaining : les deux vrais verbes finir et jouer, et la ratification humaine de la liste des termes

- [x] TASK-105 [P1] [difficulté: compact] [class: bug] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Un nom capitalisé quelque part n'est un candidat verbe nulle part
  - Dépendances : TASK-103
  - Reçu : recensement en deux passes, texte brut conservé à côté des jetons normalisés, et exclusion de tout terme capitalisé hors position zéro
  - Preuve : 789 tests ; sur la révision courante, odycer a quitté la liste des verbes (user 40, continuer 29, were 27, etre 25, autre 9, another 6, browser 6, finir 6, jouer 6, marker 6) et reste dans celle des termes (codex 26, background 20, ultimate 13, development 7, comment 6, failed 6, pass 6, codex spark 5, commit 5, gpt 5)
  - Notes : l'observation de l'auteur, « tu sembles confondre odycer avec auditer », a été testée avant d'être crue : verb_action sur odycer renvoie None et aucune clé du lexique n'est à une édition de lui, donc la tolérance ne confond rien ; la confusion est réelle mais dans la règle de forme, où le suffixe -er rend un nom indiscernable d'un infinitif. Trois défauts en cascade corrigés en chemin, chacun trouvé par mon propre test : la règle ne couvrait que le texte courant, puis le motif tournait sur des jetons déjà minusculés, puis la suppression du premier mot capitalisé se faisait par rang au lieu de par position, ce qui effaçait un nom en milieu de texte

- [x] TASK-106 [P2] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Déclarer les deux derniers verbes du recensement et constater la saturation de l'axe verbal
  - Dépendances : TASK-100
  - Reçu : finir, finis, finie, jouer, joue déclarés vers generate, plus l'artefact local runs/signature-corpus/vocabulary-to-ratify.json (schéma, termes de domaine, hints par action, volumes)
  - Preuve : 790 tests ; couverture en volume 0.560 vers 0.570 (cadre avec signal), soit **un demi-point** pour deux verbes ; et la liste des verbes restants s'est re-remplie dès qu'on a retiré sa tête : penser(6), analyser(5), modifier(5) apparaissent maintenant, ce qui montre une queue longue à poids 5-6
  - Notes : la conclusion mesurée est que **l'axe verbal est saturé** — chaque nouveau verbe rapporte moins d'un demi-point, et la queue ne se referme pas ; continuer à déclarer des verbes serait un travail sans fin sur une ressource qui n'est plus le facteur limitant. Ce qui reste atteint n'est plus un problème de vocabulaire mais un problème de mécanisme : 43 % du volume des demandes n'est atteint par aucun des trois, et aucun mot-clé ni verbe ne le corrigera. Le seul chemin restant est celui des étiquettes (récupération, TASK-102 et au-delà), et il demande du travail réel neuf. Ce qui est à l'auteur : trancher la liste des termes et des hints, désormais écrite dans vocabulary-to-ratify.json ; les candidats génériques à rejeter y sont mêlés (true, sans, autre, puis, apres, oui, https, 2026)

- [x] TASK-107 [P1] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Une abstention de signature devient une décision d'escalade budgétée, pas un silence
  - Dépendances : TASK-098
  - Reçu : signature_escalation.py et decide_after_signature, qui passe la signature à la politique d'escalade existante comme l'issue d'une tentative — verdict None si elle s'abstient, True si elle tranche — et conserve le code de raison de la signature dans le détail
  - Preuve : 5 tests ; signature déterminée vers ACCEPT ; abstention avec route plus lourde déclarée vers ESCALATE avec next_route_id et la cause visible dans le détail ; abstention sans droit d'escalade vers ABSTAIN sans route ; budget de tentatives épuisé vers FAIL_HARD ; et le pont refuse qu'on lui dise qu'aucune tentative n'a eu lieu
  - Notes : c'est le joint qui manquait entre les deux moitiés du projet — la couche qui choisit le mécanisme et celle qui décide quoi faire quand aucun ne convient ; la politique possède le budget, le garde-fou de boucle et les arrêts durs, ce module ne fait que traduire et n'exécute rien ; traité comme l'issue d'une tentative parce que le prédicteur a réellement tourné et a coûté quelque chose, et qu'un prédicteur non calibré ne peut ni accepter ni retenir une route par lui-même

- [x] TASK-108 [P1] [difficulté: compact] [class: bug] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Le pont sur les demandes réelles, et la correction d'un mot emprunté à tort
  - Dépendances : TASK-107
  - Reçu : la signature déterminée ne passe plus par la politique et n'emprunte plus son motif verified_accept, elle rend un ACCEPT avec le motif signature_determined et un détail qui dit qu'un vérificateur détient encore le résultat
  - Preuve : 795 tests ; sur les 1769 demandes réelles, volume 2658 : **ACCEPT 1335 distinctes / 1514 messages (0.570)** et **ESCALATE 434 / 1144 (0.430)**, aucune abstention forcée parce que le budget déclaré autorise une escalade
  - Notes : la faute corrigée est celle que je cherchais dans mon propre travail en pensant à l'exécution réelle — nommer une action n'est pas vérifier un résultat, et reprendre le mot « verified » de la politique aurait été un surclaim discret. Ce que la distribution dit vraiment : 100 % du volume des demandes a désormais une décision typée au lieu d'un silence, et les 43 % qui escaladent sont exactement là où vit le coût de ce pipeline. Ce qu'elle ne dit pas : que l'escalade donnera la bonne réponse, ni que les 0.570 sont généralisables, la couverture restant en échantillon. Budget, coût et latence sont déclarés pour l'exercice et non mesurés. L'abstention à zéro est une conséquence du budget déclaré, pas du corpus : avec max_escalations=0, tout le non-atteint bascule en ABSTAIN, ce que les tests hermétiques couvrent

- [x] TASK-098 [P1] [difficulté: raisonnement] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Mesure sur les demandes réelles, sans aucune étiquette inventée
  - Dépendances : TASK-093
  - Reçu : real_asks.py (couverture par mécanisme, distribution des actions, couverture par bande de longueur, triage par accord entre mécanismes) et examples/real_asks_lane.py
  - Preuve : 5 tests ; sur les 1754 demandes réelles de la révision 6a82e0bc (3127 messages) : couverture en volume 0.169 (règle), 0.272 (cadre témoin), 0.288 (cadre avec signal) ; triage 848 messages unanimes, 10 en désaccord, 3 en majorité, et **2266 messages (72 % du volume) où même deux mécanismes ne répondent pas**
  - Notes : trois lectures. Un : sur des demandes réelles, les mécanismes répondent **moins de 30 % du volume**, contre 73-79 % sur le corpus public — le vocabulaire réel est le mur, pas la précision. Deux : là où deux mécanismes peuvent être comparés, ils s'accordent sur 98.8 % du volume, donc **l'arbitrage humain n'est pas le coût, l'atteinte l'est** : 0.4 % du volume mérite une étiquette. Trois : le cadre atteint 84 % des textes de plus de 1000 caractères, et ce n'est **pas** un succès mais un symptôme — un texte long contient presque toujours un verbe, et le premier trouvé est arbitraire ; à l'inverse la bande la plus fréquente (30-99 caractères, 1531 messages) n'est atteinte qu'à 6-8 %. Aucune étiquette n'existe, donc précision et exactitude restent non mesurées et non mesurables sans un humain

- [x] TASK-099 [P1] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Recensement des verbes des demandes que rien n'atteint
  - Dépendances : TASK-098
  - Reçu : unreached_verb_candidates et looks_like_a_verb dans real_asks.py (deux signaux déclarés : premier jeton, et forme infinitive en er/ir/re ; chaque signal séparé en ce que le lexique sait et ce qu'il manque)
  - Preuve : 4 tests ; sur les 1754 demandes, 775 distinctes et **2001 messages** ne sont atteints par aucun des trois mécanismes ; par forme, 94 termes manquants pesant 1135 messages, dont faire(105), creer(92), etre(66), continuer(57), ameliorer(53), develloper(27), commencer(24), ajouter(17) ; par position, 24 termes pesant 999 messages
  - Notes : trois constats. Un : l'écart réel est nommé — faire, créer, améliorer, développer, ajouter, commencer ne sont pas dans le lexique, et les déclarer est un geste mesurable. Deux : une **faute de frappe réelle est dans les données** (« develloper », 10 messages), ce qui justifie enfin par des faits le candidat « distance d'édition ≤ 1 » signalé il y a plusieurs tours. Trois : le recensement par position a exposé **encore du harnais** (« agents » premier jeton de 508 messages) et trois familles de bruit honnête : noms propres (odycer), passés anglais (were, 29) et adjectifs ou prépositions en -re (autre, apres) ; le signal positionnel n'est donc pas encore exploitable, et la forme demande une ratification

- [x] TASK-100 [P1] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Déclarer les verbes manquants et tolérer les fautes de frappe, puis remesurer sur la révision suivante
  - Dépendances : TASK-099, TASK-093
  - Reçu : 92 entrées de lexique ajoutées (impératifs et infinitifs français, verbes anglais manquants) depuis la sémantique des catégories et l'usage général, plus verb_action avec tolérance à une édition et l'application en dernier recours seulement (un verbe exact gagne toujours), et deux variantes observées déclarées explicitement
  - Preuve : 785 tests ; sur la **même révision** 3244946e, donc attribuable au seul lexique : les demandes non atteintes par les trois mécanismes passent de **764 distinctes / 1493 messages à 346 / 624** (−58 % de messages) ; couverture en volume 0.169 → **0.403** (règle), 0.272 → **0.556** (cadre témoin), 0.288 → **0.560** (cadre avec signal), au-dessus de la cible de 0.50 ; couverture en distincts du cadre 0.747
  - Notes : deux constats mesurés. Un : la tolérance à une édition attrape un vrai lapsus (« formatter », « corrgier » par transposition) mais produisait un faux positif sur « rendu », nom à une substitution de l'impératif « rends », d'où le plancher relevé à six caractères. Deux : la faute réelle des données, « develloper », est à **deux** éditions, donc hors de portée d'une tolérance à une édition ; elle est **déclarée** comme variante, pas devinée, parce qu'une faute vue dix fois est du vocabulaire et non un lapsus. Limite : j'ai vu les jetons du recensement avant de déclarer, donc ce chiffre est en échantillon ; la preuve indépendante demande une révision postérieure, voir TASK-102. Le recensement ne propose plus que du bruit à rejeter (nom propre, passé anglais, adjectif, auxiliaire) : l'écart de verbes est refermé

- [ ] TASK-102 [P2] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Remesurer la couverture sur une révision postérieure à l'artefact
  - Dépendances : TASK-100
  - Notes : le gain de TASK-100 est en échantillon, puisque les verbes déclarés l'ont été après avoir vu les jetons du recensement. Première tentative de vérification : **impossible aujourd'hui, et c'est un résultat**. La réingestion a rendu delta=unchanged avec le même identifiant de révision, alors que le compteur de messages est passé de 6808 à 6813 : les cinq messages neufs sont des répétitions d'entrées connues, et l'identité d'une révision étant adressée par contenu, des occurrences nouvelles ne changent rien. La séparation est donc armée mais l'ensemble tenu à l'écart est vide : aucun contenu distinct n'est apparu depuis la déclaration. Procédure prête : ingérer, prendre les prompts dont le texte est absent de revision-3244946e44a7aeaf.json, mesurer la couverture sur ceux-là seulement. Critère : la couverture en volume du cadre doit rester au-dessus de 0.50 sur du contenu qui n'existait pas à la déclaration, sinon le gain était du surapprentissage. Prérequis réel : du travail neuf, hors de cette conversation

- [x] TASK-101 [P0] [difficulté: compact] [class: bug] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Retirer le fichier d'instructions de projet injecté dans les messages
  - Dépendances : TASK-099
  - Reçu : marqueur « # AGENTS.md instructions » ajouté aux queues de harnais, avec correspondance insensible à la casse, et le contenu retiré jusqu'à la fin du message parce que le harnais préfixe le fichier d'instructions du projet
  - Preuve : 19 tests d'ingestion ; révision 3244946e avec delta −12 entrées et −859 messages, et vérification par mesure : **0 entrée** dont le premier jeton est encore « agents » (contre 12 entrées et 868 messages avant) ; le recensement positionnel passe de agents(508) en tête à commit(89), command(61), local(61), oui(55), task(37), continuer(32)
  - Notes : le coût assumé est qu'un message qui *parle* d'un fichier d'instructions perd sa fin ; c'est déclaré dans le module et le drapeau harness_stripped le compte ; le recensement par forme n'a pas bougé (faire, creer, ameliorer, develloper…), ce qui confirme que les deux résidus étaient bien distincts

- [ ] TASK-094 [P2] [difficulté: raisonnement] [class: feature] [horizon: medium] [goal: GOAL-PARCIMONIA]
  - Intitulé : Route de délégation et plan à deux étages (LLM cloud si disponible, récupération de plans sinon)
  - Dépendances : TASK-093, TASK-089
  - Notes : trois préconditions mesurables avant d'écrire cette route. Un : un corpus de plans, pas de prompts, chacun lié à son issue — des plans seuls n'apprennent pas quels plans ont marché. Deux : un vérificateur déterministe de plan (couverture des sous-tâches, capacités déclarées existantes, contraintes respectées), à défaut un plan récupéré n'est qu'une hallucination avec une citation. Trois : la mémoire de récupération est le format d'enregistrement des plans, comme pour les signatures. La délégation vers un autre agent ou un outil est déjà exprimable comme une route portant une capacité, ce qui manque est le vérificateur du résultat délégué. Priorité basse parce que le multi-demande mesuré plafonne à 8.7 % du volume : la première tâche reste le routage d'une demande unique

- [x] TASK-095 [P1] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Frontière de responsabilité entre la famille continuation et la famille demande
  - Dépendances : TASK-092
  - Reçu : RESPONSIBILITY et responsible_layer dans signature_taxonomy.py, avec les entrées exigées par chaque couche
  - Preuve : tests/test_signature_taxonomy.py (13 tests au total), dont la frontière qui suit la classification (« continuer », « oui ! », « et la suite » vers le directeur ; « summarise the report », « extraire les colonnes » vers Parcimonia) et la vérification qu'une continuation ne demande ni signature ni vérificateur ; démonstration réelle : l'arbitre alimenté par le quota effectif (fenêtre hebdomadaire à 0 %, réinitialisation à 12 h 23 UTC) autorise une tâche déterministe via une règle locale à coût nul de jeton, dégrade une tâche compacte en modèle local à 1000 jetons, gèle le raisonnement lourd et demande un humain quand il ne reste pas d'horloge
  - Notes : c'est une frontière, pas un routeur — aucune couche ne prend silencieusement la décision de l'autre, et le directeur a besoin d'état, jamais de texte ; environ 55 % du volume réel de messages appartient à cette famille, donc le chemin état est le chemin majoritaire

- [x] TASK-096 [P2] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Branchement consommateur : une continuation alimente l'état du directeur, jamais le chemin de signature
  - Dépendances : TASK-095
  - Reçu : dispatch_turn en observation, avec continuation exacte vers AstralDirector et demande vers signature_escalation ; les messages courts ambigus restent unresolved
  - Preuve : tests/test_turn_dispatch.py ; ni la signature ni le vérificateur ne sont créés par une continuation
  - Notes : la boucle de tour de l'application peut appeler ce pont ; le Director conserve intention et autorisation. Le quota observé reste une contrainte de ContinuationArbiter

- [ ] TASK-061 [P3] [difficulté: compact]
  - Intitulé : Sync live Kanboard Neo si KANBOARD_URL et AGENT_INGEST_TOKEN existent
  - Dépendances : TASK-052
