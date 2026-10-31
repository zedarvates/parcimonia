# Diagnostic de l'ordre des options Tev1

L'[étude Bev de la PR #14](https://github.com/zedarvates/parcimonia/pull/14)
conduit à tester la stabilité des décisions sous différentes présentations
des mêmes options. Ce mode étend la capture consultative de la PR #13 :
utiliser un checkout isolé de `codex/tev1-choice-order-20261004`, noter
`git rev-parse HEAD` et suivre le [relais local](TEV1_LOCAL_RUN.md).
Le mode par défaut reste le corpus original de 24 cas.

## Corpus et présentation

Les 16 cas à choix ont cinq options chacun. Le mode `choice-order` utilise
les cinq rotations cycliques, y compris l'originale, puis l'ordre inversé :
six ordres sur les 120 possibles. Les huit contrôles booléens/scores restent
inchangés ; les niveaux d'un score gardent leur ordre.
Au total : **96 variantes à choix + huit contrôles = 104 requêtes par modèle**.

État, question, clés, descriptions et étiquette sont conservés. Les identifiants
des variantes sont distincts : `fr-01-rotate-0`, `fr-01-rotate-1`,
`fr-01-reverse` ; les contrôles portent le suffixe `control`.
La révision dérivée inclut le corpus de base et une liste explicite d'ordre
des clés, car le hash JSON canonique trie les clés des mappings.
L'ordre effectivement transmis est vérifié sur HTTP simulé.

L'envoi est déterministe, par cas source, rotations puis inversion, avec les
contrôles à la fin. Les temps peuvent dépendre du chargement et des caches.
Ce diagnostic ne prouve pas une invariance sur toutes les permutations.

## Exécution locale

Afficher le plan sans serveur ni inférence :

```console
python examples/tev1_shadow.py plan --corpus choice-order
```

Après la capture initiale des 24 cas et inspection des résultats, contrôler
les deux modèles **déjà installés** avec le prévol existant :

```console
python examples/tev1_shadow.py preflight --base-url http://127.0.0.1:11435
```

Le port illustré est celui du tunnel du relais local ; l'adapter à l'endpoint
loopback confirmé. Capturer le petit modèle une fois :

```console
python examples/tev1_shadow.py capture --corpus choice-order --model tev1:0.8b --base-url http://127.0.0.1:11435 --budget-ms 5000 --machine-id local-order-01 --out runs/tev1-order-01-small
```

Contrôler son code de sortie. Lancer le second uniquement après un code 0 :

```console
python examples/tev1_shadow.py capture --corpus choice-order --model tev1:4b --base-url http://127.0.0.1:11435 --budget-ms 5000 --machine-id local-order-01 --out runs/tev1-order-01-large
```

Version/digest et échéance sont contrôlés avant et après chaque POST.
Le premier échec ou résultat inutilisable arrête le lot, conserve les records
acceptés et marque les cas restants non tentés, sans temps ni probabilités
inventés. Le code 2 demande d'inspecter le serveur avant un autre appel.
Un dossier existant est refusé ; aucun retry, téléchargement ou entraînement
n'est lancé. À 5 000 ms par tentative, le budget des appels totalise au plus
520 secondes par modèle, hors prévol et écritures : ce n'est pas une durée
mesurée. Le client n'atteste ni arrêt du calcul serveur, ni précision, ni VRAM
ou énergie. L'étiquette de machine reste déclarative.

## Relecture et comparaison

Le corpus est identifié dans le manifeste ; la suite est entièrement hors ligne :

```console
python examples/tev1_shadow.py replay --run runs/tev1-order-01-small
python examples/tev1_shadow.py replay --run runs/tev1-order-01-large
python examples/tev1_shadow.py compare --small runs/tev1-order-01-small --large runs/tev1-order-01-large --out runs/tev1-order-01.json
```

La relecture reconstruit les requêtes depuis la révision du protocole et
contrôle les records, l'identité, le budget et l'arrêt du lot. Elle ignore
les totaux stockés dans `comparison.json`. La comparaison recalcule les deux
rapports ; elle refuse de mélanger corpus de base et corpus de permutations.

| Champ de `order_stability` | Lecture |
| --- | --- |
| `source_case_count`, `by_family` | Les 24 sources sont comptées une fois. |
| `source_coverage` | Fraction des sources dont toutes les variantes sont utilisables. |
| `source_agreement_all_cases` | Fraction des 24 sources dont toutes les variantes sont utilisables et correctes ; les absences restent au dénominateur. |
| `rules_source_agreement_all_cases` | Accord de la règle sur les mêmes 24 sources, sans corriger ses collisions. |
| `choice_invariant` | Même choix sémantique sur les six ordres ; `null` si la série est incomplète. |
| `stable_but_wrong_sources` | Sources complètes dont le choix est stable et faux. |
| `winner_changes_from_original` | Changements parmi les autres variantes utilisables ; `null` sans comparaison. |
| `max_pairwise_probability_delta` | Plus grande différence par clé entre deux distributions utilisables ; `null` si moins de deux existent. |
| `margin_top_two`, `max_tie_options` | Marge des deux probabilités maximales et clés exactement à égalité au maximum. |

Une série incomplète ne prouve pas la stabilité ; une réponse stable peut être
fausse. Des probabilités identiques peuvent donner des choix différents en
cas d'ex aequo. Une petite dérive numérique peut aussi renverser des choix
proches. Les distributions sont comparées par clé sémantique ; aucun seuil
de confiance ou tolérance d'autorisation n'est inventé.

Les statistiques de requêtes déclarent `observation_unit=request_variant`.
Le rapport apparié conserve deux résumés par source dans
`order_stability.small` et `.large`. Les variantes ne sont pas des échantillons
indépendants : `independent_sample_count=null`.
Les labels restent des fixtures ; `auto_act_allowed=false`,
`saving_claim=false`, sans sélection d'un modèle.

## Formats et preuve disponible

Le mode de base écrit toujours un manifeste v3 et un rapport v2.
Le mode `choice-order` écrit un manifeste **v4** avec `corpus_kind=choice-order`,
puis un rapport **v3** avec métadonnées de présentation et probabilités.
Les manifestes de base v1/v2/v3 restent lisibles ; un ancien lecteur ne peut
pas interpréter un manifeste v4 comme une capture de 24 cas.

Les tests vérifient l'ordre reçu sur HTTP, les 104 captures et leur relecture,
le biais de position, les ex aequo, les renversements numériques, les réponses
stables mais fausses, les arrêts et les mutations de corpus/records.
Ils utilisent un serveur HTTP simulé et des réponses authorées.
**Aucun Tev1 réel n'a été mesuré pendant cette implémentation** ;
la qualité sur Eurekai, la calibration et le coût complet restent à établir.
