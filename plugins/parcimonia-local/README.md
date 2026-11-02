# Parcimonia Local 0.4.3 — candidat

Proposer des routes de calcul et des fichiers utiles à partir de mesures et de sources vérifiées par empreinte.

Python 3.10+ doit être installé et accessible avec la commande `python`.
Le paquet utilise seulement la bibliothèque standard. Aucun téléchargement,
modèle, installation globale ou service réseau au démarrage.

Pour vérifier le transport sans modifier Codex : lancer `python -I -B server.py`
dans le dossier extrait, puis envoyer initialize, notifications/initialized,
tools/list et tools/call en JSON-RPC, un objet par ligne.

Pour tester dans Codex, ajouter le dossier à un marketplace local puis installer
le plugin et ouvrir une nouvelle session qui le charge. La découverte des outils
et un appel réel dans cette session sont nécessaires pour qualifier cette surface.
Les outils se nomment `parcimonia_local_plan`, `parcimonia_local_hardware`,
`parcimonia_local_context` et `parcimonia_local_observations`.

Les requêtes et réponses JSON-RPC sont bornées à 1 Mio chacune. Les identifiants
texte de requête ont une limite de 256 octets UTF-8. En cas de résultat trop
volumineux, l'outil renvoie `output_budget_exceeded` sans contenu partiel.
Le conseiller accepte aussi la tâche log_compact avec les mêmes gates de preuve.

La sélection de contexte prend des documents fournis ; elle ne lit aucun chemin.

Les observations de capacité concernent uniquement l'hôte du processus et le
volume du plugin. GPU NVIDIA optionnel via nvidia-smi en lecture seule ; son
absence laisse la capacité GPU inconnue. L'absence de mesure ne vaut pas zéro.
La capacité d'un modèle ou d'un accélérateur ne se déduit jamais de son nom.

Les recommandations sont des propositions ; rapports hôte non attestés, aucune exécution ni réservation de ressources. Le coût d'électricité reste inconnu.

Voir PRIVACY.md, PUBLICATION.md, SOURCES.json et FILES.json.

Le candidat 0.4.3 ajoute `parcimonia_local_observations` avec un argument
`request`. Il compare les rapports fournis aux exigences datées de la tâche
exacte, conserve les rejets et propose une seule observation suivante.
`ready` signifie que les rapports actuels compatibles disent tous `pass` ;
ce résultat ne certifie ni leur vérité ni une autorisation. L’horloge utilisée
est celle de l’hôte du plugin. Aucune preuve n’est collectée ou enregistrée.
Le guide de développement est `docs/VERIFIED_OBSERVATIONS.md` dans le dépôt.
La version 0.4.2 reste le candidat de qualification distinct de la PR #39 ;
ce changement de source ne modifie aucun plugin installé.
