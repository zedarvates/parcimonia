# Identifiants des tâches mémoire — 2026-10-31

La PR #12 et la branche principale avaient attribué les mêmes identifiants à
des travaux différents. L'intégration conserve les identifiants déjà présents
sur main et utilise deux identifiants libres pour les travaux mémoire.

| Contexte | Identifiant initial | Identifiant courant | Travail et état conservé |
| --- | --- | --- | --- |
| Main | `TASK-109` | `TASK-109` | Comparaison contrôlée des routes Astra/LLM, Jev-like, Needle-like, règle et KNN ; ouverte |
| Main | `TASK-110` | `TASK-110` | Piste géométrique sur des représentations accessibles et test de perturbation apparié ; ouverte, dépend de `TASK-109` |
| PR #12 | `TASK-109` | `TASK-111` | Implémentation de la mémoire bornée et des propositions en observation ; terminée |
| PR #12 | `TASK-110` | `TASK-112` | Évaluation sur traces séquentielles, issues indépendantes et mesures fournisseur ; ouverte, dépend de `TASK-111` |

Ce renvoi est **limité au contexte de la PR #12**, en particulier sa tête
historique `6d9ce62201f5b3c5c77313a3451e8a1096c5e26e`. Ce n'est pas un alias
global : une référence `TASK-110` dans les documents de recherche de main
continue de désigner la piste géométrique.

Les guides mémoire courants utilisent `TASK-112`. Les quatre fichiers de
preuves datés des 3 et 4 octobre restent identiques à ceux de la PR #12 :

- [COMPACT_MEMORY_2026-10-03.json](COMPACT_MEMORY_2026-10-03.json) ;
- [MEMORY_REPLAY_2026-10-03.json](MEMORY_REPLAY_2026-10-03.json) ;
- [MEMORY_CAPTURE_2026-10-03.json](MEMORY_CAPTURE_2026-10-03.json) ;
- [MEMORY_EXECUTION_2026-10-04.json](MEMORY_EXECUTION_2026-10-04.json).

La mention `TASK-110` dans le relevé historique de rejeu signifie donc
`TASK-112` pour le suivi mémoire actuel. Aucun relevé ou hash historique n'est
réécrit pour masquer la collision. Les autres tâches de main, leurs contenus,
états et dépendances sont conservés.

Cette correction porte sur le suivi et les liens documentaires. Elle ne clôt
pas l'évaluation réelle, ne transforme pas les fixtures en mesures fournisseur
et n'active ni route, ni service, ni collecte sur une machine personnelle.

## Vérification de l'intégration

Base vérifiée : main `e8eed5ce444573b40fcb0283f9b09731313bd5af`.
Les 67 enregistrements de tâches existants sont conservés à l'identique,
par lecture du parseur Kanban réel et comparaison des blocs de texte complets.
Le suivi résultant contient 69 identifiants uniques. Les deux nouvelles tâches
conservent les états, priorités et dépendances de la branche mémoire, avec
la seule réaffectation des identifiants décrite ci-dessus.

Les 19 fichiers de runtime, tests, exemples et fixtures concernés correspondent
exactement au contenu de la tête historique de la PR #12. Les quatre preuves
JSON historiques ont également été comparées octet par octet. La correction
de conflit ne modifie donc pas ces comportements ou résultats enregistrés.

Sur Python 3.12.14, **3 410 tests et 34 sous-tests passent**, sans test ignoré :
les 3 308 tests de la base et les 102 cas mémoire de la PR. L'avertissement
de dépréciation du plugin pytest `anyio` installé reste sans échec.
La grammaire Python 3.10 des 16 fichiers Python concernés, les liens locaux
modifiés et les espaces du patch ont été vérifiés. Ces tests restent hors ligne ;
ils ne qualifient pas de vrais appels de modèles, corpus privés ou économies.
