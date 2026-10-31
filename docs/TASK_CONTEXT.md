# Champs fournis, contexte requis et informations manquantes

Incrément du 7 octobre 2026. `task_context.py` ajoute un compagnon version 2 à une
signature historique version 1. Les anciens champs, questions, labels et captures
restent dans leur format d’origine ; ils ne deviennent pas automatiquement des
champs fournis ou des exigences du nouveau contrat.

## Sens des champs

| Champ | Sens | Exemple |
|---|---|---|
| `provided_fields` | Valeurs explicitement présentes dans l’entrée structurée fournie par l’hôte | Le contenu CSV figure dans `values.document` |
| `referenced_fields` | Références déclarées séparément, dont la disponibilité peut être vérifiée | Une pièce jointe identifiée par l’hôte |
| `available_context` | Valeurs de forme utilisable ou références accompagnées d’une preuve compatible | Document inline non vide ou pièce jointe disponible |
| `required_context` | Exigences déclarées par le contrat d’une opération précise | Le contenu du document pour extraire ses colonnes |
| `missing_context` | Exigences connues absentes, invalides ou indisponibles | L’hôte confirme qu’aucun document n’est fourni |
| `unknown_context` | Exigences dont la disponibilité n’est pas établie | La capture ne conserve pas les pièces jointes |

« Récupère les champs de ce fichier » mentionne un document. Cette phrase ne
contient pas ses données et ne prouve pas qu’une pièce jointe est accessible.
Le contrat n’effectue aucune extraction lexicale de valeurs à partir du prompt.
L’hôte fournit les valeurs déjà structurées et les références qu’il connaît.
Une future extraction sémantique devra produire des candidats avec une provenance
et une vérification propres.

Un champ présent peut être invalide. `None` ou une chaîne vide reste dans
`provided_fields`, mais est marqué dans `invalid_fields` et ne devient pas un
contexte disponible. Les valeurs numériques zéro et booléennes `False` sont
acceptées si le type déclaré leur correspond. La validation de forme ne garantit
pas les contraintes métier : les budgets, la validité du CSV et le résultat de
l’opération conservent leurs vérificateurs.

## Exigences déclarées par opération

`ContextContract` contient identité, version, type de tâche, déclarations des
champs et liste du contexte requis. L’hôte déclare ces exigences pour l’opération
choisie ; elles ne sont pas apprises à partir de quelques mots. Deux opérations
de type `extract` peuvent demander des contextes différents.

```python
from tiberium_ai import ContextContract, ContextField, assess_context

contract = ContextContract(
    "extract.csv-columns", "1", "extract",
    (ContextField("document", "Contenu CSV concret"),),
    ("document",),
)
result = assess_context(
    contract,
    context_revision="snapshot-1",
    values={"document": "nom,age\nAda,36"},
)
assert result.ready
assert result.to_record()["auto_act_allowed"] is False
```

`enrich_signature_context(signature, prompt, contract, ...)` ajoute ce relevé à
une signature existante. Il refuse un autre hash de prompt et conserve une
abstention si la signature est indéterminée ou si son type ne correspond pas au
contrat. Le compagnon enregistre séparément la signature v1 et le contexte v2.

`ready` signifie que les exigences de contexte sont satisfaites dans les
déclarations et preuves transmises. Il n’autorise aucune exécution et ne certifie
ni le résultat futur ni la calibration du classifieur.

## Inconnu et absence confirmée

Par défaut, `context_complete=false`. Une information non observée reste
inconnue, même si le dictionnaire des valeurs connues est vide. Cela protège les
captures historiques où le prompt est enregistré sans contexte de l’éditeur,
du navigateur ou des pièces jointes.

L’hôte peut déclarer `context_complete=true` lorsqu’il a observé l’ensemble du
contexte pertinent. Alors seulement, un champ non fourni et non référencé est
considéré absent. Les deux verdicts restent distincts : `context_unknown` et
`missing_context`.

## Preuves de disponibilité des références

L’hôte produit une `Verification` avec le registre existant. Le descripteur
`reference_payload` contient hash du contrat, champ, référence et révision du
contexte. Le relevé de disponibilité n’est réutilisable qu’avec le même descripteur
et une identité de vérificateur enregistrée. Une preuve ancienne ou étrangère
reste inconnue. Un verdict faux exprime l’indisponibilité ; un verdict nul exprime
l’absence de conclusion.

