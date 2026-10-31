# Relier le LLM local au second cerveau existant

Le modèle de code utilise la mémoire commune comme source externe. Les poids
du modèle, les connaissances documentaires et la vérification ont des rôles
distincts : récupérer une information ne garantit pas de raisonner correctement
avec elle. Réutiliser le coffre Markdown, l'index et le graphe existants ; ne pas
créer un autre wiki ou déclarer un nouveau stockage opérationnel.

## Chemin disponible pour les extraits

Dans le coffre existant, la commande documentée est :

```sh
python tools/rag_dag_engine.py rag --query "QUESTION" --top 3
```

Ce script appartient au coffre, pas à Parcimonia. Sa documentation décrit un
index SQLite FTS5/BM25 et le parcours des relations des notes ; `rag` prépare
des extraits cités sans lancer de modèle. Vérifier la version et l'état réels
du script et de l'index sur le poste avant raccordement. Sauvegarder sa sortie
en UTF-8 dans un fichier privé choisi par l'appelant, en conservant les citations.

Le worker accepte désormais ce fichier explicitement :

```sh
PYTHONPATH=src python3 examples/local_chat_worker.py \
  --context-file contexte-rag.txt < request.json
```

`request.json` garde son enveloppe d'entrée version 1. Le texte documentaire est
borné à 16 Kio, encapsulé comme données, accompagné d'une instruction de citation
et séparé de la tâche. Une lecture invalide ou un dépassement empêche le POST.
Ce mode ne recherche pas dans le coffre et n'exécute aucune instruction d'une
note. La séparation de messages ne garantit pas à elle seule qu'un modèle
résistera à toutes les injections : les autorisations et vérifications restent
dans l'appelant.

Sans cette option, le résultat reste version 1. Avec cette option, le résultat
est explicitement version 2 et ajoute `context` : empreinte SHA-256 des octets
lus, taille UTF-8, origine `provided_rag_context` et fraîcheur `not_assessed`.
Cela identifie exactement le contexte fourni ; cela ne certifie pas la vérité,
la fraîcheur des notes ni leur utilisation effective par le modèle.

## Rechercher et répondre dans le même appel

Une fois le script du coffre qualifié, l'appelant peut éviter le fichier
intermédiaire :

```sh
PYTHONPATH=src python3 examples/local_chat_worker.py \
  --vault-dir /chemin/du/coffre-existant \
  --rag-query "QUESTION DE RECHERCHE" --rag-top 3 --rag-timeout 15 < request.json
```

Le chemin du coffre et la requête de recherche sont des options du processus,
pas des instructions tirées des notes. L'adaptateur lance une seule commande
fixe avec l'interpréteur Python courant et le dossier du coffre comme répertoire
de travail : `tools/rag_dag_engine.py rag --query ... --top ...`. L'option
`--rag-python` sélectionne au besoin l'interpréteur de cette installation.
`--context-file` et `--vault-dir` sont mutuellement exclusifs.

Une recherche réussie fournit ses octets UTF-8 exacts au même mécanisme de
contexte. Le résultat est explicitement version 3 : il conserve le contexte,
les empreintes du script observées avant et après, celle de la requête, le code
de sortie et le temps mesuré. Le contenu RAG n'est pas dupliqué dans le reçu
`retrieval`. Les chemins privés et stderr n'y sont pas enregistrés.

Un échec de recherche, une sortie trop grande, un UTF-8 invalide, une source
modifiée ou un timeout bloque l'inférence : `retrieval_failed`, code de sortie
2, sans retry ni appel de secours. Une recherche `completed` signifie que la
commande a terminé avec une sortie textuelle valide ; cela ne prouve pas que
les bonnes sources ont été retrouvées. Le caller vérifie toujours les citations.

La sortie RAG est bornée à 16 Kio, stderr à 4 Kio ; aucun des deux flux n'est
capturé sans limite. Le timeout RAG couvre le processus et la collecte des flux,
avec une courte marge de nettoyage. Les lectures de fichiers et la création
du processus par l'OS ne sont pas préemptées. Seul le fils direct est arrêté ;
l'appelant garde le budget global du worker et la gestion d'éventuels descendants.

