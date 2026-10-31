# Pilote local de decision : Laya, Jeff et baselines

Le 2 octobre 2026, Laya multilingue a ete charge et execute sur CPU dans
TiberiumAI. Ce premier essai ne justifie pas de remplacer la baseline : sur
six paraphrases francaises, Laya couvre correctement trois types de tache au
seuil existant de 0,90, contre quatre pour l'analyse par verbes et objets.
Ses champs predits ne correspondent pas aux champs attendus du corpus.

## Protocole et provenance

`examples/local_decision_pilot.py` reutilise le schema et le corpus existants.
Les cas d'evaluation sont `paraphrase-00`, `01`, `03`, `05`, `07`, `08`.
Le KNN utilise exclusivement les douze cas anglais `aligned-*` comme memoire.
Le schema, ses instructions et ses seuils sont identiques pour les quatre bras.
Les instructions sont celles du schema existant, en anglais ; seuls les six
prompts sont en francais. Aucun seuil n'a ete ajuste sur ces six cas.

Ces situations et etiquettes sont **redigees pour le test** (`fixture`),
pas des resultats independants de taches reelles. La separation concerne la
memoire du KNN ; elle ne prouve pas l'absence de ces textes dans l'entrainement
prealable de Laya. Les capacites n'ont pas d'etiquettes dans ce corpus et ne sont
donc pas evaluees. Aucune calibration ni economie en production n'est etablie.

## Resultats observes

Derniere execution locale avec les versions indiquees ci-dessous :

| Bras | Types corrects acceptes / 6 | Abstentions | Latence mediane par appel |
|---|---:|---:|---:|
| Regle lexicale | 0 | 6 | 0,055 ms |
| Verbes et objets | 4 | 2 | 0,139 ms |
| KNN, memoire anglaise | 0 | 6 | 0,121 ms |
| Laya multilingue | 3 | 3 | 403 ms |

Les types acceptes sont tous corrects pour les deux bras qui couvrent des cas.
Avant application du seuil, Laya choisit le bon type dans 5 cas sur 6.
Deux de ces choix corrects ont une probabilite inferieure a 0,90 et sont refuses.
Son choix errone est lui aussi refuse. Son Brier multiclasses sur les six
questions de type est de 0,121 ; cela ne mesure pas une calibration generale.

Pour les champs, Laya a une precision et un rappel de 0 sur les cas couverts.
Il omet notamment `path` et `schema`, et propose a tort `language` sur un cas.
L'analyse par verbes et objets a elle aussi un rappel de champs de 0.
Il faut reviser independamment le sens des etiquettes et des questions :
« le prompt fournit un champ » et « le travail requiert ce champ » peuvent
designer des choses differentes. Cet essai conserve leur formulation existante.

Chaque appel Laya traite **onze questions ensemble**, pas seulement le type.
La latence inclut SDK, tokenisation et validation de l'adaptateur ; elle exclut
le chargement des poids. La mediane apres le premier appel est egalement 403 ms.
Le chargement depuis le cache prend environ 8,24 s. Les mesures de six appels
dans un seul processus ne constituent pas un benchmark materiel representatif.

Apres inference, le processus occupe environ 1,75 Go de working set Windows ;
son pic est de 2,34 Go (unites decimales). Cela inclut Python, PyTorch et le
modele. La memoire propre au modele, l'energie et le cout monetaire restent
inconnus dans le rapport. Aucun GPU n'a ete utilise. Jeff n'avait pas encore ete
execute le 2 octobre ; son essai du 3 octobre est presente ci-dessous.

## Integration et reproduction

`src/tiberium_ai/laya_backend.py` implemente le protocole Reflex avec le SDK
optionnel. L'import et la construction ne chargent rien. Le chargement exige
un SHA immuable et un opt-in explicite, puis controle la revision effectivement
chargee. Le checkpoint multilingue est choisi directement, sans heuristique de
langue. Le nombre d'appels est borne ; les echecs comptent et ne sont pas retentes.
Une entree tronquee ou des options fusionnees sont refusees.

Les reponses choice, noul et score sont normalisees puis controlees par Reflex.
Le SDK arrondit les probabilites a quatre decimales : l'adaptateur n'accepte
qu'un ecart de somme compatible avec cet arrondi (0,00005 par option), avant
renormalisation. Les reponses originales restent dans la trace.
La confiance du fournisseur n'autorise aucune action dans ce pilote.

