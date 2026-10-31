# Traces GPX : coordonnées, provenance et recherche

Parcimonia peut lire les positions déclarées dans un fichier GPX 1.1 complet,
proposer des tags de format et de contenu géographique, puis rechercher son
enveloppe dans le catalogue. Les preuves conservent le chemin de chaque point,
notamment son itinéraire ou son segment de trace. Cette lecture ne certifie pas
qu'un appareil GPS a réellement enregistré ces positions.

## Périmètre de la première lecture

Le profil `parcimonia.gpx-coordinate-profile/v1` traite les points isolés,
les points d'itinéraires et les points de segments de trace. Il reconnaît la
racine GPX 1.1 dans son namespace exact, sa version et la présence de `creator`.
Ce dernier est une déclaration du fichier, sans authentification.

| Objet GPX | Chemin standard lu |
| --- | --- |
| Point isolé | `/gpx/wpt` |
| Point d'itinéraire | `/gpx/rte/rtept` |
| Point de trace | `/gpx/trk/trkseg/trkpt` |

Les chemins des preuves ajoutent des indices commençant à 1, par exemple
`/gpx[1]/trk[1]/trkseg[2]/trkpt[1]`. L'ordre des points et les segments restent
identifiables. Aucun segment n'est relié automatiquement à un autre et aucune
distance, vitesse, durée ou géométrie de parcours n'est calculée.

Les points GPX déclarent deux attributs nommés `lat` et `lon`. La sortie les
présente dans l'ordre **longitude, latitude**, comme le filtre spatial existant :

```json
{"path":"/gpx[1]/wpt[1]","coordinates":[1.0,2.0]}
```

La latitude doit être comprise entre −90 et 90 inclus ; la longitude entre −180
inclus et 180 exclu. Les valeurs sont contrôlées comme décimaux exacts avant leur
conversion en nombres flottants. Si une longitude légale trop proche de 180
s'arrondit à 180 lors de cette conversion, le profil la refuse plutôt que de la
modifier silencieusement. Les sorties restent des approximations binaires,
sans qualification de précision géodésique.

Le champ `spatial` reprend le contrat existant : `crs: OGC:CRS84`, axes
longitude/latitude, degrés, nombre de positions et enveloppe
`[minlon,minlat,maxlon,maxlat]`. L'enveloppe est recalculée depuis les points lus.
`metadata/bounds` n'y contribue pas. Sans point standard, le nombre est zéro et
l'enveloppe `null`, même si le fichier déclare une enveloppe dans ses métadonnées.

Cette enveloppe min/max est conservatrice, notamment près de l'antiméridien.
Une recherche reste un candidat d'intersection d'enveloppes, sans test exact de
parcours ou d'identité de lieu. Elle peut donc retourner un fichier dont aucun
point ne se trouve dans le rectangle demandé, lorsque son enveloppe le traverse.

## Inspection et catalogue

Les commandes existantes sont réutilisées :

```bash
python -m tiberium_ai.asset_cli inspect trace.gpx --source-id trace-001 --revision v1 > report.json
python -m tiberium_ai.asset_cli search reports.json --tag format:gpx --bbox 0 0 4 4
```

`reports.json` doit contenir un tableau de rapports, comme dans le
[catalogue initial](ASSET_PERCEPTION.md). Un suffixe trompeur ne suffit pas à
établir le format ; le contenu XML reconnu est déterminant.

Le rapport utilise l'enveloppe `parcimonia.asset-inspection/v1` avec une identité
d'analyseur distincte : `asset-gpx-inspection`, version `1`. Son `input_hash`
inclut le profil GPX. Les rapports des autres formats conservent leurs identités
et calculs précédents. Le catalogue accepte explicitement cette troisième identité
versionnée, sans ouvrir son contrat à des analyseurs inconnus.

Tous les tags restent `proposed`, en mode `shadow`. Les propositions de format,
modalité et contenu GPX reposent sur la structure lue ; les tags de présence de
coordonnées et de CRS reposent sur les points effectivement extraits. Le rapport
reste `partial`, avec une limite explicite de validation du schéma GPX complet.

