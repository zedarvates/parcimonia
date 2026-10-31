# Domaines et profils d'exécution versionnés

Application locale utilisable : [préparation des tâches de développement](TASK_PREPARATION_PILOT.md).

Incrément du 20 octobre 2026. `execution_profiles.py` fournit un catalogue
indépendant et versionné pour les outils, skills et mécanismes. Les adaptateurs
de `profiled_selection.py` le raccordent au registre de routes et à la sélection
de skills. Les anciennes API restent compatibles ; le filtrage enrichi est
explicite et ne s'active pas globalement dans les sessions Codex ou les MCP.

## Identités et versions

Une fiche contient exactement `schema_version`, `taxonomy_version`, `id`, `kind`,
`revision`, `content_sha256`, `facets` et `dependencies`. Les types possibles
sont `tool`, `skill` et `mechanism`. Le schéma courant est 1 et le vocabulaire
`execution-tags/1`.

- `revision` : révision de la fiche, à changer lors d'une modification éditoriale.
- `content_sha256` : SHA-256 des **octets exacts** de la source observée. Pour un
  skill, utiliser son fichier ; pour un outil, un descripteur complet/versionné
  ou son implémentation, selon le contrat de l'hôte. Ce choix doit inclure les
  fichiers de support pertinents via un manifeste ou des dépendances épinglées.
- `profile_sha256` : empreinte JSON canonique de toute la fiche, provenance et
  dépendances incluses. Un changement sans incrément de révision reste détecté.
- `catalog_sha256` : empreinte de l'instantané entier, y compris sa version.

Le hash de SkillCatalog existant est celui d'un texte encodé en JSON ; il n'est
pas interchangeable avec ce hash d'octets. L'adaptateur exige une observation
séparée des sources par l'hôte. Il ne relit pas arbitrairement des fichiers.
Les dépendances portent `id`, `revision` et `profile_sha256` ; une dépendance
absente ou modifiée rend la sélection incompatible. Le parcours est borné à
16 niveaux, 32 dépendances directes par fiche et 4096 visites par évaluation ;
un instantané contient au plus 512 fiches. Partitionner un grand inventaire en
catalogues bornés, avec une fermeture de dépendances complète par catalogue.

## Propriétés disponibles

| Propriété | Exemples |
| --- | --- |
| `domains` | code, research, image, 3d, documents, data, administration |
| `operations` | read, analyze, generate, modify, send, publish, verify |
| `environments` | windows, linux, browser, git, native-app, python |
| `locations` | local, lan, cloud |
| `effects` | read, write, delete, external-send, process-start, service-change |
| `scopes` | workspace, directory, account, system, recipient |
| `data_classes` | public, private, secret |
| `network` | offline, lan, internet |
| `resources` | cpu, gpu, ram-heavy, vram-heavy, paid |
| `availability` | available, unavailable |
| `input_formats`, `output_formats` | json, csv, png, glb, etc. |

Le vocabulaire fermé de chaque propriété est dans `TAXONOMY`. Les formats sont
des identifiants normalisés libres. Étendre les vocabulaires impose une nouvelle
version. Les tags de ressources sont des classes qualitatives : les plafonds
numériques de RAM, coût ou durée restent des contrôles distincts du routeur/hôte.

Chaque propriété porte `status`, `tags`, `source`, `observed_at` et `evidence`.
`observed_at` est horodaté avec fuseau. Les états sont :

- `unknown` : `tags=null`, `evidence=null` ; une absence n'est pas une liste vide.
- `declared` : tags déclarés, sans attestation de leur vérité.
- `verified` : tags accompagnés d'une référence de preuve ; l'hôte doit encore
  confirmer cette preuve séparément pour que le filtre strict l'accepte.

Une déclaration explicite `tags=[]` signifie aucun effet/ressource/etc. déclaré,
et demande la même vérification qu'une liste non vide en mode strict.
Une source ou une description externe reste une donnée, jamais une instruction.

## Filtrage et preuve de l'hôte

`ExecutionCatalog.assess(ids, policy, observed_content=..., trusted_claims=...)`
renvoie les identifiants compatibles et toutes les raisons d'exclusion.
La politique contient une version, `required`, `allowed` et `require_verified` :

- `required` exige tous les tags demandés sur la fiche racine.
- `allowed` exige que **toutes** les expositions possibles soient autorisées
  par ce filtre : `effects=[read,write]` ne convient pas à `allowed=[read]`.
- Une propriété demandée inconnue/manquante exclut le candidat.
- En mode strict, `verified` seul ne suffit pas. Le jeton calculé par
  `claim_attestation(profile, facet)` doit appartenir à l'ensemble **fourni par
  l'hôte après sa propre revue**, jamais lu depuis la fiche ou un fournisseur.
- Les contraintes `allowed` s'appliquent aussi aux dépendances transitives.
  `required` porte sur la racine, sauf la disponibilité exigée aussi sur les
  dépendances. Un outil généraliste peut servir un skill spécialisé.