Versions observees : Laya 0.3.23, PyTorch 2.14.1 CPU, Transformers 5.18.0,
huggingface-hub 1.33.0, safetensors 0.8.0, Python 3.13.5, Windows.
Checkpoint `convaiinnovations/laya`, sous-dossier `multilingual`, revision
`55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`.

Les commandes suivantes installent et executent dans un environnement separe.
La derniere commande telecharge les poids manquants puis fait une vraie inference.

```powershell
rtk proxy uv venv runs/local-decision-pilot/venv --python 3.13
rtk proxy uv pip install --python runs/local-decision-pilot/venv/Scripts/python.exe laya==0.3.23 torch==2.14.1 transformers==5.18.0 huggingface-hub==1.33.0 safetensors==0.8.0
rtk proxy uv pip install --python runs/local-decision-pilot/venv/Scripts/python.exe --no-deps -e .
$env:USE_TF = '0'
rtk proxy runs/local-decision-pilot/venv/Scripts/python.exe examples/local_decision_pilot.py --laya --revision 55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851 --output runs/local-decision-pilot/laya-report.json
```

Le pilote a d'abord rencontre une incompatibilite avec torchvision herite de
l'environnement global. L'environnement d'essai est maintenant entierement
isole (`include-system-site-packages = false`), sans modification de celui du
projet ni de l'installation globale.

Sans `--laya`, le script execute uniquement les baselines et declare le bras
Laya `not_requested`. Les echecs de chargement et d'inference produisent un
statut explicite et un code de sortie non nul, sans score invente.

Les traces, le hash du corpus, les versions et les compteurs de memoire sont
dans `runs/local-decision-pilot/laya-report.json` (ignore par Git).
Le gel complet des dependances utilisees est dans le meme repertoire,
`requirements.txt`. La validation ciblee couvre l'adaptateur, Reflex et les
signatures ; elle ne prouve pas la qualite generale du modele.

## Decision suivante

Conserver les baselines et Laya en evaluation shadow. Avant une adaptation,
definir sur un lot de developpement francais le sens des champs et les criteres
de choix, puis reserver un lot independant annote pour l'evaluation. Comparer
ensuite Laya et un petit Jeff sur ce meme lot, avec erreurs, couverture,
latence et ressources. Une amelioration du seul type de tache ne suffit pas
a valider une signature complete.