L’évaluation du contexte ne lance pas ce vérificateur et ne lit aucun fichier.
Elle contrôle la preuve produite et transmise par l’hôte, dont la sincérité et
la fraîcheur doivent être assurées par la collecte. Une simple métadonnée de
modèle n’est pas une preuve de disponibilité. L’attribution du vérificateur et
son hash sont conservés dans `reference_verification`.

Le relevé contient des hashes et des statuts, sans recopier valeurs ou identifiants
des références. Les données source restent chez l’hôte. La révision du contexte
fait partie de l’identité et doit changer lorsque le contexte change.

## Pilote de contrat

```powershell
rtk proxy .venv/Scripts/python.exe examples/context_review_pilot.py --output runs/context-pilot/fixture-report.json
```

Sept scénarios authored couvrent mention seule, CSV inline, contexte non capturé,
référence sans preuve, disponible, indisponible et preuve périmée. Ils démontrent
le contrat et ses refus ; ils ne mesurent pas la qualité d’un modèle ni une
économie d’inférence.

## Préparation d’un lot indépendant

`context_review.py` prépare des dossiers d’annotation, avec labels, contrat,
contexte source et identité de l’annotateur à compléter. Une valeur nulle signifie
« pas encore établi » ; elle ne signifie jamais « ensemble vide ». Le modèle
évalué ne fournit pas ses propres labels de vérité.

```powershell
rtk proxy .venv/Scripts/python.exe examples/context_review_pilot.py --corpus runs/signature-corpus/latest.json --output runs/signature-corpus/context-review-new.json --limit 120 --seed 20261007
```

Le pilote vérifie la révision de corpus par contenu. Il sélectionne des demandes
de 40–2000 caractères, non tronquées, avec un signal lexical français. La langue
reste à confirmer par revue. Le tri de sélection est déterministe et les
demandes privées restent dans `runs/`, ignoré par Git. Les fichiers ne sont
jamais écrasés. Aucun prompt privé n’est imprimé dans le résumé console.

Avant de figer le split : récupérer/revoir les groupes de conversations d’origine,
regrouper les paraphrases apparentées et contrôler les doublons. Le regroupement
des doublons normalisés est conservateur et ne remplace pas cette revue sémantique.
`freeze_context_review_split` garde ensemble conversations, paraphrases revues
et doublons normalisés, même lorsque ces liens sont transitifs. Il refuse un lot
sans groupes revus ou sans possibilité de séparation par source.

Un split figé contient les identifiants et hashes des cas ; les réglages et seuils
doivent ensuite être choisis sur développement. Les références de test doivent
venir d’annotations indépendantes ou d’issues vérifiées. Une séparation de
groupes n’établit pas à elle seule l’indépendance des labels ou du préentraînement.

## État local du 7 octobre 2026

La provenance des 120 cas a depuis été retrouvée et le formulaire est préparé :
voir [la revue indépendante](CONTEXT_INDEPENDENT_REVIEW.md). L’état initial décrit
ci-dessous reste celui du dossier avant récupération ; les labels demeurent vides.

Un dossier de **120 demandes candidates**, avec **zéro label**, a été préparé
dans `runs/signature-corpus/context-review-20261007.json`, à partir de la révision
`22de4af5f3175be494ca84b33d456abd9f86a636bb4bcedfc822ed5f46e23b40`.
Cette révision est celle déjà présente sur disque ; aucune nouvelle collecte
de conversations n’a été effectuée.

Ses métadonnées distinguent seulement `sessions` et `archived_sessions`, sans
identifiants de conversation. Le split reste donc
`awaiting_source_and_paraphrase_group_review`. Contexte des cas, contrats,
langue, groupes et labels restent à examiner. Aucun taux d’exactitude,
calibration ou gain de coût n’est mesuré sur ce dossier.

Les signatures et métriques historiques ne sont pas réétiquetées par cet
incrément. La cascade actuelle reste celle de son pilote v1 ; le compagnon
de contexte est une entrée supplémentaire pour une future politique de
préparation, qui doit conserver budgets et vérificateurs existants.

Un mode explicite a depuis été ajouté à cette cascade :
[`propose_signature` et son contrôle préalable du contexte](CONTEXT_SIGNATURE_CASCADE.md).
La méthode historique `evaluate` et ses captures restent utilisables.