L'adaptateur ne demande ni réindexation ni synchronisation. Il ne constitue pas
un sandbox et ne garantit pas les effets internes du programme externe. Son
code, ses dépendances, son index et ses droits doivent être vérifiés sur le
poste avant activation. Le script réel n'était pas accessible dans les sources
inspectées ici ; les essais utilisent des programmes explicitement écrits comme
fixtures. Ni cette compatibilité documentaire ni les tests ne qualifient le
moteur réel du PC.

Pour qualifier le moteur sans demander d'inférence, l'appelant peut utiliser
directement la primitive de lecture :

```python
from tiberium_ai.local_retrieval import retrieve_context

result = retrieve_context("/chemin/du/coffre-existant", "QUESTION", top=3)
print({key: value for key, value in result.items() if key != "content"})
```

Dans les reçus du worker, `execution_performed` désigne l'exécution d'actions
proposées par le modèle ; la commande de préparation explicitement choisie par
l'appelant est observée séparément dans `retrieval.attempted`.

## Fonctionner quand les crédits cloud sont épuisés

Le poste d'inférence doit disposer d'une copie exploitable du corpus, des scripts
et d'un index compatible. Une page Space seule ou une synchronisation qui
nécessite Codex ne suffit pas à garantir ce fonctionnement. Conserver le dernier
instantané local utilisable si la synchronisation cloud s'arrête.

Réutiliser le mécanisme existant de rapprochement des notes et de conservation
des conflits. La synchronisation Markdown ne transporte pas automatiquement les
scripts, les Canvas, les bases SQLite ni les poids. La reconstruction d'un index
local est une étape distincte à qualifier sur la cible. Ne pas recopier une base
en cours d'écriture comme si elle constituait un snapshot cohérent.

## Combler les lacunes par le mécanisme adapté

| Lacune observée | Réponse à évaluer | Preuve attendue |
| --- | --- | --- |
| Fait ou décision projet absent du modèle | Note sourcée, version et contexte récupérés | Bonne note retrouvée et citation exacte |
| Mauvais document sélectionné | Recherche ciblée puis voisins ou chemins du graphe | Chemin explicite et relations effectivement présentes |
| Information ancienne ou contradictoire | Dates, versions et conflits conservés | Réserve explicite, pas de fusion silencieuse |
| Erreur de code ou de calcul | Compilateur, tests, calculateur ou solveur | Résultat de l'outil sur les entrées exactes |
| Cas non couvert | Lacune enregistrée pour enrichissement vérifié | Abstention plutôt qu'une source inventée |

Les résultats générés restent des propositions tant qu'ils ne sont pas vérifiés.
Un épisode réussi peut enrichir la mémoire avec sa source, sa version et sa
condition d'invalidation ; aucune auto-promotion n'est ajoutée par le worker.

## Piste Prospector à comparer après la baseline

Le [dépôt officiel](https://github.com/lamm-mit/Prospector) et le
[préprint du 27 octobre 2026](https://arxiv.org/abs/2610.37121) décrivent une
politique Qwen3.5 post-entraînée qui appelle `find`, `expand` et `connect` sur un
graphe externe. Le dépôt documente le réemploi à poids figés sur un nouveau
GraphML dirigé, avec attribut `relation`, backend et questions d'évaluation.

Comparer cette politique au moteur déterministe existant sur les mêmes questions
et sources avant de l'adopter. Les liens de navigation d'un wiki ne doivent pas
être convertis implicitement en relations causales. La gate publiée contrôle
que les arêtes citées ont été vues ; elle ne prouve pas leur vérité.

Les résultats publiés portent sur les graphes scientifiques des auteurs. Leur
transfert ne valide pas notre wiki français, le code ou les jeux. Les drivers
publiés incluent transformers, vLLM et MLX ; aucune conversion GGUF, compatibilité
LM Studio ou performance RTX 3060 n'est qualifiée ici. Aucun poids Prospector
n'a été téléchargé. La vidéo fournie n'était accessible que par ses métadonnées ;
les mécanismes ci-dessus proviennent des sources primaires, pas de paroles vues
ou entendues dans la vidéo.
