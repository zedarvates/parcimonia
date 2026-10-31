# Audit des entrées et préparation de la comparaison

Incrément du 7 octobre 2026. L’interface de revue est maintenant accessible dans
le navigateur intégré ; son état observé reste `0 / 120`. Aucun export humain
n’a été trouvé dans le dossier de travail ni parmi les fichiers `context-review`
de Téléchargements. Cette observation ne prouve pas qu’aucun export existe ailleurs.

## Audit du texte capturé

Le contrôle du formulaire a montré des enveloppes encore présentes dans le
corpus historique : balises de contexte avec attributs, réponses structurées de
l’interface et messages de délégation. Le nettoyage historique ne couvrait pas
toutes ces variantes. Elles ne doivent pas être assimilées sans revue à des
demandes humaines ordinaires.

`context_input_audit.py`, version `context-input-audit/1`, détecte des signaux
précis et propose une isolation conservatrice. Il ne choisit pas de label, ne
certifie pas l’origine humaine et ne remplace pas les fonctions historiques
d’ingestion. Un marqueur littéralement cité dans une vraie question peut donc
nécessiter une revue manuelle. Une suppression proposée de blocs connus reste
une proposition : aucun texte de source n’est réécrit automatiquement.

Sur le dossier existant : **114 cas candidats et 6 cas isolés**. Ce résultat
décrit les règles de sélection, pas la précision d’un modèle ou celle du filtre.
Les originaux et leurs occurrences restent dans le dossier antérieur. La
quarantaine conserve les six cas complets et les raisons d’audit.

Le sous-lot garde les composantes de source calculées sur les 120 cas, y compris
les liens passant par un cas isolé. Les groupes ne sont pas ratifiés et aucun
split n’est figé. Les deux dossiers ont des identités distinctes ; un export
humain de l’ancien dossier ne peut pas être attribué silencieusement au nouveau.

Livrables locaux ignorés par Git :

- `runs/signature-corpus/review-audited-20261007/input-audit.json` ;
- `review-packet.json` et `review.html` pour les 114 cas ;
- `quarantine.json`, avec les originaux et les décisions ;
- `comparison-readiness.json` et manifeste des hashes.

La décision d’isolation est recalculée avant application. Modifier une décision
dans le JSON d’audit ou changer le paquet source invalide l’application.

## Porte de comparaison

`assess_context_comparison` contrôle le paquet avant toute capture de résultats :

1. Texte et identités des cas, enveloppes restantes, provenance récupérée et
   revue des groupes avec annotateur identifié.
2. Partition développement/test disjointe couvrant le dossier, affectation de
   chaque cas et hashes des cas finaux.
3. Absence de conversations, groupes de source ou de paraphrases traversant les
   deux partitions ; absence d’identifiants d’entraînement locaux dans le test.
4. Nombre suffisant de cas de test annotés en français ou français mixte.
   La barre initiale de 20 est un minimum de pilote, pas une certification.
5. Distinction entre label de type connu et toutes les dimensions de contexte
   connues : un `null` ne devient pas une liste vide.
6. Identités et disponibilité déclarées des bras, puis recours à la porte
   existante `route_experiment.assess_experiment` pour les résultats appariés.

La baseline et le candidat doivent porter sur le même lot. Cette porte prépare
la collecte ; elle n’exécute aucun backend. Une déclaration de disponibilité
reste une déclaration et ne fournit ni preuve de chargement ni autorisation.

La comparaison n’est pas prête dans le dossier réel : revue humaine absente,
split non figé, labels de test et captures candidates manquants. Les rapports
laissent qualité et économies à `null`. Même un plan fixture prêt à recevoir des
captures ne certifie pas l’indépendance des labels. Une mesure contre une revue
humaine doit être décrite comme accord avec ces labels ; les issues vérifiées
et la chaîne canonique de benchmark restent nécessaires pour les revendications
de qualité et de ressources.

## Correction des hashes du split

`apply_context_review` calculait les hashes juste avant d’ajouter l’affectation
`development` / `heldout` aux cas. Les hashes ne correspondaient donc pas aux
enregistrements finalement sauvegardés. Le test de régression reproduit cet
écart et le calcul lie maintenant les cas finaux, avec
`case_hash_scope=final_case_record/1`. Un cas modifié ou une affectation incohérente
invalide la porte. Un manifeste ancien présentant cet écart doit être régénéré
depuis la revue d’origine, sans changer les labels.

## Commande reproductible

```powershell
rtk proxy .venv/Scripts/python.exe examples/context_comparison_pilot.py --packet runs/signature-corpus/review-20261007-final/review-packet.json --output-dir runs/signature-corpus/nouvel-audit
```

La commande préserve les dossiers existants et refuse l’écrasement. Elle écrit
uniquement dans la zone locale `runs/`. Aucun modèle, compte payant, service GPU
ou routage automatique n’est appelé ou activé.

Le contrôle navigateur présent a confirmé les champs vierges et la progression
initiale du dossier original. Il ne remplace pas une preuve de téléchargement
ou d’import/export interactif complet ; les tests du JavaScript et des importeurs
couvrent ces contrôles séparément sur des fixtures.
