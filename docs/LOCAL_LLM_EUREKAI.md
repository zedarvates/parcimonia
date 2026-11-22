# LLM local de secours pour Eurekaï

Objectif : un assistant de code, d'ingénierie et de jeux/physique, en français et
en anglais, utilisable sans crédits API. Partir de poids ouverts quantifiés et
du LM Studio déjà installé, puis raccorder les tâches au caller existant.

## Configuration de départ à qualifier

Mise à jour du 31 octobre : le [raccord vision](LOCAL_VISION.md) utilise le même
worker et le même contexte RAG. Les candidats multimodaux retenus pour l'essai
sont Qwen3.5-9B Q4 pour le travail courant et Qwen3.8-27B Q4 pour les tâches
complexes. Ils incluent la vision dans leur architecture ; le paquet et le
runtime installés doivent encore être qualifiés. Le tableau ci-dessous conserve
les candidats texte du plan initial comme recours, sans les déclarer chargés.

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


## Pilote LFM3 pour les tâches courtes — 1 novembre 2026

**État : protocole proposé.** Aucun poids téléchargé, service modifié ou modèle
évalué par cet ajout. Le worker texte et les raccords mémoire existants sont
réutilisés ; aucun routage automatique n'est activé.

LFM3-1.7B est un candidat pour l'extraction, les réponses courtes avec sources,
les propositions d'outils et le dialogue PNJ cadré. Sa carte prend explicitement
en charge le français et déconseille le coding agentique ainsi que le
raisonnement complexe. Il complète le profil principal de code. Le résultat
d'un PNJ reste une proposition ; inventaire, quêtes et état du monde conservent
leurs autorités déterministes.

### Compatibilité avant tout chargement

- Inventorier le serveur existant, les modèles réellement présents et leurs
  digests. Les noms Qwen rapportés le 31 octobre ne prouvent pas leur présence
  actuelle. Vérifier RAM, VRAM par carte et disque avant un nouveau téléchargement.
- Ollama **0.40.13** annonce LFM3 sous Linux et Windows. La **0.40.12** ne suffit
  pas pour notre hôte Linux : son annonce était limitée à Apple silicon.
- Le GGUF officiel documente llama.cpp **b11960 / v0.8.0 ou plus récent**.
  Pour LM Studio, sa carte exige le moteur llama.cpp 2.65.1 ou plus récent.
  Vérifier ce moteur plutôt que déduire son support du numéro de l'application.
- Choisir un seul moteur pour la comparaison et garder ses versions fixes.
  La voie Ollama réutilise un service déjà installé ; elle ne demande pas une
  migration automatique du runtime choisi pour le profil principal.
- Conserver le dépôt et la révision des poids, la quantification et le hash du
  fichier ou digest observé. Le code Parcimonia reste Apache-2.0 ; les poids
  LFM3 restent sous LFM Open License v1.0. Le pilote ne les embarque pas.

Réglages de départ proposés : une requête et un modèle chargé à la fois,
contexte serveur de **4096 tokens**, sortie de **512 tokens maximum**,
température 0.1. Conserver une marge système et GPU mesurée avant de démarrer.
Le petit modèle texte et sa fenêtre maximale ne dimensionnent pas toute la
mémoire du serveur. Un arrêt client ne prouve pas l'arrêt du calcul distant.

### Deux étapes, avec leurs contrats réels

**A — texte et contexte existants.** Le diagnostic `examples/eurekai_diagnostic.py`
inspecte l'appelant et `/v1/models` sans inférence. Le worker
`examples/local_chat_worker.py` peut ensuite soumettre explicitement une
requête texte v1 à un endpoint compatible, avec un identifiant réellement
observé. Un endpoint Ollama utilise habituellement le port 11434 : l'origine
doit être confirmée. Les commandes précédentes gardent leur valeur par défaut
LM Studio tant qu'aucune autre origine n'est explicitement fournie.

Le worker actuel accepte `model`, `messages`, `max_tokens` et `temperature`
dans son enveloppe. Il ne prend pas en charge `tools`, `tool_choice` ou
`response_format`. Demander une forme JSON dans le prompt mesure donc un
suivi de consigne, pas une sortie contrainte par schéma. Valider ensuite le
JSON, ses valeurs et ses sources avec les contrôles du caller.

**B — outils natifs et JSON contraint, à développer/qualifier séparément.**
LFM3 utilise un format XML de tool calling différent de LFM2/2.5. Le serveur
doit fournir des appels normalisés, puis le caller doit contrôler nom, types
et arguments avant un éventuel dispatch. Du XML restant dans le texte est un
échec d'intégration ; aucune exécution par regex de ce texte n'est autorisée.