Le [catalogue sauvegardé](ASSET_CATALOG_SNAPSHOTS.md) peut sélectionner ce rapport,
comme les rapports texte ou OCR. Le [journal de revue](ASSET_TAG_REVIEW.md) peut
accepter ou rejeter ses tags. Une décision sur un rapport n'est pas transmise
automatiquement à une nouvelle révision ou à de nouvelles coordonnées. Avec un
filtre de tag, `catalog-search` utilise les tags acceptés par défaut ;
`--state proposed` expose les propositions non revues.

Les éléments `name`, descriptions et autres textes XML ne donnent pas lieu à
une reconnaissance sémantique de lieux ou à des sujets lexicaux à cette étape.
Les coordonnées d'extensions propriétaires ne sont pas promues en GPS standard.

## API, preuves et limites

`tiberium_ai.gpx_probe.probe_gpx(data, complete=True)` est une fonction pure,
sans accès à un chemin ou à un service. `inspect_asset` l'appelle dans sa chaîne
de détection, puis conserve la source, la révision et le hachage des octets.

- `gpx:structure` décrit le profil et la portée en octets du document fourni.
- `gpx:positions` contient les chemins et coordonnées standard dans leur ordre.
- Les métadonnées donnent les comptes structurels et les déclarations retenues,
  dont la version et `creator`.

Une erreur après reconnaissance de la racine GPX, notamment un point invalide
tardif ou une limite dépassée, ne conserve ni enveloppe ni liste partielle de
positions. Seule une observation de format accompagnée du motif de refus peut
rester. Si la racine GPX n'a pas pu être reconnue, le probe retourne `None` : la
détection générale peut alors conserver un indice de suffixe ou une lecture de
texte, sans localisation GPX. Un préfixe n'est pas analysé comme document GPX.

| Ressource ou syntaxe | Limite du profil |
| --- | --- |
| Source | Au plus 1 MiB, complète |
| Encodage XML | UTF-8, BOM UTF-8 facultatif, XML 1.0 |
| Éléments XML | Au plus 20 000, extensions comprises |
| Profondeur | Au plus 32, racine à profondeur 1 |
| Positions standard | Au plus 2 000 ; dépassement refusé en entier |
| Décimal de coordonnée | Au plus 128 caractères, chiffres ASCII, sans exposant |
| Déclaration `creator` | Au plus 4 096 caractères Unicode |

Les espaces XML peuvent entourer les nombres ; les espaces Unicode supplémentaires
ne sont pas acceptés comme syntaxe décimale. Les références XML numériques et
prédéfinies sont décodées normalement avant ce contrôle. Les déclarations DTD et
d'entités personnalisées sont refusées. Aucun accès n'est fait aux entités externes,
liens, `schemaLocation` ou ressources XInclude. Les sous-arbres d'extensions sont
ignorés pour la géométrie mais restent comptés dans les budgets XML.

Ce profil ne valide pas le XSD complet, toutes ses séquences, valeurs optionnelles
ou extensions. L'altitude, les horodatages, la précision GPS et les capteurs ne
sont ni extraits ni validés. Aucun référentiel vertical n'est déduit de `ele`.
Une réussite de lecture des coordonnées n'est donc pas un verdict de conformité
de tout le fichier. Les limites sont des budgets de données, sans sandbox OS ou
garantie de durée murale. Aucun modèle ou géocodage n'est appelé et aucun gain de
performance n'est mesuré.

## Reproduction

```bash
PYTHONPATH=src python examples/gpx_catalog_demo.py
PYTHONPATH=src python -m pytest -q
```

La démonstration utilise des positions inventées, une enveloppe déclarée trompeuse
et un point d'extension ignoré. Elle vérifie l'enveloppe calculée, les chemins de
segments, la revue, le catalogue, puis le refus d'un point standard invalide tardif.
Elle ne lit pas de trajet personnel. Voir le
[point de vérification](../wiki/ASSET_GPX_2026-10-31.md).

Références primaires : [documentation GPX 1.1](https://www.topografix.com/GPX/1/1/),
[XSD officiel](https://www.topografix.com/GPX/1/1/gpx.xsd),
[interface Python Expat](https://docs.python.org/3/library/pyexpat.html).
