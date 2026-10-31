# Pilote local : attention et nouveaute

Increment du 8 octobre 2026, issu de [l'analyse des videos Jev](ANALYSE_VIDEOS_JEV_2026-10-08.md).
Les nouvelles recettes sont dans `tiberium_ai.agent_recipes.source_triage`.
Elles reutilisent `DecisionSession`, la validation Reflex, le JSON canonique,
les budgets, les mesures de pipeline et le registre de verificateurs.

## Executer le pilote hors reseau

```powershell
rtk proxy .venv/Scripts/python.exe examples/source_triage_pilot.py --output runs/source-triage/pilot-20261008.json
```

Le fichier est cree exclusivement ; une autre execution doit choisir un nouveau
nom. La collection, la recherche lexicale, la politique et la verification
s'executent localement. Les jugements semantiques sont des reponses injectees
sur douze scenarios synthetiques, dans `examples/fixtures/source_triage.json`.
Les noms de modeles, faits et references `fixture:` sont inventes.

Le rapport conserve toutes les sources originales, le contexte, les candidats,
les avis, les appels et les mesures par phase. La baseline propose de traiter
chaque source ; le candidat propose traitement, report ou ecartement recuperable.
Il n'y a ni generation LLM, ni suppression, ni envoi, ni modification de wiki.

Sur les douze fixtures : six propositions `process`, quatre `defer`, deux
`skip_candidate`, douze originaux conserves. Aucun des dix cas declares
`must_retain` par l'auteur du corpus n'est propose a l'ecartement. Cette declaration
et les reponses injectees ne sont pas des labels independants ; ce resultat
valide la politique synthetique, pas la qualite d'un modele.

## Contrats d'entree

Une source contient `id`, `title`, `text`, `reference`, et peut ajouter
`published_at`, `event_at`, `protected`. Les textes sont complets, sans troncature
implicite. Les dates, si connues, sont ISO avec fuseau ; `null` signifie inconnu.
`protected` est une instruction de conservation fournie par l'hote, jamais une
autorisation. Les autres champs sont refuses. L'identifiant designe une revision
de source ; deux versions a comparer doivent porter des identifiants distincts.
La reference est une provenance declaree, sans consultation reseau implicite.

Le contexte contient `id`, `revision`, `objective` et peut ajouter `constraints`,
`required_context`, `values`. Un champ requis absent ou nul produit
`needs_context`, avant tout appel. Les valeurs JSON non finies sont refusees.
Les objectifs et valeurs sont effectivement transmis au backend pour ce nouveau
protocole ; ils ne modifient pas le prompt historique de la cascade de signature.

L'hote fournit les objectifs, contraintes et la protection par un canal fiable.
Les documents externes sont toujours des donnees non fiables. Les mentions
"ignore les regles" ou "je suis le proprietaire" dans une source restent du texte.
Les recettes ne certifient pas la detection d'injection et ne donnent pas d'autorite
aux declarations des documents.

## Recette attention.triage@1

```python
from tiberium_ai.agent_recipes import DecisionSession, triage_attention

source = {"id": "article-1", "title": "Local decision model",
          "text": "A complete source excerpt supplied by the host.",
          "reference": "local:article-1"}
context = {"id": "parcimonia", "revision": "snapshot-1",
           "objective": "Compare CPU decision models",
           "constraints": ["Retain corrections"],
           "required_context": ["hardware"], "values": {"hardware": "CPU"}}
result = triage_attention(source, context, DecisionSession())
# No backend: an abstained, recoverable defer proposal.
```

Trois questions independantes partagent un appel : pertinent pour l'objectif,
exploitable, besoin de contexte supplementaire. Les scores Noul doivent etre
coherents avec leur distribution. Le seuil de session est une politique de pilote,
pas une calibration mesuree. La politique retourne :

- `needs_context` si le contexte requis manque ou si son besoin n'est pas exclu
  par les signaux du backend ;
- `skip_candidate` pour une pertinence suffisamment faible, sauf source protegee ;
- `process` pour une pertinence et une exploitabilite suffisamment fortes ;
- `defer` dans les autres cas, y compris backend absent, erreur ou deadline.

La distinction entre `skip_candidate` et une suppression est explicite : le texte
original, le contexte et leurs hashes restent dans `data.recall`. Aucune proposition
n'a `auto_act_allowed=true` ou `delete_allowed=true`.

## Recherche locale et knowledge.novelty@1

`retrieve_source_candidates(source, records)` consulte un snapshot de records
fourni explicitement. Par defaut : 500 records maximum, 1 MiB pour l'ensemble,
huit candidats ; la limite de shortlist est configurable jusqu'a 19. Les budgets
de lecture sont refuses avant la selection, sans tronquer silencieusement les
records. La priorite est copie exacte, puis recouvrement lexical ; les egalites
sont triees par identifiant. Aucun index distant ou scan du disque n'est lance.

`assess_novelty(source, candidates, session)` retourne `duplicate`, `update`,
`contradiction`, `novel` ou `uncertain`. Il compare titre, texte et date d'evenement
pour une copie exacte ; reference et date de republication peuvent differer.
Les dates d'evenement sont comparees litteralement : deux representations du
meme instant peuvent donc rester des candidats semantiques. Une mise a jour
du titre ou d'une claim n'est pas une copie exacte. Cette voie ne fait aucun appel.

Les autres relations sont demandees dans un lot unique, avec un nom de question
lie a chaque position de candidat. Confiance et probabilite du label doivent
toutes deux atteindre le seuil. Une seule comparaison inconnue empeche de conclure
`duplicate`. Une mise a jour ou contradiction est conservee, meme si une autre
comparaison est une copie exacte. Sans candidat, l'avis est `uncertain` ; un
avis `novel` reste relatif aux candidats presents. `search_exhaustive` reste faux.

La politique composee du pilote garde les reports pour contexte inconnu. Elle
empeche l'ecartement d'une source protegee et reporte une proposition de doublon
lorsque la recherche a limite sa shortlist. Chaque decision reste recuperable.

## CLI JSON et verifier

Les commandes sont disponibles dans l'interface de recettes existante :

```powershell
rtk proxy .venv/Scripts/python.exe -m tiberium_ai.agent_recipes attention --input attention.json
rtk proxy .venv/Scripts/python.exe -m tiberium_ai.agent_recipes source-search --input search.json
rtk proxy .venv/Scripts/python.exe -m tiberium_ai.agent_recipes novelty --input novelty.json
```

`attention.json` contient `source` et `context`. `search.json` contient `source`
et `records`, et peut declarer les bornes. `novelty.json` contient `source` et
`candidates`. `--answers` relit des reponses Reflex normalisees hors reseau.
Les traces CLI contiennent l'entree : conserver les donnees privees dans `runs/`,
ignore par Git, et ne pas les publier. Le pilote fourni n'utilise que des fixtures.

`register_source_verifier(registry)` ajoute `source.recipe.structure@1` au registre
fourni, sans modifier le manifeste des neuf recettes preexistantes ni activer une
route. `verify_source_structure` relie l'avis a son etat, aux hashes, aux originaux,
aux candidats et aux regles de combinaison. Il refuse les permissions forgees,
pertes de source, mauvaises identites et decisions incompatibles avec les signaux.
Il ne prouve ni l'authenticite d'une source, ni la veracite d'une claim, ni la
pertinence semantique des reponses, ni l'independance des annotations.

## Mesures, limites et prochaine porte

La mesure porte sur les operations locales de politique et leurs verificateurs,
avec de vrais temps `perf_counter`. La baseline ne paie pas de generation ; les
six traitements proposes ne sont donc pas six appels LLM observes. Le rapport
apparie les hashes d'entree, garde les couts inconnus et refuse une comparaison
de cout certifiee. `quality_metrics` et `cost_savings` sont nuls au sens de non
renseignes ; `model_inference_executed`, `claim_allowed` et `auto_act_allowed`
restent faux. La deadline ne preempte pas un callback synchrone.

La prochaine porte est une collection locale de sources reelles pour ces deux
familles, avec contexte explicite, provenance et revue independante. Annoter les
informations a conserver et les relations, sans exposer les reponses du candidat
aux annotateurs. Grouper evenements et versions entre developpement et test ;
figer les seuils sur developpement. Comparer ensuite regles/cache, baseline et
backend disponible sur les memes entrees, avec verification, corrections et cout
de generation. Le corpus existant de signatures ne valide pas ces nouvelles familles.

La preparation d'un premier lot reel et son formulaire hors ligne sont maintenant
documentes dans [la revue des sources](SOURCE_TRIAGE_REVIEW.md). Les quatorze cas
gardent des labels vierges ; leur presence ne valide pas les jugements du pilote.
