# Comparer les réponses texte locales : LFM3 et Qwen

Le pilote transforme le protocole LFM3 en un lot explicitement appelable,
avec réponses conservées et relecture hors ligne. Il réutilise
`local_chat.chat_completion` et ne change pas le contrat du worker.

Le corpus comprend **24 fixtures françaises originales** : huit propositions
d'outils, huit questions sur des documents fournis, quatre extractions JSON
et quatre cas de limites/abstention. Les données sont synthétiques et les
réponses attendues sont authorées. Ce lot public n'est pas un holdout indépendant
et ne mesure pas la qualité générale d'un modèle ou d'un agent autonome.

## Commandes

Depuis le dépôt, sans dépendance modèle à installer dans Parcimonia :

```sh
PYTHONPATH=src python3 examples/local_text_eval.py plan
```

`plan` lit seulement le corpus. Il n'interroge pas de serveur et ne soumet pas
les réponses attendues au modèle.

Après inventaire du serveur, vérification de sa mémoire et admission par
l'ordonnanceur existant, une capture est explicitement déclenchée ainsi :

```sh
PYTHONPATH=src python3 examples/local_text_eval.py capture \
  --model IDENTIFIANT_REEL_OBSERVE \
  --base-url http://127.0.0.1:11434 \
  --resources-checked --out runs/local-text-lfm3
```

Le dossier parent `runs` doit exister ; le dossier du run doit être nouveau.
Pour un autre corpus, fournir `--corpus CHEMIN` à la sous-commande. Les fixtures
fournies sont dans `examples/fixtures/local_text_cases_fr.json`.

`--resources-checked` est une déclaration de l'appelant, pas une mesure de la
RAM/VRAM et pas un verrou global. Le caller conserve la responsabilité de la
réservation GPU et d'une seule phase lourde à la fois. L'inventaire d'Odin ne
qualifie pas les ressources d'EurekAI lorsqu'un endpoint LAN est utilisé.
Une adresse LAN littérale exige `--allow-lan` et un trajet déjà qualifié.

Conserver le même runtime et les mêmes paramètres pour le run Qwen. Le modèle
doit être déjà disponible dans l'inventaire du serveur : le pilote n'installe,
ne télécharge et ne supprime aucun modèle. Un POST peut néanmoins déclencher
son chargement JIT ; un modèle listé n'est pas forcément chargé.

```sh
PYTHONPATH=src python3 examples/local_text_eval.py replay --run runs/local-text-lfm3
PYTHONPATH=src python3 examples/local_text_eval.py compare \
  --left runs/local-text-lfm3 --right runs/local-text-qwen
```

`replay` et `compare` ne contactent pas de modèle et ne réécrivent pas les runs.
Ils vérifient les empreintes puis recalculent les verdicts depuis les réponses.
Un `report.json` précalculé ne fait pas autorité. Les hashes détectent les
modifications accidentelles ; ils ne signent pas l'auteur ou la véracité d'un run.

## Ce que mesure la phase texte

Chaque prompt reçoit un petit contrat JSON commun : `status`, `value`,
`sources` et `calls`. Les champs des outils restent des **propositions textuelles**.
Il n'existe aucun répartiteur de commandes ou d'outils derrière ce lot.
Le client actuel refuse les appels natifs `tool_calls` ; leur qualification,
ainsi que les sorties contraintes par JSON Schema côté serveur, reste distincte.

La forme JSON et l'accord exact avec l'oracle sont évalués séparément.
Les citations et valeurs doivent correspondre aux pièces du cas. Les booléens
ne valent pas des entiers ; des clés dupliquées, NaN, du XML, des fences Markdown
ou du texte de raisonnement enveloppant un JSON ne sont pas nettoyés pour
fabriquer une réussite. Un échec de format reste un échec, même si un humain
pourrait deviner la réponse.

Les requêtes de recherche utilisent des termes imposés dans les fixtures pour
un contrôle déterministe des champs. Le score ne mesure donc pas la qualité
des reformulations libres de recherche. La mémoire est constituée de documents
fixes inclus dans le corpus ; aucun moteur RAG externe n'est exécuté.

## Arrêt, preuves et limites

- Le modèle demandé est obligatoire. Un GET `/v1/models` précède le premier
  POST. Un modèle absent ou un préflight en échec n'entraîne aucune inférence.
- Les appels sont séquentiels avec borne par appel et borne de lot. Un incident
  transport, une sortie native non supportée, une troncature ou une identité de
  réponse différente/inconnue arrête le lot. Aucun retry n'est effectué.
- Une réponse texte terminée mais incorrecte ou mal formée reste au score et
  permet de poursuivre le lot de qualité. Les cas non tentés restent dans le
  dénominateur de couverture et de réussite.
- Le manifeste est écrit avant les appels, puis mis à jour. Un run interrompu
  sans finalisation ne devient pas un run complet lors de sa relecture.
- Le nom retourné par le serveur et l'éventuelle révision/runtime déclarés
  sont conservés distinctement. `/v1/models` ne certifie pas le digest des poids,
  la version du runtime ni l'état chaud : `identity_certified=false`.
- Les temps du client et tokens fournis par le serveur sont descriptifs. Un
  compteur absent reste inconnu ; les cas non tentés n'inventent aucun token
  ou temps d'appel. Mémoire maximale, énergie et coût restent inconnus.
- La comparaison ne désigne aucun modèle à activer et ne certifie pas un gain
  de performance entre environnements non qualifiés. `selected_model=null`,
  `auto_act_allowed=false` et `saving_claim=false` restent explicites.

Un timeout du client ne prouve pas que le serveur a terminé son calcul. Après
un incident, contrôler le serveur avant de lancer un autre run.

La prochaine preuve utile est une capture LFM3/Qwen sur les machines réelles,
puis des tâches terminées avec leurs vérificateurs et leurs reprises.
Les tests hors ligne du harnais utilisent des réponses fabriquées et un serveur
HTTP simulé : ils ne constituent pas un résultat de LFM3 ou de Qwen.

Voir le [profil LFM3 et ses sources](LOCAL_LLM_EUREKAI.md), les
[limites du contexte mémoire](LOCAL_KNOWLEDGE.md) et le
[client texte existant](../src/tiberium_ai/local_chat.py).
