# Trois étiquettes à ratifier dans le corpus de paraphrases

La carte TASK-082 porte sur trois exemples rédigés pour une fixture. Ces labels
ne décrivent pas des issues observées. Une modification du label augmenterait
l'accord du cadre sur les cas auxquels il répond de 0,667 à 0,778 pour chacun
des trois changements pris isolément. Cette hausse n'est pas un critère de
vérité : elle se produit précisément parce que l'on rapproche le label de la
prédiction du cadre.

| Cas | Formulation | Label actuel | Prédiction du cadre | Question à trancher |
| --- | --- | --- | --- | --- |
| `paraphrase-09` | `check the spelling of this sentence` | `format` | `verify` | S'agit-il de vérifier l'orthographe, ou de corriger la phrase ? |
| `paraphrase-10` | `reformat the options before deciding` | `decide` | `format` | La tâche cible est-elle la première action, ou la décision finale ? |
| `paraphrase-11` | `tidy the report then confirm it` | `verify` | `format` | La tâche cible est-elle la remise en forme, ou la confirmation finale ? |

Deux des formulations sont des séquences d'actions. Un label unique exige
donc une règle éditoriale explicite : première action, résultat final, ou
séparation en deux tâches. Le système ne doit pas apprendre une convention
implicite qui change d'un exemple à l'autre.

`label_review.py` calcule la sensibilité de l'accord pour les interprétations
envisagées sans toucher à `signature_corpus.py`. La carte reste ouverte jusqu'à
la décision de l'auteur. La fixture ne peut autoriser ni auto-act, ni
affirmation de qualité sur les demandes réelles.
