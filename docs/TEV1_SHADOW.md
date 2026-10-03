# Tev1 local : capture consultative et comparaison rejouable

L'analyse des « 50 use cases » de Prompt Engineer 48 mène à une intégration
limitée : demander une décision typée à un modèle local, la vérifier, conserver
sa provenance et la comparer aux règles sur les mêmes entrées. Le transport est
optionnel. Aucune route active, autorisation, vérification de fin de tâche ou
politique de compaction n'est modifiée.

## Contrat et limites

`OllamaTev1Transport` s'injecte dans le contrat `DecisionRequest` existant.
L'import et la construction ne font aucun appel. `probe_tev1_model` inspecte un
serveur déjà lancé et un modèle déjà installé. Aucun téléchargement de poids,
installation d'Ollama, clé d'API ou SDK tiers n'est nécessaire au transport.

L'origine est un HTTP local sur l'adresse littérale `127.0.0.1` ou `::1`.
Les proxys de l'environnement et les redirections ne sont pas utilisés. Le
modèle doit être nommé explicitement `tev1:0.8b` ou `tev1:4b`. La provenance
associe la version d'Ollama (au moins 0.35) et le digest SHA-256 observé dans
`/api/tags`, normalisé avec le préfixe `sha256:`.

Chaque capture vérifie version et digest avant puis après le POST
`/v1/systemone` : cinq requêtes locales partagent une même échéance. Une
interruption du socket borne aussi les en-têtes et corps transmis lentement.
Il n'y a pas de retry. Un modèle absent, une panne, une réponse incomplète ou un
changement d'identité ne produit aucun record accepté. Le serveur ne fournit
pas de verrou atomique sur un tag : ne pas remplacer les poids pendant un run.

Les limites locales sont 64 questions, 20 choix ou niveaux par question,
6 000 caractères d'état, 64 KiB pour la requête et 1 MiB pour la réponse.
Le plafond de caractères n'est pas une mesure des tokens : garder les états
courts, le contexte effectif documenté pour Tev1 étant d'environ 2 000 tokens.
Le plafond de 20 conserve le contrat Parcimonia, même si l'API accepte davantage.
Les plans en plusieurs étapes restent la responsabilité de `decision_adapter`.

| Réponse Ollama | Record Parcimonia |
| --- | --- |
| `choice`, probabilités des options | Choix valide et distribution complète ; cohérence avec le maximum contrôlée |
| `noul` | P(vrai), complétée par P(faux) = 1 − P(vrai) |
| `score`, probabilités d'indices et `legend` | Score conservé dans [0, nombre de niveaux − 1] ; indices associés aux descriptions des niveaux |
| `confidence` | Vérifiée puis écartée ; `confidence=None`, aucune autorisation d'auto-act |
| `usage.input_tokens`, `output_tokens` | `input_tokens_total`, `output_tokens_total` ; absence conservée comme inconnue |

Un score doit correspondre à la moyenne pondérée de ses indices ; son échelle
n'est pas ramenée à [0, 1]. Les clés JSON dupliquées, NaN/Infinity, probabilités
incomplètes, types erronés et légendes permutées sont refusés. La vérification de
forme et de cohérence ne prouve pas que le jugement sémantique est juste.

Utiliser `transport.capture(request)` avec un backend épinglé et un
`DecisionBudget`. Cette méthode mesure le temps, ajoute ce temps à l'âge initial
de l'état et applique `decision_clock`. Un résultat réussi mais devenu périmé
est conservé pour analyse et reste inutilisable. Un âge inconnu face à une borne
déclarée échoue avant tout appel. Le fallback est celui déclaré dans le budget ;
le transport ne l'exécute pas et n'invente jamais un premier choix de secours.

## Corpus initial français

`tev1_cases.py` fournit 24 cas originaux, quatre par famille. Les étiquettes sont
authorées (`label_origin=fixture`), sans calibration indépendante ni résultat
de modèle réel publié ici.

| Famille | Usage envisagé |
| --- | --- |
| Mécanisme | Proposition règle/cache/modèle local/raisonnement/abstention |
| Compétence | Document/tableur/code/web/aucune demande |
| Journaux | Triage timeout/mémoire/test/authentification/inconnu |
| Cause de test | Assertion/dépendance/syntaxe/environnement/inconnu |
| Signal de fin | Contre-exemple : une citation ou promesse ne remplace pas un vérificateur |
| Pression du contexte | Contrôle numérique déterministe ; le modèle ne pilote pas la compaction |

Le corpus inclut des accents, demandes paraphrasées, citations, absence de preuve
et une instruction injectée dans un journal. Cela prépare une comparaison, sans
constituer une évaluation complète du français, de l'injection ou des entrées
hors distribution. La baseline par mots-clés conserve ses collisions : les
corriger après lecture des cas invaliderait leur rôle de comparaison initiale.

L'accord est exact pour les choix, utilise le seuil déclaré 0.5 pour les
booléens et une tolérance déclarée de 0.25 niveau pour les scores. Tous les cas
restent au dénominateur. Les réponses manquantes, mal formées ou inutilisables
ne disparaissent pas pour améliorer l'accord. Le rapport distingue couverture,
accord sur tous les cas et accord sur les seules réponses utilisables.

## Commandes

Avec l'environnement Python du dépôt installé :

