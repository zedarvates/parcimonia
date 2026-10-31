---
name: local-plan
description: Comparer des routes de calcul sur ressources fraîches et mesures de qualité, avec abstention explicite.
---

Utiliser parcimonia_local_hardware pour observer l'hôte, puis parcimonia_local_plan avec request, snapshot et candidates.
Chaque mesure doit correspondre au workload_sha256 et au hardware_key de l'hôte, avoir au moins trois essais tous validés par un vérificateur nommé et dater de moins de 24 heures.
Les ressources doivent dater de moins de 60 secondes. Garder des réserves de 5 Gio de RAM, 6 Gio d'engagement, 15 Gio de disque.
Les latences incluent le démarrage à froid ou à chaud. Ne pas additionner la VRAM de plusieurs cartes. NPU non qualifié dans cette version.
Les rapports fournis restent non attestés. Ne jamais exécuter une route sur la seule proposition, ni inventer une mesure, un coût ou une qualité manquants.
Un verrou lourd inconnu bloque toute proposition lourde. Le plugin ne réserve pas Odin et n'autorise aucune commande externe.
Pour des documents déjà fournis, utiliser parcimonia_local_context : références, hashes et omissions, sans texte persisté. Les scores sont lexicaux.
Pour éviter de transmettre tout le corpus à l'agent, préférer botte_local_sources lorsque l'hôte a explicitement configuré son alias de projet.
