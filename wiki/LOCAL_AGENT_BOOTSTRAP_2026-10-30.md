# Préparation cloud de l'agent local - 30 octobre 2026

## Besoin et périmètre

Préparer un secours local et décharger les itérations de code/ingénierie et
d'éditeurs d'assets. Réutiliser les callers existants ; ne pas démarrer de job
Work, charger de modèle, modifier le homelab ou présumer de la disponibilité
d'une version future. TASK-074 reste ouverte.

Base inspectée et testée : `83f40ebd715d09add32c45a73c44dc48e88a472a`.
Les PR #12 (mémoire) et #13 (Tev1) restent distinctes ; aucune de leurs API n'est
requise par cet incrément. Pas de nouveau scheduler, service ni dépendance runtime.

## Réalisation

- `local_probe.py` et `examples/eurekai_diagnostic.py` : GET local `/v1/models`,
  inventaire de la machine appelante et rapport exclusif. Aucune inférence,
  réparation ou collecte de logs/credentials.
- `local_iteration.py` : callbacks de production et évaluation autour de
  `capture_run` et `VerifierRegistry`. Baseline vérifiée, meilleur candidat,
  budgets, stagnation, abstention et résultats partiels.
- `examples/local_iteration_demo.py` : fixture authored, aucun modèle ni rendu.
- Procédure et frontières : `docs/LOCAL_AGENT_BOOTSTRAP.md`.

## Vérification réellement exécutée

Environnement : Python 3.12.14 dans la session cloud, pytest 9.2.0.

| Contrôle | Résultat |
| --- | --- |
| Suite avant modification | 809 tests passés |
| Nouveaux tests ciblés | 103 passés : 67 diagnostic, 36 itérations |
| Suite complète finale | 912 tests passés |
| Revue indépendante ciblée | Défauts reproduits, corrigés puis revérifiés |
| Démonstration hors ligne | Candidat 1 invalide rejeté ; candidat 2 conservé ; arrêt `patience` après 4 propositions |

Les tests HTTP lancent des serveurs loopback de test, avec réponses erronées,
redirections et envois lents. Les tests de boucle utilisent des callbacks et des
scores écrits pour le test. Ce ne sont pas des mesures d'un modèle ou d'un
éditeur réel. Un avertissement de compatibilité d'un plugin pytest de
l'environnement n'a pas affecté le résultat.

La revue a notamment révélé :

1. Des en-têtes envoyés lentement pouvaient dépasser le timeout total : ajout
   d'une échéance sur la socket, avec témoin HTTP lent.
2. La sortie retenue pouvait être modifiée après retour : snapshots canoniques
   privés et copies défensives pour les consommateurs.
3. Une mutation non JSON ou un retour invalide du vérificateur pouvait perdre
   le résultat partiel : arrêt explicite préservant le meilleur, sans rejeu.

## Limites et reprise

Le GET n'a pas été exécuté contre une machine du homelab. Aucune cause de panne
de LM Studio n'est démontrée. Le diagnostic n'observe pas le Hailo ni la topologie
PCIe ; depuis un autre poste, son inventaire reste celui de l'appelant. Un listing
de modèles n'établit jamais qu'un modèle est chargé ou utilisable en inférence.

Le helper conserve un descripteur, pas les fichiers de l'asset. Le caller doit
fournir les snapshots, contrôles techniques, moteur/VLM, verrouillage GPU et
timeouts des outils. Sa deadline est coopérative entre callbacks. Les tokens,
coûts, économies et performances matérielles restent inconnus.

Prochaine étape matérielle : lancer le diagnostic explicite sur l'hôte concerné,
puis qualifier une inférence et une boucle d'éditeur sur une copie isolée.
Omettre ces nouveaux imports et exemples conserve les comportements existants.
La réparation et l'activation ne font pas partie des résultats revendiqués.
