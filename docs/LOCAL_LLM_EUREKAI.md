# LLM local de secours pour Eurekaï

Objectif : un assistant de code, d'ingénierie et de jeux/physique, en français et
en anglais, utilisable sans crédits API. Partir de poids ouverts quantifiés et
du LM Studio déjà installé, puis raccorder les tâches au caller existant.

## Configuration de départ à qualifier

| Étape | Candidat et réglage initial | Passage à l'étape suivante |
| --- | --- | --- |
| Remise en service | Qwen2.5-Coder-7B-Instruct GGUF Q4_K_M, une RTX 3060, contexte 4–8k | Réponse courte puis tâche de code vérifiée sans erreur mémoire |
| Modèle de travail | Qwen3-Coder-30B-A3B-Instruct GGUF Q4_K_M, répartition à tester sur deux RTX 3060, contexte 8k | Mémoire, latence et qualité mesurées sur les mêmes tâches |
| Boucles des éditeurs | Propositions du modèle puis vérifications techniques par le caller ; vision/rendu séparés si nécessaire | Exports, captures comparables et meilleur candidat conservés par le véritable éditeur |

Les 2 × 12 Go de VRAM sont deux espaces distincts. Le moteur doit répartir les
poids ; le cache KV et les buffers occupent aussi de la mémoire. Le 30B est un
MoE de 30,5 milliards de paramètres au total, dont 3,3 milliards activés par token :
ce dernier chiffre ne décrit pas la mémoire occupée par tous les experts.
Tailles exactes des fichiers Q4_K_M et place libre sont à relever avant tout
téléchargement. Aucun débit ni chargement réussi n'est mesuré sur Eurekaï.

RAM, troisième GPU, Hailo, topologie PCIe et état des disques restent à confirmer.
Commencer sur une machine ; plusieurs hôtes serviront d'abord des tâches
indépendantes. Offload RAM/disque et distribution réseau seront comparés ensuite.
LM Studio est le premier runtime à remettre en état ; évaluer vLLM après la
baseline si un besoin de concurrence le justifie.

## Premier passage sur Eurekaï

Depuis cette branche, sur la machine qui héberge LM Studio :

```sh
PYTHONPATH=src python3 examples/eurekai_diagnostic.py --out diagnostic-local.json
```

Cette commande n'infère pas. Elle observe `/v1/models` et inventorie l'appelant.
Le diagnostic précède un nouveau téléchargement : version, GPU visibles, RAM
et volume des poids. La panne et sa correction restent à établir sur place.

## Worker texte appelable sans interface graphique

`examples/local_chat_worker.py` lit une requête JSON sur stdin et émet sa réponse
JSON sur stdout. Exemple de `request.json`, avec un identifiant `model` réel
relevé dans LM Studio (le nom du dépôt Hugging Face ne suffit pas forcément) :

```json
{
  "schema_version": 1,
  "task_id": "eurekai-code-smoke-1",
  "model": "IDENTIFIANT_REEL_DU_MODELE",
  "max_tokens": 256,
  "temperature": 0,
  "messages": [
    {"role": "system", "content": "Assistant de code FR/EN. Propose des corrections vérifiables et signale les informations manquantes."},
    {"role": "user", "content": "Propose une fonction Python clamp(x, lo, hi), refuse lo > hi et donne trois tests de limites."}
  ]
}
```

```sh
PYTHONPATH=src python3 examples/local_chat_worker.py < request.json
```

Le lancement demande explicitement une inférence et peut déclencher le chargement
JIT du modèle demandé. Aucun compte ou clé OpenAI n'est requis. Un serveur LM
Studio exigeant une authentification répondra 401/403 : cette version ne gère pas
ses jetons d'accès.

Depuis Odin ou un autre poste, si l'API est exposée sur le LAN :

```sh
PYTHONPATH=src python3 examples/local_chat_worker.py \
  --base-url http://192.168.1.47:1234 --allow-lan < request.json
```

Revalider cette adresse connue d'Eurekaï. Cette commande ne crée aucun accès
cloud vers le LAN et ne prouve pas que le serveur écoute sur cette interface.

Code de sortie 0 seulement pour `completed`, 2 sinon. `truncated` conserve le
texte partiel mais ne vaut pas réussite. Les compteurs absents restent `null`.
Un POST au maximum : aucun retry, repli cloud ou commande du modèle exécutée.
`--timeout` borne la phase HTTP, pas l'attente d'EOF sur stdin ; l'appelant doit
fermer stdin et borner la durée du sous-processus. Un timeout client n'arrête
pas forcément l'inférence du serveur. Le caller conserve les réponses et journaux
privés selon ses besoins et ne les committe pas.

## Raccordement à l'agent et adaptation

Un agent local peut lancer le worker ou appeler
`tiberium_ai.local_chat.chat_completion`. Il reçoit des propositions à appliquer
et vérifier avec ses outils. Ce worker n'est pas encore un agent autonome ; cette
session cloud n'a pas de chemin direct confirmé vers l'API d'Eurekaï.

Dans `improve_candidate`, `produce` peut appeler ce client, refuser un statut
autre que `completed`, puis transformer la réponse selon un schéma explicite en
candidat. Garder les vrais contrôles dans `VerifierRegistry` et le score dans
`evaluate`. Du texte ou une forme JSON valide ne prouvent ni code correct ni
export GLB ni qualité visuelle. Voir le [contrat de boucle](LOCAL_AGENT_BOOTSTRAP.md).

Le second cerveau existant alimente le modèle via des extraits cités du moteur
RAG/DAG, avec `--context-file` sur le worker ou `--vault-dir` et `--rag-query`
pour une commande RAG explicitement configurée. Voir le
[raccord de mémoire et ses limites](LOCAL_KNOWLEDGE.md), y compris le maintien
d'un corpus utilisable lorsque la synchronisation cloud est indisponible.

Adapter d'abord par consignes FR/EN, contexte de projet récupéré et outils de
vérification. Constituer un jeu de tâches réelles avant un éventuel LoRA.
Supprimer des langues ne retire pas des blocs indépendants de poids. Draft /
speculative decoding, cache de préfixe et offload d'experts se comparent après
une première baseline stable ; aucun gain n'est établi ici.

Client et worker testés hors ligne sur serveur simulé. Aucun poids téléchargé,
modèle chargé ou essai matériel réalisé par ce travail. TASK-074 reste ouverte.

## Sources primaires vérifiées le 30 octobre 2026

- [API LM Studio](https://lmstudio.ai/docs/developer/openai-compat/chat-completions).
- [Qwen3-Coder officiel](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct) et [GGUF LM Studio communautaire](https://huggingface.co/lmstudio-community/Qwen3-Coder-30B-A3B-Instruct-GGUF).
- [Qwen2.5-Coder-7B GGUF officiel](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF).