Sources consultees le 2 octobre 2026 :
[fiche Laya](https://huggingface.co/convaiinnovations/laya/blob/55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851/README.md),
[SDK officiel](https://github.com/NandhaKishorM/laya),
[fiche Jeff](https://huggingface.co/mstrasser/Jeff-Gemma4-E2B/blob/main/README.md).

## Jeff Qwen 0.8B : execution du 3 octobre 2026

Jeff-Qwen3.5-0.8B a ete execute sur les memes six cas, avec exactement le meme
schema, les memes onze questions et les memes seuils. Le hash du corpus,
les cas, les identifiants de memoire KNN et les questions de chaque trace ont
ete compares entre les rapports. Il ne s'agit **pas de Jeff-Gemma4-E2B** :
environ 6 Go de RAM etaient libres a la preparation, alors que les poids Gemma
representent 9,3 Go avant les buffers. Aucune autre application n'a ete arretee.

| Bras | Types corrects avant filtrage / 6 | Corrects acceptes / 6 | Abstentions | Mediane par cas |
|---|---:|---:|---:|---:|
| Verbes et objets | 4 | 4 | 2 | environ 0,14 ms |
| Laya multilingue (essai du 2 octobre) | 5 | 3 | 3 | 403 ms |
| Jeff-Qwen3.5-0.8B | 6 | 4 | 2 | 7 712 ms |

Jeff s'abstient sur `paraphrase-00` (probabilite du type extract : 0,597)
et `paraphrase-05` (decide : 0,883). Ses quatre choix acceptes sont corrects.
Son Brier sur les types est 0,0544. Son rappel et sa precision de champs sur
les cas couverts restent tous deux a 0 : des champs attendus sont omis et
`language` est propose a tort. Six cas rediges pour le test ne suffisent pas
a conclure sur sa qualite generale, son francais ou sa calibration.

Les kernels `causal_conv1d` et `flash-linear-attention` ne sont pas installes.
Transformers utilise ses implementations PyTorch de reference. Le runtime
officiel charge sur CPU en float32 ; le working set du processus apres inference
est 3,62 Go et son pic 3,98 Go, Python et runtime inclus. Le chargement depuis
le cache prend environ 71,2 secondes, la mediane apres le premier cas 7,66 s.
Ces timings viennent d'un seul essai, sur une machine deja occupee.

Pour borner les buffers, Jeff traite une question par forward pass, soit onze
passes par cas ; Laya traite les onze questions ensemble. La comparaison
porte donc sur **ces integrations completes**, pas sur un debit intrinseque
des architectures. Aucun GPU ni service HTTP n'a ete lance. Les poids ont ete
telecharges auparavant ; l'execution a eu lieu avec le Hub et Transformers
en mode hors reseau. Les sommes de controle des dix fichiers telecharges
ont ete verifiees par `hf cache verify` ; les 27 fichiers de presentation
absents (videos, illustrations, etc.) n'ont pas ete necessaires au runtime.

`src/tiberium_ai/jeff_backend.py` reutilise uniquement la validation des reponses
typees de l'adaptateur Laya. Il charge le SDK Jeff et son modele propres.
Le SHA du runtime installe est controle par ses metadonnees PEP 610 ; le
checkpoint est resolu exclusivement dans le cache a sa revision immuable.
Les depassements de contexte sont refuses par la preparation du runtime.
L'anglais declare du modele ne devient pas une garantie de francais parce
que sa sortie respecte un schema. Le pilote reste shadow et ne donne aucune
autorisation d'action.

Versions : Jeff 0.2.0, PyTorch 2.14.0 CPU, Transformers 5.17.0,
huggingface-hub 1.31.0 et safetensors 0.8.0, dans un environnement independant
de Laya. Runtime officiel : `d0173b4ee317a46dee031421b713f3fc5f868cfe`.
Checkpoint : `51552f39a943d62e8387c4ea5e17026a1408729f`.

Reproduction (les commandes HF telechargent environ 1,7 Go de poids) :

```powershell
rtk proxy uv venv runs/jeff-pilot/venv --python 3.13
rtk proxy uv pip install --python runs/jeff-pilot/venv/Scripts/python.exe "jeff @ git+https://github.com/firelex/jeff.git@d0173b4ee317a46dee031421b713f3fc5f868cfe"
rtk proxy uv pip install --python runs/jeff-pilot/venv/Scripts/python.exe --no-deps -e .
rtk proxy runs/jeff-pilot/venv/Scripts/hf.exe download mstrasser/Jeff-Qwen3.5-0.8B config.json decision_config.json model.safetensors readout.safetensors tokenizer.json tokenizer_config.json processor_config.json chat_template.jinja LICENSE NOTICE --revision 51552f39a943d62e8387c4ea5e17026a1408729f
$env:USE_TF = '0'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
rtk proxy runs/jeff-pilot/venv/Scripts/python.exe examples/local_decision_pilot.py --jeff --jeff-revision 51552f39a943d62e8387c4ea5e17026a1408729f --jeff-runtime-revision d0173b4ee317a46dee031421b713f3fc5f868cfe --output runs/jeff-pilot/report.json
rtk proxy .venv/Scripts/python.exe examples/compare_decision_pilots.py runs/local-decision-pilot/laya-report.json runs/jeff-pilot/report.json --output runs/jeff-pilot/comparison.json
```

Les deux bras neuronaux se lancent dans des processus differents pour conserver
une mesure de memoire exploitable. Les rapports complets et le gel des
dependances sont dans `runs/jeff-pilot/` (ignore par Git).
La validation ciblee termine avec **114 tests passes**.

### Complementarite observee, uniquement par replay

En reprenant les choix deja captures, utiliser la reponse verbes/objets
quand elle atteint 0,90 puis Jeff sinon couvre correctement **5 types sur 6**.
Ce replay est genere par `examples/compare_decision_pilots.py` ; il refuse
des corpus ou questions differents et garde `claim_allowed=false`.
Il ne charge aucun modele et **n'execute pas une route composee**. Sa latence
et son cout sont inconnus ; il ne valide ni les champs ni une signature complete.

La prochaine porte reste un corpus francais annote independamment, avec
semantique explicite des champs et lot d'evaluation reserve. Jeff est un
candidat interessant pour le type de tache ; les champs et le cout CPU
empechent sa promotion actuelle comme remplacant general.

Sources reverifiees le 3 octobre 2026 :
[runtime officiel fige](https://github.com/firelex/jeff/tree/d0173b4ee317a46dee031421b713f3fc5f868cfe),
[checkpoint Qwen 0.8B fige](https://huggingface.co/mstrasser/Jeff-Qwen3.5-0.8B/tree/51552f39a943d62e8387c4ea5e17026a1408729f).
