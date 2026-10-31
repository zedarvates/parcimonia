# Confidentialité

Le plugin ne transmet aucune donnée à un réseau et n'appelle aucun modèle.
Les textes et rapports sont traités dans le processus, sans journal ni stockage.
Le parcours de sources Botte est désactivé sans BOTTE_LOCAL_PROJECTS fourni par
l'hôte. Il lit seulement les fichiers explicitement désignés sous ces racines
fiables, refuse liens et emplacements exclus, et ne conserve aucun texte source
ou index sur disque. Un cache privé au processus conserve au plus 4 Mio de
termes, compteurs et symboles dérivés, liés au chemin et à l'empreinte. Ces données
dérivées peuvent contenir du vocabulaire privé. Les requêtes ne sont pas cachées.
Les octets source sont toujours relus pour vérifier leur fraîcheur. La mémoire
Python peut dépasser la taille sérialisée des charges utiles des caches.
La configuration contient des chemins privés : ne pas
l'inclure dans une archive publique. Les extraits choisis sont renvoyés au client.
Botte conserve au plus 4 Mio de résultats de calcul et leurs empreintes dans
un cache mémoire privé à ce processus, supprimé à son arrêt. Parcimonia ne cache
pas les rapports. Les limites portent sur la charge utile ; la mémoire Python
et les buffers du transport ont un coût supplémentaire.

L'observation matérielle lit RAM, engagement et espace disque disponibles ainsi
que, si nvidia-smi est présent, le nom et la mémoire des GPU locaux. Elle ne lit
aucun numéro de série, nom d'utilisateur ou adresse réseau. La clé matérielle
est une empreinte de cette configuration générale, sans identifiant personnel.
Le programme du pilote NVIDIA peut avoir ses propres mécanismes indépendants.

Le client Codex et son fournisseur de modèle reçoivent les arguments et résultats
des appels selon leur propre politique. Le traitement local du plugin ne signifie
pas que toute la conversation Codex reste hors ligne. Ne fournir que les données
autorisées pour la conversation concernée.
