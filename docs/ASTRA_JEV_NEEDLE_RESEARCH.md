# Astra, Jev, Needle 3 et les routes locales de Parcimonia

État : proposition d'intégration en observation seulement, 2026-09-23.
Les titres des vidéos ont été vérifiés par les métadonnées YouTube. Leur
transcription et leurs démonstrations complètes n'ont pas été vérifiées. Les
performances annoncées dans un titre ou une démonstration ne sont donc pas des
mesures de Parcimonia.

## De quel Astra parle-t-on ?

Deux projets portent ici des noms voisins :

- [MatrixOrigin/Astra](https://github.com/matrixorigin/Astra) est un runtime
  d'agents. Il permet un modèle principal et un modèle de jugement séparé
  (Jev ou un LLM) pour filtrer la mémoire, classer une demande et choisir un
  skill. Son runtime conserve l'autorité d'exécution.
- [astra-flash-orchestrator](https://github.com/ethanplusai/astra-flash-orchestrator)
  est un workflow : Astra planifie et révise, DeepSeek Flash réalise la tranche
  de code. Ses chiffres publiés sont issus d'un cas d'étude et ne valent pas
  validation de qualité, coût ou quota pour nos projets.
- **Astral Resonance Director** est notre superviseur existant. Son rôle est
  l'intention, la phase, la proposition et l'approbation. Il ne doit pas être
  remplacé implicitement par l'un des deux projets précédents.

Les vidéos consultées par leurs métadonnées publiques :
[Astra + Jev + DS V4.1 Flash](https://youtu.be/WBvmtzkJZsY),
[JARVIS + Jev](https://youtu.be/D5v4UuvtUXc),
[Jev avec Astra](https://youtu.be/k6aU6T03JyU),
[The Geometry of AI Thoughts](https://youtu.be/gNV2rDH7d4E),
[AI Data Centers Will Be Obsolete](https://youtu.be/4S8I22ybG2c).

## Montage proposé

```text
buts humains + kanban.md + budget temps + quota + capacité locale
       |
       v
Astral Resonance Director : sélection du travail et autorisation
       |
       v
Parcimonia : contrat de tâche, contraintes, registre de routes, budget
       |
       +--> règle / cache exact / KNN vérifié
       +--> nano ou micro modèle local si résident, mesuré et calibré
       +--> Jev ou Laya : questions fermées, jugement auxiliaire
       +--> LLM principal (Astra ou autre) : plan, code, explication
       |
       v
Needle 3 (optionnel) : proposition d'appel d'outil et extraction
       |
       v
schéma + provenance des arguments + permission + vérificateur
       |
       v
rapport de tour : identité du modèle, quotas, coût, temps, qualité et outils
```

Jev n'est pas le planificateur et Needle n'est pas l'autorité qui exécute.
Un modèle de jugement répond à des questions fermées ; le LLM principal écrit
un plan ou du code ; Needle propose un appel d'outil ; Parcimonia compare les
routes et abstient quand preuve ou budget manquent ; le Director porte
l'intention et l'approbation. Les routes KNN/nano/micro sont des candidates,
pas des promesses de qualité. La bascule vers un autre modèle doit garder
l'identité réelle, le coût et le quota de chaque appel.

Exemple pour une correction de bug : une règle lit les métadonnées, un KNN
cherche un correctif déjà vérifié, Jev peut juger si le cas connu s'applique,
le LLM principal prépare ou réalise la tranche si nécessaire, Needle peut
proposer un appel de test. Le vérificateur exécute les tests autorisés et
attribue le résultat. Une réponse Jev confiante n'autorise ni écriture ni
validation du correctif.

## Ce qui existe dans ce dépôt

| Besoin | État local |
| --- | --- |
| Buts, kanban, priorité et approbation | `goals.py`, `kanban.py`, `roadmap.py`, `director.py` |
| Budget de quota, temps, capacité | `continuation.py` |
| Questions Jev-like `choice/score/noul` | `reflex.py` et `decision_adapter.py` ; transport injecté et rejeu |
| Proposition de tool call Needle-like | `schema_emit.py` ; validation après proposition, **pas de vrai décodeur à grammaire** |
| Route KNN/nano/micro | contrats de signature et surface projet ; aucun modèle KNN/nano/micro entraîné ou évalué ici |
| Preuve et comparaison | registre, vérificateurs, mesure, benchmark ; fixtures distinctes des tâches réelles |

Le dernier point est décisif : le benchmark a besoin d'un même corpus de
tâches et de sorties vérifiées pour comparer « LLM seul », « règles + KNN »,
« jugement typé + LLM », « émission d'outil » et les combinaisons. Mesurer
par étape les tokens *par fournisseur*, le coût facturé, la latence de bout en
bout, le démarrage à froid, les échecs, les appels de validation et le travail
humain. Un gain sur les seuls tokens du LLM principal peut cacher le coût des
jugements, outils, caches ou revues. Une route moins chère qui échoue à la
vérification perd.

## Porte d'évaluation suivante

Le manifeste `route_experiment.py` permet de décrire les bras et leur
disponibilité, puis de vérifier des résultats appariés sans exécuter de modèle.
Avec Jev/Needle/KNN encore indisponibles ou sans sorties, le rapport indique
`arm_unavailable` et `missing_paired_outcomes` : aucune économie n'est
déclarable. Les résultats fixture, coûts inconnus et échecs de vérification
restent des motifs explicites de refus.
Même des résultats complets fournis par l'appelant portent maintenant le
motif `caller_reported_only` et `claim_allowed=false` : seule la chaîne
canonique de mesures et vérifications du benchmark peut certifier un gain.

1. Constituer 20 à 50 tâches représentatives et autorisées à être mesurées,
   avec une sortie attendue ou un vérificateur indépendant, sans données
   privées dans ce dépôt public.
2. Rejouer hors ligne les mêmes tâches avec la règle et les adaptateurs déjà
   présents. Enregistrer les abstentions et les cas non couverts. Ne pas
   fabriquer de verdict pour les modèles absents.
3. Préparer une matrice d'essais avec transports injectés pour chaque backend
   réel. Chaque essai garde son `backend_id`, version, matériel, quota,
   horloge, origine et coût. L'appel Jev est facturable ; le chargement de
   poids Needle/Laya a son propre examen de licence, environnement et capacité.
4. Promouvoir seulement si le jeu tenu à l'écart satisfait les seuils de
   qualité et si le coût total est meilleur, avec la possibilité de revenir à
   la route de base. Aucune vidéo ne remplace cette preuve.

## Les deux pistes « géométriques »

[Zur et al.](https://arxiv.org/abs/2511.04527) étudient les chemins
alternatifs encodés dans les activations d'un LLM et les points de décision.
Cela suggère des expériences de lecture d'état ou de calibration pour un
modèle dont on contrôle les activations. Une API fermée Astra/Jev ne fournit
pas nécessairement ces activations ; le `JEPAActionGate` actuel est une
heuristique et ne mesure pas ce phénomène.

[Sophontic](https://sophontic.ai/) décrit une méthode de raisonnement
géométrique et revendique un prototype compact. La page annonce encore la
publication du modèle et du kit d'évaluation. Cela reste une piste de
recherche : pas de route de production, pas d'économie mesurée par Parcimonia.

## Sources primaires

- [MatrixOrigin/Astra : architecture et Jev](https://github.com/matrixorigin/Astra)
- [MatrixOrigin/Astra : configuration du jugement](https://github.com/matrixorigin/Astra/blob/main/docs/guides/memory-judgment-pilot.md)
- [MatrixOrigin/Astra : résultats et limites du pilote mémoire](https://github.com/matrixorigin/Astra/blob/main/expriment/jev-memory/results/README.md)
- [Astra Flash Orchestrator : workflow et mesures](https://github.com/ethanplusai/astra-flash-orchestrator)
- [TypeSafe : System One et Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- [Cactus : Needle 3](https://www.cactuscompute.com/needle)
- [Laya : contrat et benchmarks](https://github.com/NandhaKishorM/laya)
- [Zur et al. : incertitude des chemins alternatifs](https://arxiv.org/abs/2511.04527)
- [Sophontic : méthode annoncée](https://sophontic.ai/)
