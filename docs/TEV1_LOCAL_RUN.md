# Relais local pour les captures Tev1

Ce document est une consigne exécutable pour l'agent du poste local connecté au
serveur de modèles. La session cloud prépare le code et les tests hors ligne ;
elle ne possède pas de liaison SSH/MCP au réseau local et ne peut pas attester
de l'état du serveur. Aucun appel réel n'a été fait depuis cette session.

## Reprendre la révision de la PR

Depuis une copie existante de Parcimonia, créer un checkout isolé de la branche
`codex/tev1-local-shadow-20261003` de la PR #13. Conserver la révision exacte avec
`git rev-parse HEAD` et suivre les consignes locales du dépôt. Ne pas écraser un
checkout ou un dossier de résultats existant.

L'environnement Python doit pouvoir importer `tiberium_ai`. Si nécessaire,
installer le dépôt dans son environnement virtuel avec
`python -m pip install -e ".[dev]"`, puis vérifier `python -m pytest -q`.
Cela installe le code du harnais ; cela n'installe pas Ollama ni de poids.

## Accès au serveur déjà configuré

Lancer directement sur le serveur via son accès habituel, ou utiliser le tunnel
SSH existant depuis le poste local. Exemple à adapter au **nom d'hôte privé
déjà configuré**, dans un terminal séparé :

```console
ssh -N -L 127.0.0.1:11435:127.0.0.1:11434 ALIAS_PRIVE_DU_SERVEUR
```

Le client se connecte alors à `http://127.0.0.1:11435`. Sur le serveur lui-même,
utiliser son endpoint loopback confirmé (souvent `http://127.0.0.1:11434`). Aucun
port public ni changement de conteneur, pilote ou configuration GPU n'est requis
par le harnais. Confirmer l'endpoint dans la configuration locale existante.

La cible de reprise prévue est une RTX 3060. Relever en lecture seule l'état des
processus, GPU et mémoire avant les captures, avec les outils déjà disponibles
(`nvidia-smi`, par exemple). Conserver la configuration du service. Des
instantanés documentent les conditions ; ils ne mesurent pas un pic VRAM ou
l'énergie. Ces dimensions restent inconnues dans le rapport.

## Contrôler puis capturer une fois

Depuis le checkout isolé, avec l'environnement Python activé, et les deux
modèles **déjà installés** :

```console
python examples/tev1_shadow.py plan
python examples/tev1_shadow.py preflight --base-url http://127.0.0.1:11435
python examples/tev1_shadow.py capture --model tev1:0.8b --base-url http://127.0.0.1:11435 --budget-ms 5000 --machine-id local-pair-01 --out runs/tev1-pair-01-small
python examples/tev1_shadow.py capture --model tev1:4b --base-url http://127.0.0.1:11435 --budget-ms 5000 --machine-id local-pair-01 --out runs/tev1-pair-01-large
python examples/tev1_shadow.py compare --small runs/tev1-pair-01-small --large runs/tev1-pair-01-large --out runs/tev1-pair-01.json
```

Adapter le port si l'exécution est directement sur le serveur. L'étiquette
`local-pair-01` est déclarée par l'opérateur : utiliser la même uniquement pour
le même chemin client/serveur et les mêmes conditions connues. Les versions
Python et Ollama sont ajoutées automatiquement ; aucune empreinte de machine,
clé, adresse réseau privée ou configuration SSH n'est enregistrée.

Arrêter la procédure si le prévol échoue : modèle absent, runtime incompatible,
connexion indisponible ou digests identiques. Le harnais ne télécharge rien.
Après une interruption ou un délai dépassé, conserver les résultats et vérifier
l'état du serveur avant de relancer une commande ; ne pas répéter un run dont
l'état est incertain. Un dossier incomplet n'est pas un run complet rejouable.

## Revenir avec les preuves

Conserver les deux dossiers complets, le rapport apparié, la révision Git et les
observations locales de conditions. La relecture peut ensuite s'effectuer sans
serveur :

```console
python examples/tev1_shadow.py replay --run runs/tev1-pair-01-small
python examples/tev1_shadow.py replay --run runs/tev1-pair-01-large
```

Rapporter les identités exactes, couverture, accord sur les 24 cas, désaccords
par famille, erreurs et temps de tentative. Les tokens absents restent inconnus.
Le premier appel peut charger un modèle ; aucun temps n'est déclaré « chaud »
sans observation de cet état.

Les états et labels sont authorés : cette première comparaison ne constitue
pas une calibration indépendante ni une économie sur des tâches réelles.
L'autorisation, la validation de fin de tâche et la compaction restent confiées
aux mécanismes existants. Aucune fusion ou activation n'est incluse dans ce relais.
