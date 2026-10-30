# Agent local : diagnostic LM Studio et itérations bornées

Incrément préparé le 30 octobre 2026, rattaché à TASK-074. Il ne clôture pas
cette tâche et ne dépend pas de la fusion des PR mémoire #12 ou Tev1 #13.

## Ce qui fonctionne dans ce code

- Un diagnostic explicite sans inférence : un GET `/v1/models`, suivi d'un
  inventaire de la machine appelante. Pas de service créé ou redémarré, de
  modèle chargé/téléchargé, de scan réseau ou de commande issue d'un modèle.
- Un helper d'amélioration d'un seul candidat JSON, à appeler à l'intérieur
  d'une mission déjà admise par le caller existant. Il réutilise `capture_run`,
  `VerifierRegistry`, `Environment` et les mesures `measurement/2`.
- Un client texte explicite `local_chat.chat_completion` et un worker stdin/stdout
  JSON qui effectuent au plus un POST local, sans retry ni exécution d'outil.
- Un exemple hors ligne qui démontre le rejet d'un export invalide, la
  conservation du meilleur candidat et l'arrêt après stagnation. Les exports
  et scores de cet exemple sont des fixtures écrites pour le test.

Ce n'est pas un nouvel orchestrateur : aucun changement d'ActiveRouter,
ContinuationArbiter, permissions, seuil Needle, scheduler ou route de secours.
Il n'y a pas encore d'adaptateur aux éditeurs d'avatars ou de monstres, ni de
connexion automatique du helper au serveur LM Studio ou au pont cloud. Le worker
`examples/local_chat_worker.py` fournit maintenant le raccord d'inférence texte
appelable par le caller ; voir le [plan local concret](LOCAL_LLM_EUREKAI.md).
`examples/lmstudio_ab.py` reste un ancien chemin distinct de comparaison A/B.

## 1. Premier diagnostic sur la machine voulue

Depuis la racine de ce dépôt, sur le serveur qui héberge LM Studio :

```sh
PYTHONPATH=src python3 examples/eurekai_diagnostic.py --out diagnostic-local.json
```

La commande n'utilise que Python 3.10+ et sa bibliothèque standard. Elle ne
requiert ni connexion Work/Codex, ni clé OpenAI, ni pytest. Le fichier de sortie
doit être nouveau et son dossier exister. Il est créé exclusivement, avec
permissions 0600 lorsque prises en charge. Le dossier parent doit être privé.
Ne pas committer l'inventaire ou les identifiants de modèles personnels.

Pour un test depuis un autre poste du LAN, fournir explicitement l'IP privée
du serveur ; remplacer la valeur d'exemple avant l'appel :

```sh
PYTHONPATH=src python3 examples/eurekai_diagnostic.py \
  --base-url http://192.168.1.100:1234 --allow-lan --out diagnostic-lan.json
```

**L'inventaire restera celui du poste qui lance la commande**, pas celui de
l'hôte distant. Un diagnostic effectué dans le cloud ne devient pas un
inventaire du serveur local. `--disk-path` permet de choisir le volume local
à observer, `--timeout` borne le GET (3 secondes par défaut).

Les commandes locales sont fixes : `nvidia-smi` (nom, mémoire et pilote) et
`lms --version`. Elles ont un timeout propre ; une limite de taille est vérifiée
après capture de leur sortie. Les processus présents dans le PATH sont donc
une dépendance de confiance. Le Hailo, la topologie PCIe et les cœurs physiques
restent non inspectés. Sur un OS sans `/proc/meminfo`, la RAM peut rester inconnue.

### Interprétation

| Résultat | Ce qu'il établit | Ce qu'il n'établit pas |
| --- | --- | --- |
| `reachable` | Réponse JSON valide à `/v1/models` | Modèle chargé, inférence ou outils opérationnels |
| `http_error` avec 401/403 | Réponse du service avec refus d'accès | Service en panne ; les credentials ne sont pas gérés par cette sonde |
| `unreachable` | Connexion impossible depuis cet appelant | Cause précise : port, service, réseau ou pare-feu |
| `timeout` | Échéance de la sonde atteinte | Arrêt d'un travail sur le serveur |
| `invalid_response` | Réponse non conforme ou incomplète | État des autres endpoints |
| `redirect_refused` | Redirection reçue et non suivie | Accessibilité de la destination de redirection |

LM Studio peut lister tous les modèles téléchargés lorsque le chargement JIT
est actif. `loaded_state="not_observed"` et `inference_ready=null` sont donc
conservés, même si la liste n'est pas vide. Le probe n'appelle jamais POST.

