# Sources

Ce qui a nourri la ligne technique, avec sa date, sa licence et la frontière qui
l'accompagne. Aucun code, aucun texte ni identité visuelle d'une source n'est
recopié : ce qui est retenu est un **motif**, réimplémenté et mesuré ici.

| Source | Reçue le | Ce qui en a été retenu | Frontière |
| --- | --- | --- | --- |
| Vidéos sur les modèles de décision discrets (Jev, System One) | 19/09/2026 | un modèle qui score K options en moins de 20 ms, sans générer ; le motif agent-natif qui filtre les outils avant la boucle | inspiration, pas matériel : aucune vidéo n'a été réanalysée ici, le contenu retenu vient des notes de cette session |
| Vidéos sur l'intelligence topologique et l'ingénierie système à grande échelle | 19/09/2026 | portes d'étranglement invariantes, indices d'enroulement comme mémoire discrète, « an interface is a promise », primauté de la télémétrie | idem ; la topologie dirigée reste une piste, pas un livrable |
| `yibie/awesome-jev` | 22/09/2026 | un catalogue d'usage du même motif, lu comme état de l'art | aucun composant repris |
| Dolly-15k (voie publique) | 22/09/2026 | un jeu étiqueté par des personnes qui ne sont pas nous, pour mesurer sans autoriser | CC-BY-SA-3.0 ; l'origine `public` ne peut jamais autoriser une exécution |
| Le magasin de rollouts local | 22/09/2026 | les prompts réellement tapés, nettoyés du harnais et adressés par contenu | reste local, ignoré par git, jamais publié ni cité en clair |

## Tutoriel Bev — 4 octobre 2026

[Analyse et protocole de reprise](BEV_2026-10-04.md) de la
[vidéo de Neural Breakdown with AVB](https://www.youtube.com/watch?v=sF3CNPbWA8o).
Sous-titres automatiques lus, code et schémas examinés ; les images du lecteur
n'ont pas pu être confirmées. Les pistes retenues sont la stabilité à l'ordre
des options, les exemples français contrastés et la comparaison de coût complet.

Sources épinglées : [entraînement](https://github.com/avbiswas/bev-train/tree/a58c551bf631418137567ccf1ad200328549cc3c),
[runtime](https://github.com/avbiswas/bev-decider/tree/aa5d861f256b57f32794715de2559cd5a7b68a30),
[modèle](https://huggingface.co/avbiswas/bev-decider-0.4B/blob/cf5138b5b465343d09c3b4fbd71eaca36d989d34/README.md),
[données](https://huggingface.co/datasets/avbiswas/bev-decision/blob/11ed9b5b879e7f9524e7c89c1037d498c54206f0/README.md).
Poids CC-BY-NC-4.0, runtime Apache-2.0 annoncé, licence globale du dataset
inconnue et aucun LICENSE dans le dépôt d'entraînement étudié. Aucun code ou
poids repris ; aucune qualité, calibration ou économie locale établie.

## Ce qui n'est pas une source

- Un corpus étiqueté par un modèle : c'est le gabarit de la distillation, et il
  reste `fixture` tant que les étiquettes ne viennent pas d'issues réelles.
- Un jeu public : il mesure un mécanisme, il ne l'autorise pas.
- Un banc authoré : il dit ce que l'implémentation fait, pas ce que la tâche
  demande.