Ollama documente `tools` et `response_format` sur sa surface compatible.
Le réglage `num_ctx` n'est pas un champ OpenAI standard : le configurer côté
modèle/serveur ou dans un adaptateur natif explicitement versionné. Ne pas
ajouter ces champs silencieusement au contrat texte fermé. Le transport Tev1
est spécifique à ses modèles et à SystemOne ; changer son nom de modèle ne
le transforme pas en transport LFM3.

### Jeu comparatif : 24 fixtures françaises

Le [pilote texte exécutable](LOCAL_TEXT_EVAL.md) fournit maintenant ces fixtures,
une capture bornée et une relecture hors ligne. Il mesure des propositions
d'outils en JSON, pas les appels d'outils natifs de l'étape B.

| Bloc | Nombre | Couverture et attendu |
| --- | ---: | --- |
| Outils proposés puis natifs | 8 | recherche mémoire par projet ; recette StoryCore ; statut Odin/Thor ; état d'un PNJ par ID ; deux lectures ; machine ambiguë ; salutation sans appel |
| RAG | 8 | fait sourcé ; absence ; contradiction ; source remplacée ; réponse utilisant deux extraits ; unités ; instruction injectée dans un document ; donnée d'un autre projet |
| Extraction JSON | 4 | tâche structurée ; champ inconnu à null ; enum fermé ; tags limités aux métadonnées fournies |
| Limites et abstention | 4 | PR non prouvée fusionnée ; image absente ; performance matérielle inconnue ; mutation absente des outils disponibles |

Les fixtures et leurs réponses attendues sont authorées et publiques ; elles
ne constituent pas un holdout indépendant. Aucun modèle réel n'a été évalué
pendant leur préparation.
Pour les outils, utiliser des fonctions de lecture simulées et des réponses
fixes ; ne pas brancher un shell ou un service réel au premier lot.
Évaluer les noms/champs nécessaires, sans imposer la même reformulation de
recherche caractère par caractère.

Comparer LFM3 aux Qwen déjà présents, s'ils sont confirmés dans l'inventaire,
avant d'ajouter de nouveaux candidats. Les étapes A et B ont des résultats
distincts. Avec trois modèles et les 24 cas, le premier passage représente
72 tentatives de modèle ; les échanges supplémentaires après résultat d'outil
sont comptés à part. Arrêter le lot sur incident de ressources ou transport
et conserver les cas non tentés au dénominateur.

Séparer échec transport, parseur, schéma, troncature, erreur factuelle et
abstention utile. Le raisonnement de LFM3 peut consommer le budget de sortie :
une réponse tronquée ne devient pas une abstention correcte. Conserver
exactitude et arguments des outils, citations, faits non soutenus, temps total,
tokens lorsqu'ils sont fournis, et maxima RAM/VRAM réellement mesurés. Distinguer
chargement à froid et état chaud observé ; les mesures absentes restent inconnues.

Avant toute promotion, comparer aussi la tâche terminée avec son vérificateur,
ses reprises et son coût total. Un bon score sur ces fixtures ne suffit pas à
autoriser les mutations, le routage automatique ou une économie annoncée.

### Pistes suivantes selon le résultat

- **Audio8-TTS** : comparer des répliques françaises pour PNJ et mascottes,
  séparément du texte et avec un délai de réponse mesuré.
- **LFM3 vision/omni** : étudier les variantes et leurs encodeurs propres après
  qualification du texte ; le modèle texte seul ne juge pas les rendus IDOL.
- **Spark-X2.6-1.7B** : challenger éventuel pour les budgets de raisonnement ;
  qualité française et compatibilité à établir avant ajout au lot.
- **SLEEP** : conserver une expérience distincte de mémoire ; la consolidation
  externe sourcée précède une mise à jour paramétrique des poids.

### Sources primaires consultées le 1 novembre 2026

- [Carte LFM3-1.7B](https://huggingface.co/LiquidAI/LFM3-1.7B)
  et [licence des poids](https://huggingface.co/LiquidAI/LFM3-1.7B/blob/main/LICENSE).
- [GGUF officiel](https://huggingface.co/LiquidAI/LFM3-1.7B-GGUF).
- [Ollama 0.40.13 : Linux et Windows](https://github.com/ollama/ollama/releases/tag/v0.40.13).
- [Tool use Liquid AI](https://docs.liquid.ai/lfm/key-concepts/tool-use).
- [Compatibilité API Ollama](https://docs.ollama.com/api/openai-compatibility).
