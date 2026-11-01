# Rapprocher les discussions cloud, locales et le savoir

Ce pilote optionnel prépare des **candidats lexicaux sourcés** entre des fragments
de discussions, de mémoire et de wiki fournis explicitement. Il complète les
[relations déclarées du catalogue](ASSET_RELATIONS.md) et le
[raccordement au moteur de savoir existant](LOCAL_KNOWLEDGE.md). Il ne remplace
pas ces composants et ne construit pas un second wiki.

Le périmètre couvre quatre canaux : `cloud`, `local`, `memory`, `wiki`.
« Cloud » désigne ici la provenance d'un historique ; aucun fournisseur de
conversation particulier n'est requis. Ce module ne collecte aucun historique,
ne contacte aucun poste et n'appelle aucun modèle.

## Ce qui est obtenu

- Index inversé de termes normalisés, avec stopwords français et anglais.
- Rapprochements entre flux ou projets différents, sur au moins deux termes
  communs, avec un score entier de chevauchement et les deux passages exacts.
- Identités, versions déclarées, canaux, projets, horodatages déclarés,
  localisateurs et empreintes SHA-256 du contenu conservés dans les citations.
- Mises à jour explicites : fragments ajoutés, changés, retirés ou conservés.
- Couverture déclarée par flux : `complete`, `partial`, `unavailable`.

Les résultats portent toujours `kind=lexical_candidate` et `status=unverified`.
Ils ne prouvent aucune complémentarité, contradiction, compatibilité, nouveauté
ou décision. Le score n'est pas une probabilité. Les négations et instructions
restent dans le passage cité ; elles ne sont pas interprétées ni exécutées.
La relecture sémantique des candidats est une étape ultérieure.

## Préparer les entrées

Le fichier de lot suit le schéma fermé `parcimonia.knowledge-update/v1` :

```json
{
  "schema": "parcimonia.knowledge-update/v1",
  "coverage": [{"id": "cloud-export", "status": "partial"}],
  "removals": [],
  "upserts": [{
    "id": "cloud-export:thread-A:message-1",
    "version": "export-1",
    "feed_id": "cloud-export",
    "channel": "cloud",
    "project": "architecture",
    "uri": "archive:thread-A",
    "locator": "message-1",
    "timestamp": "2026-11-01",
    "state": "active",
    "text": "Contrôler les dimensions de la toiture et de l'escalier."
  }]
}
```

Les identités sont choisies par l'importateur. `uri` et `locator` sont des
références opaques, jamais ouvertes par le pilote. `timestamp` est conservé tel
que déclaré, sans interprétation chronologique. Pour une discussion, conserver
un identifiant de fil et de message ; pour un fichier, sa révision et ses lignes.
Le découpage des longs documents appartient à l'importateur et doit préserver
le contexte nécessaire à la relecture, notamment les contraintes et négations.

Tous les champs de fragment illustrés sont obligatoires. Les états acceptés
sont `active`, `superseded`, `rejected`, `paused`. Les trois derniers restent
consultables dans le snapshot mais ne fournissent aucun candidat. Le programme
ne déduit jamais cet état de la prose ou de la date. Une correction d'état ou de
texte exige une nouvelle version. L'immuabilité id/version est contrôlée contre
le snapshot retenu ; elle n'est pas vérifiée contre un historique supprimé.

## Exécuter le pilote

Depuis le dépôt, Python 3.10 ou ultérieur suffit :

```sh
python scripts/parcimonia_knowledge.py create essai --out index-0.json
python scripts/parcimonia_knowledge.py update index-0.json lot.json --expected-head HASH_DU_PREMIER_RESULTAT --out index-1.json
python scripts/parcimonia_knowledge.py candidates index-1.json --fragment-id cloud-export:thread-A:message-1 --limit 5
python examples/knowledge_crosswalk_demo.py
python -m unittest discover -s tests -p 'test_knowledge*.py'
```

La commande `update` écrit uniquement le nouveau snapshot dans `--out` et
affiche son empreinte et les compteurs `added`, `changed`, `removed`, `reused`.
Un fichier existant, un lien final ou une tête attendue différente sont refusés.
La précondition sur l'empreinte compare des valeurs ; elle n'est pas un verrou
sur un stockage partagé. L'appelant doit organiser l'écriture concurrente.

Les suppressions exigent un identifiant existant dans `removals`. L'absence d'un
fragment ou d'un flux du prochain lot ne supprime rien. Une panne du collecteur
doit mettre le flux à `unavailable`, sans transformer sa dernière lecture en
source vide. Ses fragments restent conservés mais ne participent plus aux
candidats. Un flux `partial` reste utilisable et rend la couverture incomplète.
`complete` reste une déclaration de l'importateur, limitée au flux choisi.

## Contrats et limites

L'API pure expose `create_knowledge_index`, `validate_knowledge_index`,
`update_knowledge_index` et `find_knowledge_candidates`. Les snapshots utilisent
`parcimonia.knowledge-index/v1`, les recherches
`parcimonia.knowledge-candidates/v1`. Les fonctions retournent des valeurs
indépendantes et ne modifient pas leurs entrées.

Le pilote accepte au plus 256 fragments et 256 flux, 8 Kio de texte et
256 termes retenus par fragment, et 2 Mio UTF-8 canonique par snapshot/résultat.
Les dépassements sont refusés ; ils ne deviennent pas des omissions silencieuses.
Le résultat indique le nombre de candidats omis, les raisons de troncature
(`limit` ou `output_budget`), l'empreinte de l'index et toute couverture déclarée
incomplète. Les candidats sont plafonnés au budget de sortie avant livraison. Un résultat vide ne concerne
que les fragments actifs des flux disponibles fournis. Les termes communs ne
détectent pas des équivalences entre langues, synonymes ou concepts éloignés.
Deux textes strictement identiques sont dédoublonnés, y compris entre miroirs.

La mise à jour réutilise les appartenances de termes des fragments conservés.
La validation d'intégrité re-tokenise néanmoins le snapshot fourni. Le compteur
`reused` décrit les données conservées, pas du temps CPU ou des tokens économisés.
Aucun gain de qualité, vitesse, coût ou couverture réelle n'est mesuré ici.

Les fichiers peuvent contenir des discussions privées complètes dans la limite
du fragment. Conserver les lots, snapshots et résultats dans un emplacement
privé ; aucun texte privé n'appartient aux exemples publics. La création demande
le mode `0600` sur les systèmes qui le supportent ; les ACL Windows et les
répertoires parents relèvent de l'appelant. Les contrôles de fichiers ne sont pas
un sandbox contre un propriétaire de système de fichiers hostile.

Code de sortie : `0` rapport produit dans le périmètre déclaré, même partiel ;
`2` entrée invalide/indisponible ou écriture refusée. Un zéro ne prouve ni
couverture complète, ni relation vérifiée. Le repli consiste à conserver les
catalogues, recherches et mémoires existants sans appeler ce pilote.

Pour raccorder les vrais historiques, la prochaine étape est un importateur
par source avec inventaire de couverture, puis un essai sur des cas évalués
indépendamment. Un graphe de connaissances peut contenir des cycles ; seules
les dépendances de travail destinées à un DAG doivent rester acycliques.