```console
python examples/tev1_shadow.py plan
python examples/tev1_shadow.py preflight
python examples/tev1_shadow.py capture --model tev1:0.8b --out runs/tev1-small
python examples/tev1_shadow.py capture --model tev1:4b --out runs/tev1-large
python examples/tev1_shadow.py replay --run runs/tev1-small
python examples/tev1_shadow.py replay --run runs/tev1-large
python examples/tev1_shadow.py compare --small runs/tev1-small --large runs/tev1-large --out runs/tev1-paired.json
```

`plan` ne contacte aucun serveur. `capture` est l'appel explicite : il exige un
serveur local préexistant et refuse un dossier de sortie existant. Le budget
par défaut est 5 000 ms par cas, configurable par `--budget-ms` ; il comprend les
contrôles d'identité. Le premier appel peut inclure le chargement du modèle :
conserver et distinguer cette observation dans une mesure à froid/à chaud.

`preflight` contrôle les deux modèles déjà installés par des GET de métadonnées,
sans inférence ni téléchargement. Il refuse des versions de runtime différentes
ou deux tags pointant sur le même digest, avant de lancer une comparaison.

Le dossier contient `run.json` (corpus, identité, budget et chaque tentative),
`records/fr-XX.json` pour chaque capture effectuée et `comparison.json`.
Un run interrompu avant son manifeste final ne constitue pas un run complet.
La relecture reconstruit les requêtes depuis la révision du corpus et refuse
les changements de budget, d'identité, d'origine ou de cas. Elle n'appelle aucun
modèle et ne réécrit pas les fichiers de la capture.

Les nouveaux manifestes sont en version 2 et peuvent enregistrer une étiquette
d'environnement choisie par l'appelant (`--machine-id`) ainsi que les versions
Python du client et Ollama du serveur. Les anciens manifestes version 1 restent
rejouables avec environnement inconnu. L'étiquette ne certifie ni le matériel,
ni la charge GPU, ni l'isolation ; ne pas y mettre de secret.

## Comparaison appariée des deux tailles

`compare` relit les deux jeux de records et recalcule les réponses et accords ;
il ignore les totaux précalculés de `comparison.json`. Les rôles doivent être
0.8B et 4B, avec digests distincts, même runtime, même corpus, même budget et même
origine. Deux environnements déclarés différents sont refusés ; un environnement
absent conserve la qualité descriptive mais laisse les deltas de temps inconnus.

Le rapport conserve tous les cas, y compris les échecs, et donne les réussites
communes, celles propres à chaque modèle, les échecs communs et les résultats
par famille. Il sépare la première tentative des suivantes, avec médiane et
p95 des tentatives complètes (méthode du rang le plus proche). La charge du
modèle reste `unobserved` : « après la première tentative » ne veut pas dire
« modèle chaud ». Les deltas par cas exigent deux réponses utilisables et des
environnements déclarés identiques.

Aucun gagnant de coût ni modèle à activer n'est désigné : `selected_model=null`,
`total_cost_comparison=unavailable`, `auto_act_allowed=false`,
`saving_claim=false`. Les labels restent des fixtures et le coût des tâches
routées, des vérifications et des fallbacks n'est pas mesuré par ce harnais.
La [procédure d'exécution locale](TEV1_LOCAL_RUN.md) prépare le relais vers
l'agent du poste connecté au serveur, sans nouveau service ni changement du routage.

## Ce qui est mesuré, ce qui reste à faire

Les tests utilisent uniquement un serveur HTTP simulé et des réponses de
fixtures. Ils prouvent l'encodage réel du protocole, les refus, l'échéance et la
relecture après arrêt du serveur. Leur accord parfait simulé n'est pas une
mesure de qualité de Tev1.

Lors d'une capture réelle, le temps mural inclut les cinq requêtes, la
normalisation et la première vérification. Les compteurs de tokens viennent du
serveur ; le total reste inconnu si une tentative n'en fournit pas. VRAM,
énergie, prix et coût des traitements suivants/fallbacks restent `null`.
Le harnais mesure une décision, sans exécuter les tâches ensuite routées :
`saving_claim=false` dans tous les cas. La latence de la relecture n'est jamais
présentée comme celle du modèle.

La prochaine preuve utile est une capture 0.8B/4B sur la même révision du corpus,
puis des tâches Parcimonia réelles avec issues labellisées indépendamment,
vérificateurs nommés et coût complet (prétraitement, décision, vérification,
fallback et tâche finale). Les fixtures ne peuvent promouvoir aucun seuil.
Aucun modèle n'a été exécuté pendant l'implémentation de cette intégration.

## Sources

- [Vidéo des 50 cas](https://www.youtube.com/watch?v=HzkljQI9T40), 2 octobre 2026.
- [Code de la démonstration](https://github.com/PromptEngineer48/tev1-50-use-cases/tree/4223508420a65cdb2f950a8bbdbd7fe1c6447ac6) : exemples et benchmark, pas de code repris ici.
- [Contrat Tev1 sur Ollama](https://ollama.com/library/tev1), consulté le 3 octobre 2026.
- [Format `/api/tags`](https://docs.ollama.com/api/tags) et [schéma SystemOne](https://github.com/ollama/ollama/blob/main/docs/openapi.yaml).

Le code de ce dépôt suit sa licence Apache-2.0. Les poids ne sont pas distribués
ici ; leur licence est distincte de celle du code de démonstration.
