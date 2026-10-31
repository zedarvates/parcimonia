# Contrats de décision : état, calibration et réponses fournisseur

Incrément du 7 octobre 2026, issu de l’analyse CLEF/GEV. Il corrige les trois
défauts reproduits dans les sondes locales et conserve l’autorité d’exécution
à l’hôte. Les fixtures, les probabilités et les rapports ne donnent aucune
autorisation d’agir.

## État structuré et compatibilité

`decision_json.canonical_json` conserve les clés, l’imbrication, les listes,
les types JSON et Unicode. Il trie les clés et refuse les valeurs non finies
et les clés non textuelles qui seraient converties implicitement par JSON.
Reflex utilise ce format lorsqu’on lui transmet un mapping. Une entrée texte
reste inchangée, y compris ses espaces et sa ponctuation.

La version est `reflex-state/2`. La concaténation des seules valeurs est supprimée :
`{"amount":100,"limit":200}` et `{"limit":100,"amount":200}` ne désignent plus
le même état au backend. Les recettes utilisent le même sérialiseur. Pour des
objets JSON valides, leur représentation canonique reste celle utilisée auparavant.

Les captures existantes de décisions et de signatures utilisent des entrées texte :
elles restent rejouables. Une calibration obtenue avec l’ancien encodage doit être
remesurée. Un adaptateur externe ayant lui-même aplati un état doit également
changer sa version et ses clés de cache.

## Calibration liée à un appel précis

Une `CalibrationSnapshot` peut porter une `CalibrationBinding`. Celle-ci contient :

- nom et SHA-256 de la question : type, instruction, options et leur ordre ;
- SHA-256 du schéma entier, avec toutes les questions dans leur ordre ;
- identité et version du backend ;
- version de l’encodage de l’état et convention de confiance.

La famille doit être `parcimonia.<nom_de_question>`. Le backend doit déclarer
`backend_id` et `backend_version`, ou l’hôte doit les fournir à `ReflexEngine`.
Une identité explicitement fournie ne peut pas contredire celle du backend.
Ces identités sont des déclarations de provenance ; leur présence ne prouve
pas à elle seule le chargement de poids authentiques ou la qualité du modèle.

La version Laya/Jeff inclut checkpoint, SDK, révision du runtime lorsque disponible,
device et normaliseur. La version du transport TypeSafe inclut le modèle déclaré
et le normaliseur ; l’identité renvoyée par le fournisseur reste contrôlée.

Le moteur accepte un relevé unique ou un mapping de relevés par nom de question.
Un relevé unique ne s’applique qu’à la question dont toute l’identité correspond.
Un relevé sans liaison ou lié à un autre schéma/backend reste inéligible.
Les calibrations de questions non demandées et les valeurs de mauvais type sont
refusées avant l’appel du backend. Une liaison incompatible garde les réponses
comme avis non calibrés ; elle ne produit pas une permission.

Exemple avec des résultats indépendants déjà disponibles et un backend identifié :

```python
engine = ReflexEngine(backend)
report = evaluate_calibration(
    engine, questions, labelled_cases,
    data_origin="labelled_outcomes",
)
calibrations = {
    snapshot.binding.question_name: snapshot
    for snapshot in report.snapshots
    if snapshot.binding is not None
}
batch = engine.evaluate(state, questions, calibration=calibrations)
```

`ReflexEngine.calibration_binding(question, questions=questions)` construit la
liaison pour ce schéma. Si `questions` est omis, le schéma contient uniquement
la question donnée. Utiliser le lot réel, car une tête commune peut changer une
réponse lorsque les autres questions changent.

Un lot demeure `uncalibrated=true` si une seule de ses questions manque de
calibration compatible. Le drapeau historique `auto_act_allowed` d’une réponse
désigne seulement son admissibilité statistique, sous les seuils existants de
couverture, qualité et nombre de cas. Il ne remplace ni autorisation de l’hôte,
ni budgets, ni vérification du résultat.

Le rejeu de `decision_adapter` utilise l’identité du backend enregistré pour
contrôler la liaison. Un relevé d’une autre version ne peut pas être appliqué
à la réponse rejouée.

## Rapport de mesure

`reflex_calibrate` conserve le schéma entier pendant la mesure, même lorsque
certains cas n’étiquettent qu’une partie des questions. Il mesure la même valeur
`answer.confidence` que celle consommée ensuite par Reflex, y compris pour `noul`.
Une confiance absente vaut zéro pour la couverture ; la probabilité reste
disponible pour le score Brier.

Les rapports portent maintenant `schema_version=2`, avec la liaison de chaque
relevé. `authorizes_auto_act` reste faux : un rapport n’a pas de demande courante
ni d’autorité d’exécution. Les anciens relevés restent constructibles sans liaison
et utilisables comme statistiques, mais ne passent pas la porte de calibration.
Les données fixture restent inéligibles, même avec une liaison complète.

Cette liaison ne démontre pas une calibration universelle ou hors distribution.
La représentativité du domaine et de la langue doit toujours être établie par
le protocole de corpus ; la prochaine étape prévue reste la révision des champs
et une évaluation indépendante en français.

## Normalisation des réponses fournisseur

`provider_answers.normalize_systemone_answers` est partagé par Laya/Jeff et le
transport TypeSafe. Sa version est `systemone-answers/1`.

Il vérifie réponses attendues, types, options, valeurs finies et bornes. Pour
`choice` et `score`, il accepte uniquement l’écart de somme compatible avec la
précision de sérialisation déclarée par l’adaptateur : actuellement quatre
décimales, soit au plus `0.00005` par option, plus une marge flottante minime.
La distribution est ensuite renormalisée ; les niveaux de score deviennent les
libellés de la grille interne. Une somme nulle ou une distribution invalide
reste refusée. La validation de Reflex lui-même conserve sa tolérance stricte.

Les réponses originales restent dans `last_raw_answers`, distinctes des réponses
normalisées. La normalisation ne transforme pas la confiance du fournisseur en
confiance calibrée. Le traitement historique de `noul` est conservé : TypeSafe
ne lui attribue pas de confiance, Laya garde celle éventuellement fournie.

Les deux adaptateurs refusent les pertes de tokens ou d’options signalées dans
`usage`. Ce contrôle ne prouve pas l’absence d’une troncature non déclarée par
un runtime : un futur adaptateur CLEF doit aussi borner l’encodage avant inference.
Les appels échoués consomment le budget ; aucun retry n’est ajouté.

## Vérification

`tests/test_decision_contract_regressions.py` couvre les trois reproductions,
les incompatibilités de modèle/schéma/convention, les lots partiellement calibrés,
le rejeu avec provenance, la conservation JSON et les distributions arrondies ou
invalides dans les deux adaptateurs. Aucun de ces tests ne charge de modèle ni
n’appelle un service.

L’analyse initiale reste dans `ANALYSE_CLEF_GEV_2026-10-07.md`. Les copies des fichiers
avant modification sont conservées dans `runs/contracts-20261007/before/`, ignoré
par Git. Les résultats de validation et l’état de reprise sont consignés après
les vérifications.
