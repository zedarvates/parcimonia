# Parcimonia 0.5.0 : livraison locale et qualification

Cette version livre l'ensemble de la bibliothèque actuelle sous son nom Python
historique `tiberium_ai` et son nom de distribution `tiberium-ai`. Elle ajoute la
commande installée `parcimonia`. Le plugin indépendant `parcimonia-local` conserve
sa version 0.4.1 et ses empreintes. Les archives restent locales.

## Utilisation

Dans un environnement Python dédié, installer la wheel livrée :

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install --no-index ./tiberium_ai-0.5.0-py3-none-any.whl
.venv/Scripts/parcimonia.exe --version
.venv/Scripts/parcimonia.exe rules --input request.json --enforce-rules
```

Exemple de `request.json` :

```json
{"change":{"path":"example.py","after":"value = 1"},"rules":[]}
```

Les règles retournent 0 pour `pass`, 10 pour `block`, 11 pour `review` avec
`--enforce-rules`. Une entrée invalide retourne 2 et un objet JSON d'erreur, sans
trace d'exception contenant les données. Les clés dupliquées, NaN, Infinity,
débordements flottants et entrées de plus de 16 Mio sont refusés, y compris dans
les réponses enregistrées. Les autres recettes gardent leur contrat existant.

Sous Linux, les exécutables d'un environnement sont sous `.venv/bin/`.
`python -m tiberium_ai.agent_recipes` expose la même commande sur les deux systèmes.
La bibliothèque et le plugin n'ont aucune dépendance Python d'exécution externe.
Node est nécessaire pour qualifier le JavaScript des interfaces de revue.

## Contrats et limites

Les exports Python existants, signatures des recettes, formats de preuve et
identifiants de vérificateurs sont conservés. `tiberium_ai.__version__`, la
métadonnée du paquet et `parcimonia --version` partagent une source de version.
Une évolution incompatible demandera une nouvelle version et une migration
documentée ; les données anciennes gardent leur version de schéma.

Le routeur shadow, le calcul local conseillé, la sélection de contexte et la
préparation/reprise de tâches restent consultatifs. Les métadonnées de profils
ne valent pas autorisation. Le mode actif existant exige toujours sa politique,
ses budgets, son sandbox et son arrêt d'urgence. Son idempotence est limitée à
l'instance en mémoire : un hôte doit conserver son propre registre durable avant
d'exécuter des effets au-delà d'une instance ou d'un redémarrage. Ne pas rejouer
automatiquement un effet dont le résultat est incertain.

Les fournisseurs réseau restent explicitement activables par le consommateur.
Les modèles, apprentissages, corpus privés, économies facturées et performances
en production ne sont pas certifiés par des tests hors réseau. Les pilotes et
résultats négatifs restent documentés dans les sources distribuées. Cette
livraison ne clôt pas les recherches et mesures encore ouvertes dans V1_GATES.

## Refaire la qualification

Utiliser un environnement de développement existant, avec `.[dev,release]`.
Préparer une fois un cache de wheels de test ; la qualification suivante fonctionne
sans accès réseau :

```powershell
python -m pip download --only-binary=:all: --implementation py --abi none --platform any --python-version 3.10 --dest runs/release-wheelhouse pytest==9.1.1 tomli exceptiongroup typing_extensions colorama
python scripts/qualify_release.py --output runs/release-0.5.0 --wheelhouse runs/release-wheelhouse --python C:/Python314/python.exe --python CHEMIN_PYTHON_310/python.exe
```

Les chemins d'interpréteurs doivent désigner des installations déjà présentes.
Le dossier de sortie doit être nouveau : aucune preuve précédente n'est écrasée.
La qualification vérifie les sources exactes de la wheel, reconstruit wheel et
archive source à partir de l'archive extraite, et exige des empreintes identiques.
Les archives sources excluent `.git`, les environnements, caches, sorties `runs`,
le répertoire cloud et les investigations `docs/spikes`.

Pour chaque interpréteur, elle installe la wheel dans un environnement isolé,
contrôle ses dépendances et tous les imports, vérifie la commande installée,
exécute la suite complète depuis l'archive extraite et contrôle que les modules
testés viennent du paquet installé. Aucune erreur, échec ou omission de test
n'est accepté pour une qualification complète. Le plugin extrait est vérifié
par son inventaire, initialisé en stdio, puis listé avant un appel réel. Ce
contrôle stdio est distinct d'une qualification native dans une session Codex.

Les archives, inventaires, logs, empreintes et résultats JUnit sont conservés.
Les environnements temporaires sont retirés après réussite ; après échec ils
restent disponibles pour diagnostic. Budget prévu : 128 Mio, propriétaire : le
processus de qualification. Une seule opération lourde à la fois sur Odin ; lancer
ce script via le reçu de coordination du chantier.

## Validation distante et retour arrière

La matrice CI vérifie Python 3.10 et 3.14 sous Windows et Linux lorsqu'elle est
exécutée. Une configuration de CI n'est pas la preuve d'une exécution distante.
Le fichier `qualification.json` décrit les interpréteurs effectivement testés.

Pour revenir à une livraison précédente, arrêter le consommateur concerné et
réinstaller sa wheel conservée dans son environnement dédié. La qualification ne
modifie ni installation Codex active, ni configuration partagée, ni service. Une
publication, un tag ou une mise à jour du profil actif est une opération distincte.
