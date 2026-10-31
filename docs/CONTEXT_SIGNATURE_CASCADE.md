# Cascade de signature avec contrôle du contexte

Incrément du 7 octobre 2026. `SignatureCascadeBackend.propose_signature` relie le
contrat de contexte à la sélection de prédicteur. La méthode historique `evaluate`
conserve son comportement et le format de ses traces ; le mode contexte est une
entrée explicite distincte.

## Ordre des contrôles

1. Contrôler schéma, contrat, identités déclarées des backends et entrée structurée.
2. Évaluer le contexte déclaré par l’hôte, avec les preuves de disponibilité des
   références selon le contrat existant.
3. Si une information requise manque ou reste inconnue, retourner `collect_context`.
   Une valeur invalide retourne `repair_context`. Aucun prédicteur n’est appelé.
4. Si le contexte est prêt et le nombre d’appels autorisé n’est pas épuisé,
   appeler la baseline sur le prompt original, puis valider son lot complet.
5. Sélectionner sa signature seulement si son type correspond au contrat et si
   sa probabilité atteint le seuil effectif. Celui-ci est le maximum du seuil
   de la cascade et de celui du schéma de signature.
6. Sinon, consulter une fois le secours déclaré, dans le plafond d’appels. Son
   résultat doit satisfaire les mêmes contrôles. Une réponse incertaine ou d’un
   autre type reste une abstention explicite.

Une erreur de protocole dans la baseline n’est pas masquée par un secours.
Les tentatives qui échouent consomment leurs plafonds ; aucun retry n’est ajouté.
Un backend déclaré limité au latin est sauté pour un prompt non latin. Un secours
compatible peut être consulté ; si aucun ne convient, aucun backend n’est appelé.
La compatibilité de script ne prouve pas la compétence dans une langue.

## Contrat fourni par l’hôte

```python
from tiberium_ai.signature_cascade import SignatureCascadeBackend

cascade = SignatureCascadeBackend(
    baseline, fallback, threshold=0.9,
    max_calls=20, max_fallback_calls=5,
)
proposal = cascade.propose_signature(
    prompt,
    schema=signature_schema,
    contract=context_contract,
    baseline_identity=("frame.verb-object", "1"),
    fallback_identity=(fallback.backend_id, fallback.backend_version),
    context_revision="snapshot-1",
    values={"document": csv_text},
)
```

Les identités sont des tuples `(id, version)`, jamais des noms de modèles déduits
du texte. Si le backend expose sa propre identité, une déclaration différente est
refusée avant tout appel. L’identité déclarée reste une provenance ; elle ne
certifie pas les poids ou la qualité à elle seule.

Le contexte sert à vérifier la préparation. Le prompt transmis aux prédicteurs
reste le texte historique : les valeurs du contexte ne sont pas ajoutées
implicitement à leur entrée. Un futur protocole de modèle utilisant aussi ces
valeurs devra avoir sa propre version et être comparé séparément.

Les champs prédits v1 restent des champs prédits v1. Le contexte disponible,
fourni ou manquant v2 provient du contrat et des données de l’hôte. Une prédiction
`field.path` ne prouve pas qu’un document existe, et une référence vérifiée n’est
pas requalifiée en valeur inline.

## Résultat et autorité

`ContextCascadeProposal` retourne un état, une raison stable, le contexte,
la signature retenue ou `None`, le nom de l’étape et une copie de ses traces.
Les statuts sont `selected`, `collect_context`, `repair_context`,
`budget_exhausted`, `backend_error` et `abstained`.

`selected` décrit un prédicteur dont la réponse satisfait ces contrôles. Il ne
certifie pas un résultat de tâche ni la calibration de ses probabilités.
`auto_act_allowed` reste faux. Le directeur/hôte conserve l’intention et
l’autorisation ; le vérificateur conserve la responsabilité du résultat.

Le hash de demande lie prompt, questions complètes, schéma, contrat, hash du
contexte, identités, politique et compteurs de budget avant l’appel. Une réponse
obtenue avant épuisement ne représente pas une nouvelle demande après épuisement.
Modifier le contenu ou la révision du contexte
change cette identité. L’hôte doit reconfirmer sa fraîcheur avant une action :
la cascade ne réobserve pas les fichiers ou l’interface après une inférence.

Les traces ne recopient pas les valeurs de contexte ni le texte des exceptions
du fournisseur. Elles conservent le type d’erreur et les identités des étapes.

## Portée des compteurs et des budgets

- `context_checks` compte les évaluations de contexte du nouveau mode.
- `calls` est le compteur partagé des requêtes entrées en prédiction, en mode
  historique comme en mode contexte. Un contexte à recueillir ne le consomme pas.
- `fallback_calls` est le plafond partagé des tentatives effectives du secours.
- `proposal.backend_calls` compte les appels à `backend.evaluate` pour cette
  proposition, de zéro à deux. Il ne compte pas les passes internes d’un modèle.

Les plafonds sont des limites de nombre d’appels. Cette méthode n’installe pas
de runtime, ne télécharge pas de poids, ne fournit pas de transport et ne lance
pas d’effector. Un backend fourni par l’hôte peut être coûteux : ses autorisations,
deadlines, coûts cumulés et contraintes de ressources conservent leurs portes
existantes. Les coûts et latences du résultat restent `None`, faute de mesure.
Une économie de coût ou de tokens ne découle donc pas des seuls compteurs.

Un contrôle optionnel des ressources a depuis été raccordé :
voir [mesures, coûts connus et deadlines](CASCADE_RESOURCES.md). Il ne change
pas le mode sans contrôle, dont les champs mesurés restent non renseignés.

## Pilote reproductible

```powershell
rtk proxy .venv/Scripts/python.exe examples/context_signature_cascade_pilot.py --output runs/context-cascade-pilot/fixture-report.json
```

Huit scénarios authored couvrent document absent, non observé, invalide, baseline
suffisante, baseline incertaine, désaccord avec le contrat, secours incertain
et secours interdit par son plafond. Trois scénarios ne font aucun appel à un
prédicteur ; les autres comptent exactement leurs callbacks injectés.

Ces callbacks ne sont pas des modèles neuronaux. Le pilote vérifie la mécanique
de collecte/sélection/refus et ne mesure ni qualité générale, calibration,
latence d’inférence, VRAM ou économie en production. Les labels humains du
lot de 114 demandes restent à établir pour la comparaison réelle.
