# Importer les sources du pilote de rapprochement

Le [pilote de rapprochement](KNOWLEDGE_CROSSWALK.md) accepte maintenant des
projections cloud explicites et des exports de textes sélectionnés. Les
importeurs produisent un lot compatible avec la commande `update`, accompagné
d'un manifeste de provenance. Ils ne parcourent aucun compte ni poste distant,
n'appellent aucun modèle et n'activent aucun agent.

## Sources prises en charge

| `source-kind` | Entrée JSON reçue | Portée conservée |
| --- | --- | --- |
| `second_brain` | `{"results":[...]}` de la recherche Kanboard | Résultats partiels, pas fils complets |
| `knowledge_inbox` | `{"items":[...],"syncStatus":"...","syncAgeSeconds":0}` | Captures de réception ; santé de synchronisation conservée telle que déclarée |
| `documents` | `{"documents":[...]}` | Textes fournis explicitement, canal déclaré par l'appelant |

L'appelant effectue la lecture via son connecteur existant et conserve sa réponse
structurée, ses paramètres et son heure d'observation. Une réponse de recherche
vide prouve seulement que cette recherche n'a rien renvoyé. Une synchronisation
manuelle réussie ne qualifie ni le cron ni l'exhaustivité des historiques.

Une ligne Second Brain contient exactement `detail`, `id`, `kind`, `project`,
`status`, `tags`, `title`, `url`. Une ligne de réception contient exactement
`confidence`, `createdAt`, `id`, `project`, `sourceKind`, `sourceUrl`, `status`,
`summary`, `title`. Les champs inconnus ou identités dupliquées refusent le lot.
Les URL nulles sont remplacées par des références opaques clairement nommées
`projection:`. Elles ne sont jamais ouvertes par le programme.

Pour les recherches, l'identité est `(instance choisie, kind, id)`. Pour la
réception, l'identité utilise son `id` natif ; corriger `sourceKind` ne crée pas
une seconde copie active du même item. Le hash canonique du record complet
définit sa version, sans intégrer l'heure de collecte. Un réordonnancement de
la réponse change son empreinte, pas les identités des fragments.

Les statuts bruts et scores déclarés restent dans le manifeste. Une tâche
terminée ne devient pas automatiquement une décision remplacée. `active`
signifie ici éligible à la recherche, sans validation du texte ni de son
actualité. `confidence` n'est ni calibré ni utilisé comme preuve de vérité.

## Préparer puis appliquer un import

```sh
python scripts/parcimonia_knowledge.py create essai --out index-0.json
python scripts/parcimonia_knowledge.py import index-0.json response.json --source-kind second_brain --feed-id instance-A-search --observed-at 2026-11-02 --parameters parameters.json --out batch-1.json > manifest-1.json
python scripts/parcimonia_knowledge.py update index-0.json batch-1.json --expected-head HASH_DU_MANIFESTE --out index-1.json
```

`HASH_DU_MANIFESTE` désigne `manifest.expected_head` dans la sortie de préparation.
`parameters.json` est un objet JSON facultatif qui conserve les paramètres de
la lecture effectuée. Préparer le lot ne modifie pas le snapshot d'entrée.
L'application garde la précondition de tête existante ; elle ne fournit pas un
verrou sur un stockage partagé.

Tous les imports de projections restent de couverture `partial`. Une lecture
échouée doit être déclarée séparément :

```sh
python scripts/parcimonia_knowledge.py unavailable index-1.json --feed-id instance-A-search --observed-at 2026-11-02 --reason-code read_failed --out unavailable.json
```

Le lot obtenu ne retire aucun fragment. Les raisons possibles sont
`unavailable`, `read_failed`, `not_connected`, `invalid_response`. Le canal
connu du flux est conservé s'il est unique ; sinon il reste inconnu (`null`).
Une erreur de lecture ne prouve pas que la machine concernée est arrêtée.

L'absence d'un record dans une réponse partielle n'entraîne aucune suppression.
Seul un record présent remplace explicitement ses propres anciens morceaux,
avec retrait de ceux qui n'existent plus après sa correction ou son raccourcissement.
Les autres flux et records restent conservés. Un changement de contenu sous une
même version documentaire déclarée est visible via le hash du record ; il ne
constitue pas une validation de l'immuabilité de la version externe.

## Exporter des fichiers locaux sélectionnés

