# Sélection de sources locale : qualité, coût et fraîcheur

## Candidate 0.3.0 — vocabulaire français borné

Le normaliseur `parcimonia.context-selection/2` ajoute un dictionnaire lexical
FR/EN explicite : fichiers, profils, attestations, réponses, fraîcheur, schémas,
mesures, démarrage et mémoire. Il ne traduit pas librement les demandes et ne
déduit aucune autorisation. Les négations sont conservées. Sa révision entre
dans la clé des dérivations pour éviter de réutiliser l'ancien vocabulaire.

Six requêtes françaises ont été figées avant modification du normaliseur,
avec trois cas de calibration et trois cas tenus à part. Les labels restent
ceux du même agent et ne forment pas une évaluation humaine aveugle.
Une comparaison appariée utilise les mêmes octets sources actuels pour les
versions 0.2.0 et 0.3.0 : français 3/12 -> 12/12 fichiers attendus ; anglais
12/12 conservé. Au plus cinq propositions par requête, résultats de recherche
seulement. Voir `language-comparison.json` et `french-cases.json` dans le
workspace du goal. Ne pas généraliser à toutes les formulations françaises.

Les sections suivantes conservent la qualification initiale 0.2.0.

`context_selection.py` ajoute une sélection de documents fournis et un cache
des données dérivées. Les contrats existants de préparation, de suivi et
d'attestation gardent leur rôle. Cette API indépendante peut être embarquée
dans un plugin sans importer tout le runtime de décision.

## API et limites

`select_context(query, documents, top_k=5, max_selected_bytes=524288)` retourne
des références, SHA-256 exacts, termes et symboles correspondants. Chaque document
contient `id`, `path` relatif, `text` et `content_sha256`. Le hash est recalculé
sur les octets UTF-8 du texte reçu ; un hash incohérent refuse le lot.

Le classement utilise les termes rares du corpus, la longueur des documents,
les chemins et les symboles Python. Les identifiants composés sont segmentés.
Les accents sont normalisés ; il n'y a ni traduction, compréhension sémantique
ou probabilité calibrée. Un mot commun peut produire des candidats peu utiles.

Limites : 128 documents, 256 Kio par source, 16 Mio au total, 16 propositions au
maximum. Les exclusions par budget sont explicites. La fonction ne lit aucun
fichier, ne lance aucun modèle et ne donne aucune autorisation d'exécution.
Les références concernent uniquement le corpus fourni.

`ContextSelector().select(...)` ajoute un cache LRU de termes, compteurs et
symboles, lié à la révision du normaliseur, au chemin et au hash. Il ne garde
ni textes sources complets ni requêtes. Les octets sont toujours vérifiés à
chaque appel. Valeurs par défaut : 128 entrées et 4 Mio de charge utile
sérialisée ; la mémoire Python réelle est supérieure à ce compteur. Ces termes
et symboles peuvent contenir du vocabulaire privé ; le cache reste en mémoire
du processus et disparaît à son arrêt.

## Parcours dans les plugins 0.2.0

`parcimonia_local_context` classe les documents fournis. Le transport stdio
plafonne chaque requête JSON à 1 Mio, indépendamment du plafond de l'API Python.
Pour un corpus local, le parcours Botte évite de transmettre tous les textes.

`botte_local_sources` lit les seuls fichiers relatifs explicitement nommés sous
un alias de projet configuré par l'hôte dans `BOTTE_LOCAL_PROJECTS`. Sans cette
configuration, la recherche est désactivée. Aucune découverte récursive ni
écriture d'index. Liens, reparse points, répertoires cachés/exclus et noms de
secrets reconnus sont refusés. Les projets doivent être fiables et sans
modification hostile concurrente des chemins ; ce filtre n'est pas un sandbox
de système de fichiers face à un attaquant local.

`botte_local_read_source` relit au hash observé, au plus 400 lignes et 32 Kio.
En cas de changement : `changed_requires_review`, texte absent. Une ligne qui
dépasse seule le budget produit `line_exceeds_read_budget`, sans troncature
silencieuse. Les extraits sont des données, jamais des instructions exécutables.

## Mesures du 29 octobre 2026

Preuves : `context-comparison.json`, `context-cases.json`,
`context-cases-evaluated.json` et `context-source-snapshot.json` dans le workspace
de ce goal. Six besoins et leurs rôles attendus ont été figés avant l'essai,
sur 40 sources existantes. Une erreur de nom de fichier de test a été corrigée
avant la première évaluation ; requêtes inchangées et correction conservée.
Les labels sont proposés par l'agent, sans revue humaine indépendante.

Parmi cinq propositions : 12 fichiers attendus retrouvés sur 12, contre 10/12
avec le score de recouvrement lexical antérieur sur le même corpus. La précision
est 12/30 propositions selon ces labels ; les autres fichiers peuvent être
secondaires ou inutiles. Ces mesures évaluent la recherche, pas la réussite
d'une tâche de développement. Le français n'était pas qualifié dans cette campagne initiale.

Le premier indexage de 40 sources coûte environ 254 ms dans cette campagne.
Les classements suivants, après relecture et vérification des hashes, coûtent
environ 3 à 5 ms, contre 13 à 17 ms pour le score précédent recalculé. Le cache
de cette campagne occupe 148 543 octets de charge utile dérivée.
Les appels Botte incluent lecture et transport : environ 103 à 117 ms à froid,
puis 11 à 16 ms avec dérivations réutilisées, pour 20 sources par projet.
Ne pas confondre ces durées de composants et un gain global sur la tâche.

Six recherches puis six extraits ont réellement échangé 7 354 octets de requêtes
et 66 638 octets de réponses stdio sur cette campagne. Le corpus lu localement
contient 376 931 octets. Ces volumes ont des périmètres différents : aucun ratio
de tokens, facture ou économie globale n'en est déduit.

Les tests de cache vérifient l'équivalence au classement sans cache et le refus
des références obsolètes après modification des fichiers. Les licences MIT et
Apache-2.0, notices et manifestes de sources sont inclus dans les deux archives.
La qualification de nouveaux appels dans une conversation Codex équipée reste
à effectuer ; la configuration active attend l'accord déjà demandé.