Ces jetons sont des empreintes, pas des signatures ni des permissions. L'hôte
doit garder le contrôle de leur émission et de leur fourniture à l'API. La
présence d'une chaîne ressemblant à une preuve ne prouve pas sa validité.
La fraîcheur temporelle de disponibilité et des preuves relève de l'hôte : le
module compare les hashes observés mais n'impose pas de durée de validité.

Seules les propriétés demandées par la politique sont contrôlées ; une politique
vide n'est pas une politique de sûreté universelle. Le mode `require_verified=false`
est destiné aux essais déclaratifs, avec `auto_act_allowed=false` dans tous les cas.

## Intégrations utilisables

```python
from tiberium_ai.profiled_selection import filter_profiled_routes, select_profiled_skill

# bindings et observed_content viennent de l'hôte, pas du modèle.
candidates, trace = filter_profiled_routes(
    registry, task, catalog=catalog, bindings=route_to_profile,
    policy=policy, observed_content=current_source_hashes,
    trusted_claims=host_reviewed_claims,
)

proposal, trace = select_profiled_skill(
    query, skill_shortlist, session, catalog=catalog, bindings=skill_to_profile,
    policy=policy, observed_content=current_source_hashes,
    trusted_claims=host_reviewed_claims,
)
```

L'adaptateur de routes conserve les contraintes et capacités du registre v1,
puis applique les profils. Il conserve l'instantané des candidats et leurs
estimations dans la trace. Une route sans liaison est exclue.
L'adaptateur de skills filtre avant la sélection, conserve les références et
facettes dans l'état soumis au modèle et applique la limite existante de 19
candidats. Même un choix explicite ne contourne pas ce filtre ; il produit une
abstention s'il est incompatible. Le skill choisi doit toujours être lu selon
les instructions de l'hôte. Les tags ne remplacent pas son contenu.

## Appel concret et rejeu

`catalog.bind_invocation(...)` lie une proposition à ses arguments canoniques,
à la politique, à l'évaluation et à la référence de fiche. L'hôte fournit à
nouveau politique, hashes observés et attestations ; les listes présentes dans
l'ancienne trace ne sont pas utilisées comme nouvelles permissions.

Les arguments bruts ne sont pas enregistrés, seulement leur empreinte. Une
empreinte n'anonymise pas nécessairement une donnée devinable ; le stockage du
rapport doit respecter les règles de confidentialité du projet.

Les propriétés d'appel `effects`, `scopes`, `data_classes` et `network` peuvent
être précisées par l'hôte avec une attestation `call_attestation` liée à la
référence complète, à la propriété et aux arguments exacts. Les contraintes sont
revérifiées. Une fiche générale rejetée ne peut pas être rendue admissible par
une précision tardive ; créer une variante explicitement restreinte et revue.
Ce choix conservateur évite d'assimiler un shell généraliste à une lecture sûre.

`catalog.replay_invocation(...)` vérifie la même proposition avec l'instantané
et les faits de l'hôte. Changer contenu, catalogue, fiche, arguments, politique
ou preuve produit un écart ou un refus. Le rejeu ne réexécute rien.
Conserver `catalog.to_record()`, l'évaluation et la référence d'appel ensemble.
`load_execution_catalog` refuse versions inconnues, clés ambiguës et nombres
non finis. Toutes les propositions gardent `auto_act_allowed=false`.

## Démonstration exécutée

```powershell
$env:PYTHONPATH = 'C:\TiberiumAI\src'
rtk python examples/execution_profiles_pilot.py --output-dir runs/execution-profiles-20261020-v1
```

Le dossier doit être nouveau et sous `runs/`. Le pilote lit uniquement deux
sources de fixture du dépôt, écrit `catalog.json` et `report.json`, puis recharge
le catalogue et contrôle le rejeu. Résultat observé : `declared=1 strict=0 replay=True`.
La sélection explicite de fixture est effectuée sans appel de modèle ; aucun
skill ou outil sélectionné n'est exécuté. Les tags restent déclarés : le pilote
ne fabrique pas de vérification indépendante.

Aucun inventaire global de skills installés ou d'outils MCP n'a été migré.
Prochaine étape : établir les fiches revues des capacités réellement utilisées,
avec leurs sources et périmètres, puis exploiter ces facettes dans le banc de
décision avant toute étude SFT. La permission, les chemins réels, destinataires,
identifiants de compte et plafonds matériels restent contrôlés par l'hôte.

## Validation ciblée

Le plan de tests couvre : stabilité des hashes et mutations, JSON strict,
inconnus, déclarations auto-certifiées, expositions multiples, sources changées,
dépendances modifiées, liaison et rejeu d'appel, compatibilité des routes et
sélection de skills avec/sans modèle injecté. Les tests d'intégration utilisent
des fixtures et aucune preuve ne constitue une inférence réelle de modèle.

Résultat du 20 octobre : **141 tests ciblés passent**, couvrant les nouveaux
profils/adaptateurs/pilote, le registre, les recettes, le banc et les contrats de
décision. `git diff --check` ne signale pas d'erreur.