Le catalogue fermé `parcimonia.local-knowledge-catalog/v1` contient une liste
`documents` avec les champs suivants :

```json
{
  "schema": "parcimonia.local-knowledge-catalog/v1",
  "documents": [{
    "id": "note-architecture",
    "file": "notes/architecture.md",
    "sha256": "REMPLACER_PAR_LE_SHA256_EXACT_DES_OCTETS_DU_FICHIER",
    "version": "revision-declaree-1",
    "project": "architecture",
    "uri": "vault:notes/architecture.md",
    "timestamp": "not_provided",
    "state": "active"
  }]
}
```

Le placeholder n'est pas un digest valide. Le remplacer par les 64 caractères
hexadécimaux minuscules calculés sur les octets réels, fins de ligne comprises.
Les URI, versions, dates et états restent déclarés. Ne pas remplacer une date
de source inconnue par l'heure d'export.

```sh
python scripts/parcimonia_knowledge.py export-documents catalog.json --root CHEMIN_LOCAL_EXPLICITE --out documents.json > export-manifest.json
python scripts/parcimonia_knowledge.py import index-1.json documents.json --source-kind documents --channel local --feed-id poste-A-selected --observed-at 2026-11-02 --out batch-local.json > import-manifest.json
```

Les fichiers `.md`, `.txt` et `.jsonl` sont lus comme textes UTF-8, sans
interpréter leurs instructions ou lignes JSONL. Les octets sont vérifiés avant
décodage ; les fins de ligne et un éventuel BOM sont conservés. Le manifeste
contient les chemins relatifs, empreintes et tailles, sans texte ni racine
absolue. Les fichiers non sélectionnés ne sont pas parcourus.

Les chemins sont relatifs POSIX stricts, sans segments vides, `.` ou `..`,
antislash, lecteur Windows ou flux alternatif. Les liens, jonctions et autres
reparse-points Windows sont refusés sur la racine et les composants sélectionnés.
Un échec de pin, d'encodage ou de lecture refuse l'export entier. L'appelant
possède la racine et ses parents ; ces observations ne sont pas un sandbox
contre des remplacements concurrents par un propriétaire hostile.

Limites de l'export : 64 fichiers, 64 Kio par fichier, 2 Mio pour le résultat.
Un export lisible n'établit aucune compatibilité sémantique ni authenticité.
Un archiveur de conversation géant dépassant ces bornes requiert son propre
importeur ; ce pilote n'en revendique pas le support.

## Citations, budgets et reprise

Les champs sont découpés en fenêtres de 512 caractères Unicode, au maximum.
Les localisateurs donnent les offsets de début et de fin exclusive en caractères,
pas en octets. Une fenêtre peut couper un mot, une négation ou son contexte ;
les morceaux entièrement blancs sont omis. La découpe ne garantit donc ni une
reconstruction intégrale ni une préservation du contexte sémantique.
`manifest.chunking.context_complete` reste `false`. Relire le champ source
complet avant d'en tirer une contrainte, une décision ou une action.

Les versions et empreintes identifient le record fourni, pas un historique
authentifié. Pour la recherche cloud sans date, `timestamp=not_provided` ; pour
la réception, `createdAt` est conservé comme date déclarée de la source.
L'heure d'observation reste séparée dans le manifeste.

Le module prépare au plus 256 fragments dans un index de 2 Mio. Les réponses
contiennent au plus 256 records ; la combinaison avec les fragments déjà retenus
est vérifiée avant toute écriture. Un dépassement est un refus explicite, sans
troncature ni effacement silencieux. Utiliser une sélection ou un snapshot borné
différent ; aucune recherche globale entre plusieurs snapshots n'est implémentée.
Les paramètres sont bornés à 8 Kio, profondeur 8 et 2 048 nœuds JSON.

Les lots, exports et manifestes peuvent contenir des informations privées.
Conserver ces fichiers dans un emplacement privé ; les exemples distribués
utilisent uniquement des fixtures. La CLI refuse les sorties existantes et
utilise les mêmes contrôles de lecture et d'écriture que le pilote.
Code `0` : préparation ou application effectuée dans ce périmètre ; code `2` :
entrée invalide/indisponible ou écriture refusée. Aucun gain de coût, vitesse,
pertinence sémantique ou exhaustivité n'est mesuré.

```sh
python examples/knowledge_collection_demo.py
python -m unittest discover -s tests -p 'test_knowledge*.py'
```
