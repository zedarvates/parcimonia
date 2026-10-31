# Kit de diffusion — démo Parcimonia

Contenu prêt à adapter après l'enregistrement de la vidéo. La démonstration
est synthétique : les coûts et les niveaux de confiance sont fournis par
l'appelant. Elle montre la règle de décision du routeur, pas une économie
observée ni la qualité réelle des routes.

## Miniature

- [PNG prêt à importer](assets/parcimonia-flagship-thumbnail.png)
- [Source SVG éditable](assets/parcimonia-flagship-thumbnail.svg)

Le visuel reprend le troisième fragment de
[la démo](../examples/flagship.py) : règle à 0,00 et confiance déclarée à 0,88 ;
KNN à 0,03 et confiance déclarée à 0,94 ; seuil à 0,90. Les coûts sont
synthétiques. Aucun modèle KNN ni aucune regex ne sont exécutés par cette démo.

## Publication LinkedIn

J'ai construit un routeur qui peut répondre « je m'abstiens ».

Dans une démo de six tâches, il refuse trois propositions — dont l'option la
moins chère sur l'une d'elles.

Pour extraire un montant de facture, une règle est déclarée à coût 0,00 et
confiance 0,88. Le seuil demandé est 0,90. Parcimonia propose donc l'option
KNN, déclarée à 0,03 et 0,94.

Puis il s'abstient sur une revue à risque élevé, un diagnostic qui exige plus
de preuves et un cas où aucune option n'a de confiance déclarée.

Ce que la démo montre : une politique de choix explicite et déterministe, avec
des raisons lisibles pour chaque refus.

Ce qu'elle ne montre pas : des économies réelles ou la qualité de ces routes.
Les coûts et les confiances sont des données d'exemple ; le mode est « shadow ».
Rien n'est exécuté.

Si votre routeur devait s'abstenir plus souvent, dans quel cas commenceriez-vous ?

Démo reproductible : https://github.com/zedarvates/parcimonia/blob/main/examples/flagship.py

#AIAgents #LocalFirst #Python

## Vidéo YouTube

**Titre :** Parcimonia : le routeur qui refuse l'option gratuite

**Description :**

Six tâches d'exemple passent dans Parcimonia. Le routeur propose une option
pour trois d'entre elles et s'abstient sur les trois autres, avec une raison
explicite.

Au troisième fragment, l'option gratuite est écartée : sa confiance déclarée
est de 0,88, sous le seuil fixé à 0,90. Une option à coût synthétique de 0,03,
déclarée à 0,94, est proposée. La démo ne mesure ni la qualité des options ni
une économie réelle.

Tout se déroule en mode « shadow » : aucune route n'est exécutée et aucune
route de référence n'est remplacée.

Reproduire la démo :
`python examples/flagship.py`

Code : https://github.com/zedarvates/parcimonia/blob/main/examples/flagship.py

Explication et capture : https://github.com/zedarvates/parcimonia/blob/main/docs/FLAGSHIP.md

**Chapitres proposés pour le montage de 90 secondes** — ajuster aux temps
réels après export :

- 0:00 — Ce que choisit le routeur
- 0:08 — Une commande, six fragments
- 0:18 — L'option gratuite écartée
- 0:45 — Trois abstentions
- 1:12 — Les limites de la démonstration
- 1:22 — Conclusion
