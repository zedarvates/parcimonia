# Parcimonia Local 0.4.1

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
Les outils se nomment `parcimonia_local_plan`, `parcimonia_local_hardware`, `parcimonia_local_context`.

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
