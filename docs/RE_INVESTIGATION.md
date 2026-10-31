# Préparer une investigation REA/LeanREA avec Parcimonia

Cette intégration propose les fichiers à lire, la prochaine investigation et
les preuves manquantes. Elle prépare un paquet local en mode `shadow` et
réutilise les profils, le suivi des fichiers et les décisions typées existants.
Elle ne lance aucun analyseur, aucune application cible et aucun appel réseau.

## Composants

- `re_investigation.prepare_investigation` appelle `build_index` puis
  `prepare_task`, ou `continue_task` avec une revue sauvegardée.
- `evidence_coverage` sépare `static`, `browser`, `export`, `runtime`, `visual`
  et `roundtrip`. Une preuve doit correspondre à l'empreinte et à la révision
  de la cible, à la propriété et au scénario déclarés.
- `advise_investigation` pose au plus trois questions fermées : premier fichier,
  prochaine analyse, preuve manquante. Les valeurs sont vérifiées par les
  contrats `DecisionRequest`/`capture_decision`/`replay_decision` existants.
- La CLI livre index, paquet, conseil, état, Markdown et manifeste SHA-256 dans
  un nouveau dossier sous `runs/`. Les sources sont lues comme données.
- Le comparateur mesure les propositions avec des labels externes au contexte
  du conseiller. Les bras Jev, modèle local et entraînement restent `not_run`
  tant qu'une expérience séparée n'est pas réalisée.

## Premier essai local

Depuis la racine du dépôt, après réservation des chemins avec le protocole Odin :

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
.venv/Scripts/python.exe -B examples/prepare_re_investigation.py `
  --state examples/fixtures/re_investigation_state.json `
  --inventory examples/fixtures/re_investigation_capabilities.json `
  --workspace-root . --output-dir runs/re-investigation/premier
```

Le catalogue livré est une curation des fonctions réelles de Parcimonia ; il
ne représente pas les capacités de l'installation REA de tous les postes.
Ses empreintes doivent être réactualisées après modification de ces fonctions.
Un profil périmé rejoint la revue plutôt que de rester éligible.

L'état JSON déclare l'objectif, la cible, sa révision, les exigences de preuve,
les observations et les routes candidates. Les champs supplémentaires, types
invalides, clés JSON dupliquées et nombres non finis sont refusés. Les routes
`unknown` ou `unavailable` restent visibles et ne deviennent pas candidates.
Les coûts inconnus restent `null`.

## Reprise à partir d'une revue

Les formats de feedback et de revue sont ceux de
[FILE_USEFULNESS_AND_FOLLOWUP.md](FILE_USEFULNESS_AND_FOLLOWUP.md).
La tâche garde son `investigation_id` et prend un nouveau `stage_id`.

```powershell
.venv/Scripts/python.exe -B examples/prepare_re_investigation.py `
  --state chemin/etat-etape-suivante.json `
  --inventory examples/fixtures/re_investigation_capabilities.json `
  --previous-run runs/re-investigation/premier `
  --feedback chemin/revue-hote.json `
  --output-dir runs/re-investigation/suite
```

`--review` permet de reprendre une revue déjà enregistrée à la place de
`--feedback`. Les fichiers modifiés sont signalés `changed_requires_reread` ;
leurs notes deviennent `stale_requires_review`. Les anciennes livraisons ne
sont pas écrasées. Une source inchangée ne prouve pas qu'une lecture a été évitée.

## Jugement Jev ou modèle local

L'API Python accepte un transport explicitement injecté, identifié et versionné :

```python
result = prepare_investigation(
    state, inventory, roots,
    transport=transport_autorise,
    backend_id="identite-reelle-du-fournisseur",
    backend_version="version-epinglee",
)
```

Le transport reçoit l'état compact et les trois questions typées et retourne
`{"answers": {...}}` au format du contrat existant. Aucun transport ou secret
n'est installé par ce pilote. Les tests utilisent des réponses injectées
artificielles, pas Jev. Le budget nul, l'âge inconnu quand une borne est exigée
et l'état périmé refusent l'appel avant son départ. Une réponse tardive reste
enregistrée mais n'est pas utilisée. Les erreurs conservent les conseils locaux.

`--decision-record` permet uniquement un rejeu hors réseau d'un enregistrement
compatible. La version du fournisseur, le contexte et le budget font partie de
l'identité du rejeu. Les jugements sémantiques restent des avis : le schéma valide
la forme de la réponse, pas sa justesse. `auto_act_allowed` demeure faux.

## Comparaison et limites de preuve

```powershell
.venv/Scripts/python.exe -B examples/compare_re_investigations.py `
  --cases examples/fixtures/re_investigation_cases.json `
  --output-dir runs/re-investigation/comparaison
```

Chaque cas fournit une origine (`authored_fixture` ou `independent_task`), des
chemins d'état et de catalogue, une racine explicite et des labels de fichiers
utiles et de prochaine route. Les labels ne sont pas envoyés au conseiller.
Le corpus livré est un exemple d'intégration écrit à la main, sans preuve de
généralisation à BD Composer, Aion ou Spore. Le bras avec réutilisation d'index
relit les octets pour vérifier leurs empreintes : ce n'est pas une suppression
de lectures. Les durées couvrent la préparation, hors démarrage et sérialisation.
Les gains sur une tâche, les économies et les performances Jev restent inconnus.

Les preuves fournies par l'hôte sont conservées comme
`reported_not_independently_verified`. Leur référence et leur empreinte sont
déclarées ; le conseiller ne rouvre pas les artefacts pour les certifier.
Des valeurs contradictoires pour une même propriété/scénario demandent un
test discriminant. Même si tous les niveaux sont rapportés, la proposition est
une revue de portée, jamais une validation automatique de la reconstruction.

L'autorité, les contrôles de formats binaires, les codes de retour, les
permissions, les ressources et les vérificateurs finaux restent dans l'hôte.
Les binaires, décompilations et données de `runs/` restent privés.