Seuls localhost et des IP loopback littérales sont acceptés par défaut.
`--allow-lan` autorise une IP RFC1918 ou ULA IPv6 explicite. Pas de noms DNS
externes, de proxy, de credentials dans l'URL ou de redirection. Cette sonde
est destinée au réseau local, pas aux passerelles de fournisseurs cloud.

## 2. Vérifier le mécanisme de boucle sans modèle

```sh
PYTHONPATH=src python3 examples/local_iteration_demo.py
```

Le rapport doit annoncer `data_origin="authored_fixture"`, zéro appel modèle,
zéro rendu, `best_iteration=2` et `stop_reason="patience"`. La proposition au
score visuel 0.99 est rejetée car son export déclaré est invalide. Ce contrôle
est un témoin de contrat ; il ne valide pas un vrai fichier GLB ni un VLM.

## 3. Raccorder une vraie boucle à l'appelant existant

`improve_candidate(...)` reçoit trois responsabilités séparées :

1. `produce(index, best_descriptor)` : une action déjà autorisée dans une copie
   de travail isolée ; créer un snapshot immuable des fichiers et rendre un
   descripteur JSON borné. Les appels éventuels à LM Studio et aux outils de
   l'éditeur appartiennent à cet appelant, pas au helper.
2. `VerifierRegistry` : contrôles techniques nommés et versionnés sur les
   entrées exactes. Pour un asset : relire les empreintes, valider géométrie,
   rig/export et tests physiques applicables. Un vérificateur de forme JSON
   seul n'établit jamais la qualité ou la conformité d'un asset.
3. `evaluate(descriptor)` : score fini entre 0 et 1, ou `None` pour abstention,
   attribué à un évaluateur/version fixes. Pour la vision : captures comparables,
   caméra/lumière fixes, critères explicites, justification et incertitude.

Un candidat rejeté ou non vérifié n'est pas évalué et ne peut devenir meilleur.
Un score égal conserve le meilleur antérieur. La baseline est soumise aux mêmes
contrôles. Un vérificateur non enregistré empêche tout appel du producteur.
Une mutation par le vérificateur est refusée ; les producteurs, évaluateurs et
consommateurs des résultats ne reçoivent que des copies de descripteurs.

Budgets initiaux : 6 propositions, patience de 2 sans progrès, 30 minutes,
256 Kio par descripteur. **Le timeout est coopératif entre callbacks** : il
n'interrompt pas un modèle ou moteur qui bloque. L'appelant doit borner chaque
outil/processus et réserver les ressources via le mécanisme existant.

Le résultat conserve le meilleur **descripteur en mémoire**, pas une sauvegarde
des fichiers 3D. L'appelant conserve les vrais artefacts versionnés, leurs hashes
et les captures ; il doit vérifier à nouveau leurs hashes avant emploi. Aucun
rollback du filesystem n'est effectué automatiquement par ce helper.

Un callback `checkpoint(result)` peut persister la progression dans le journal
existant. Le record compact ne contient pas les payloads ; l'appelant peut
accéder au meilleur descripteur via `best_output`. Après une erreur de
checkpoint, conserver le résultat et réconcilier le journal : **ne jamais
relancer la production seulement pour réparer une preuve**. Une erreur de
vérification conserve un état partiel et une mesure inconnue lorsqu'elle n'a
pas pu être récupérée. `KeyboardInterrupt` est transmis à l'appelant.

## 4. Ce qui doit encore être validé sur le serveur

- Cause réelle de la panne de LM Studio ; versions, modèles et ressources libres.
- API texte, outils, puis images sur un modèle explicitement sélectionné.
- Commandes réelles des éditeurs : produire, exporter, tester et capturer.
- Alternance entre génération/rendu et VLM si les GPU ne peuvent les héberger
  simultanément ; accès depuis un autre poste ; checkpoint et reprise.
- Retour compact via le pont existant, sans relance automatique d'un job Work
  lorsque son quota est épuisé.

Pas de modèle futur présumé, de gain de tokens mesuré, d'activation automatique
ou de correctif annoncé à la panne. Les coûts, tokens et VRAM non mesurés restent
`null`. Les résultats de test sont distincts d'un essai matériel ou de production.

## Sources primaires du protocole

- [LM Studio : serveur API](https://lmstudio.ai/docs/developer/core/server)
- [Mode service et chargement JIT](https://lmstudio.ai/docs/developer/core/headless)
- [Responses](https://lmstudio.ai/docs/developer/openai-compat/responses)
- [Outils](https://lmstudio.ai/docs/developer/openai-compat/tools)

La sonde utilise uniquement le listing standard `/v1/models` ; les capacités
Responses, vision et outils citées ne sont pas testées par cette sonde.
