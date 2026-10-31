# Banc local de décisions : premier incrément du 20 octobre 2026

Le banc `decision_gym.py` génère 300 épisodes synthétiques hors réseau. Les
baselines exécutées sont `rules` et `rules_retrieval` : calcul direct, ou lecture
d'un cache exact fourni par la fixture lorsque document et objectif correspondent.
Ce cache n'est pas un moteur de recherche ni une mémoire apprise.

Les épisodes portent sur une somme ou une extraction dans un petit tableau.
Six scénarios couvrent le cas normal, le remplacement d'une donnée, une sortie
mal formée injectée, une révision périmée, l'indisponibilité des outils et un
budget nul. La réparation de contexte est un événement synthétique explicite de
l'hôte. Un vérificateur séparé recalcule la réponse depuis le document attendu ;
le label et le document oracle ne sont pas transmis au routeur.

## Reproduction

Depuis la racine, avec Python et pytest déjà disponibles :

```powershell
$env:PYTHONPATH = 'C:\TiberiumAI\src'
rtk python -m pytest -q tests/test_decision_gym.py
rtk python examples/decision_gym_pilot.py --output-dir runs/decision-gym-20261020-v1
```

Le pilote exige un nouveau dossier sous `runs/` et refuse de réutiliser un
dossier existant. Il écrit `episodes.json` et `report.json`, ignorés par Git.
Le hash canonique du corpus est reproductible pour une même graine. Les durées
mesurées changent entre exécutions. Les p50/p95 utilisent le rang supérieur et
somment les étapes de chaque épisode ; ils excluent génération, sérialisation,
écriture du rapport et démarrage de Python. Ce n'est pas un coût système complet.

## Séparation et limites

Exécution du 20 octobre : les deux bras vérifient chacun 200 épisodes sur 300,
escaladent 50 épisodes sans outil disponible et s'arrêtent sur 50 budgets nuls.
Les 50 sorties mal formées injectées sont rejetées puis corrigées. Sur le lot
`test` du protocole : 48 résultats vérifiés, 12 escalades, 12 budgets nuls par
bras. Cela n'est pas un taux de réussite sur des demandes réelles.

Rapports : `runs/decision-gym-20261020-v1/episodes.json` et `report.json`.
Validation : 68 tests ciblés réussis (banc, contrats et cascade de contexte).

Les 50 familles contiennent chacune les six scénarios et ne traversent jamais
les lots. Le découpage effectif est **150/78/72**, ajustement de 150/75/75 pour
conserver les groupes entiers. Les modèles linguistiques de requête et opérations
restent partagés : ces lots valident le protocole, pas une généralisation
linguistique ou un test de modèle gelé. Les objectifs sont structurés ; les
reformulations naturelles restent à ajouter avant une étude SFT.

Chaque trace conserve entrée, hash, route, réponse, verdict, budget, état suivant
et durée. Les erreurs consomment un appel. Un résultat invalide est rejeté et la
reprise est visible. `escalate` et `budget_exhausted` arrêtent le rejeu sans
prétendre avoir résolu la tâche. Aucune route de modèle n'est exécutée.

Les bras cascade de signature existante, Jev, modèle non adapté et SFT sont
`not_run`. La cascade historique ne traite pas directement cette question de
choix de mécanisme ; son intégration demande un adaptateur explicite.
Les coûts monétaires et énergétiques restent inconnus (`null`), ainsi que les
résultats des bras non exécutés. Les caches sont préparés par le générateur :
leur présence ne mesure pas le coût de constitution d'une mémoire réelle.

Les règles suffisent à tous les calculs exécutables de ce banc. Il ne justifie
donc aucun SFT à ce stade. Une décision de promotion reste `inconclusive`.
L'étape suivante utile est de définir des demandes en langage naturel et un
jeu indépendant de reformulations avec oracle conservé, puis de mesurer les
erreurs résiduelles des baselines. Les données d'entraînement éventuelles
nécessiteront aussi une preuve d'admissibilité des différentes routes ; le
présent rapport ne constitue pas encore un export SFT multi-route.
