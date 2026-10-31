# Perception, classification et recherche des fichiers

Extension disponible : [extraction locale du texte](ASSET_TEXT_EXTRACTION.md)
avec OCR PNG/JPEG et texte PDF, puis tags lexicaux liés aux zones ou pages et
au journal de revue. Les limites ci-dessous décrivent l'inspection initiale.

Les [snapshots de catalogue](ASSET_CATALOG_SNAPSHOTS.md) permettent ensuite de
sauvegarder une sélection de ces rapports, de remplacer une révision précise et
de rechercher les tags avec leur état de revue.

La [lecture GPX 1.1](ASSET_GPX.md) ajoute les positions déclarées des points,
itinéraires et segments de trace, avec provenance et enveloppe 2D recalculée.

Le [sondage natif audio/vidéo](ASSET_NATIVE_MEDIA.md), explicitement demandé,
complète les en-têtes par des pistes, codecs et durées rapportés par ffprobe,
avec preuves par piste et revue des tags.

La [lecture du corps PLY](ASSET_PLY_BODY.md) contrôle les positions locales,
indices de faces et paramètres Gaussian des enregistrements disponibles, puis
ajoute leurs agrégats, preuves et tags candidats.

L'[inventaire GLB](ASSET_GLB_RESOURCES.md) lit les chunks et les déclarations
core de buffers/images, avec leurs plages et références. Les URI externes
restent non vérifiés ; aucun contenu lié ou rendu n'est ouvert.

L'[audit d'attentes explicites](ASSET_EXPECTATIONS.md) compare ces rapports à
des exigences choisies : correspondance, contradiction, inconnu ou rapport
manquant. L'absence d'une proposition n'est pas une preuve d'absence du contenu.

Objectif : retrouver des fichiers par leur format, leurs caractéristiques, leur
contenu proposé et leur localisation, puis préparer leur classement. Un même
asset pourra relever de plusieurs modalités : une vidéo peut contenir image,
audio, texte et coordonnées. Chaque modalité nécessite sa propre preuve.

Cette première version réalise une inspection déterministe et un catalogue de
tags proposés. Elle ne reconnaît pas encore des objets dans des pixels, des
paroles, une scène 3D ou un lieu représenté. Les métadonnées constatées, les
indices lexicaux et les futures inférences de modèles restent distincts.

## Périmètre actuel et étapes suivantes

| Famille | Première version | Extraction ou perception suivante à qualifier |
| --- | --- | --- |
| Texte et documents | UTF-8, JSON, vocabulaire fourni par l'appelant ; PDF et ZIP par signature seulement | Langue, thèmes sémantiques, OCR, extraction PDF/Office |
| Images | En-têtes PNG, GIF, JPEG ; dimensions lorsque disponibles | Objets, textures, scènes, texte présent dans l'image |
| Vidéo | Conteneur ISO-BMFF et Ogg ; suffixe vidéo conservé comme indice | Pistes réelles, images clés, segments, sous-titres et événements |
| Sons | WAV PCM : métadonnées déclarées ; FLAC par signature | Parole, transcription, musique, événements sonores |
| 3D | Profil GLB des chunks et ressources core ; profil PLY des sommets/faces ; structure glTF JSON déclarée | Géométrie glTF décodée, extensions, unités, textures, animation et reconnaissance après rendu autorisé |
| Gaussian splatting | Candidat de paramètres PLY après lecture des records compatibles | Qualification des paramètres, rendu, formats splat/ksplat/spz et variantes |
| Code | Rôles et motifs nommés Python des analyseurs existants | Autres langages et similarité fonctionnelle vérifiée |
| Géographie | GeoJSON et profil GPX 1.1 : coordonnées, ordre des axes, CRS et enveloppe | KML, GeoTIFF, Shapefile, reprojection et recherche géométrique exacte |

« Gaussian splatting » est l'interprétation provisoire du terme oral reçu.
Le nom reste à confirmer ; son support proposé ne
suppose pas qu'un fichier PLY quelconque soit une scène gaussienne.

Les suffixes des formats non décodés donnent uniquement `format_hint` et
`modality_hint`. Un MP4 n'atteste pas la présence d'une piste vidéo, ni Ogg celle
d'une piste audio. Une coordonnée x/y/z dans un PLY ne devient jamais du GPS.
Une paire de nombres dans un JSON générique n'est pas localisée automatiquement.

## Utilisation

Après l'installation de développement du dépôt, depuis sa racine :

```powershell
python -m tiberium_ai.asset_cli inspect image.png --source-id image-001 --revision v1
python examples/asset_catalog_demo.py --summary
```

L'exemple construit en mémoire sept fichiers fictifs : image, texte, son, code,
GeoJSON, points PLY et conteneur vidéo. Les coordonnées sont synthétiques.
La sortie complète est un tableau JSON de
rapports ; elle peut être donnée à la commande de recherche :

```powershell
python -m tiberium_ai.asset_cli search catalogue.json --tag modality:image
python -m tiberium_ai.asset_cli search catalogue.json --tag topic:robotique
python -m tiberium_ai.asset_cli search catalogue.json --bbox -1 -1 1 1
```

`catalogue.json` doit être un tableau de rapports d'inspection existants. La CLI
émet du JSON sur stdout, sans écrire de fichier de catalogue ou de métadonnées.
Une recherche sans filtre liste les rapports dans un ordre stable.

Le vocabulaire texte est fourni par un fichier JSON explicite, par exemple
`{"robotique": ["robot", "robotique"], "jardin": ["jardin"]}`, avec l'option
`inspect --topics vocabulaire.json`. Un mot présent produit un indice lexical,
pas une preuve de sens : « pas un robot » peut proposer le même thème. Aucun
score lexical n'est transformé en confiance mesurée.
Un mot coupé au bord droit d'un préfixe n'est pas proposé : sa frontière droite
doit être observée, ou l'échantillon doit être complet.

Codes de sortie : `0` signifie rapport produit, `2` entrée ou lecture refusée,
`3` inspection indéterminée. Une inspection partielle reste explicite dans le
rapport ; un code zéro ne certifie ni la validité complète du fichier ni sa qualité.

## Contrats et provenance

API : `tiberium_ai.asset_inspection.inspect_asset(data, filename=...,
source_id=..., revision=..., complete=True, total_bytes=None, topic_terms=None)`.
Elle reçoit des octets, sans accès à un chemin ni à un service.

Le rapport `parcimonia.asset-inspection/v1` comporte :

- l'identité et la révision déclarées de la source ;
- l'empreinte de l'entrée effective, dont la politique de vocabulaire ;
- la portée de l'échantillon et son SHA-256 ;
- le format observé, l'indice de suffixe et leurs désaccords ;
- les métadonnées, modalités et preuves correspondantes ;
- des tags `{namespace, value, status, basis, evidence_refs}` ;
- les données spatiales éventuellement extraites et les limites restantes.

Tous les tags ont le statut `proposed`. Leur `basis` distingue notamment
signature, en-tête, structure analysée, règle de code, indice de suffixe et
indice lexical. La preuve précise les octets, lignes ou caractères concernés.
Les caractères d'un indice lexical sont comptés en points de code Unicode.
Les identités et empreintes établissent des liens de calcul, pas une origine
authentifiée ou la vérité des déclarations du fichier.

Le [journal de revue](ASSET_TAG_REVIEW.md) peut conserver séparément les choix
acceptés, rejetés ou réinitialisés et les utiliser dans une recherche dédiée.
Il ne modifie pas ces propositions et ne transfère pas les choix à une nouvelle
révision ou à un rapport d'analyse changé.

L'échantillon est limité à 1 Mio. Pour un fichier plus grand, la CLI lit un
préfixe et conserve la taille observée ; `content_sha256` reste `null`. Deux
préfixes identiques ne prouvent pas que deux fichiers entiers sont identiques.
Un en-tête incomplet dans un préfixe ne prouve pas un fichier tronqué. Une
métadonnée absente de l'échantillon reste inconnue.

La CLI accepte seulement un fichier régulier explicite. Elle refuse liens,
répertoires et périphériques et les changements qu'elle observe pendant la
lecture. Ces vérifications ne sont pas un verrou ni une garantie d'immuabilité
future. Aucun contenu référencé par un glTF n'est suivi ou téléchargé.

## Recherche et géographie

API : `tiberium_ai.asset_catalog.search_asset_reports(reports, tags=None,
bbox=None, limit=50)`. Elle utilise jusqu'à 256 rapports fournis, sans base de
données ou index externe. Les tags sont comparés exactement, avec casse, et
plusieurs filtres sont combinés par ET. `count` indique le nombre retourné,
`truncated` des résultats supplémentaires. Les résultats gardent la source,
la révision, l'empreinte et l'état consultatif de leur provenance.

Les identités dupliquées `(source.id, source.revision)`, incohérences de portée,
tags sans preuve connue et structures invalides sont refusées. Ce contrôle ne
relit pas les fichiers et ne vérifie pas la vérité des rapports fournis.

GeoJSON est traité selon RFC 7946 : CRS `OGC:CRS84`, ordre longitude/latitude,
degrés décimaux ; la troisième coordonnée éventuelle est une hauteur en mètres
par rapport à l'ellipsoïde WGS84. Les anciens membres `crs` sont refusés, sans
reprojection implicite. L'enveloppe fournie dans le JSON est ignorée et
recalculée depuis les positions. Une erreur dans une géométrie ne laisse pas
fuiter une localisation partielle présentée comme valide.

Le filtre `--bbox ouest sud est nord` teste l'intersection d'enveloppes
conservatrices. Le résultat est `envelope_overlap_candidate`, pas une preuve
d'intersection géométrique ou d'identité de lieu. Les enveloppes traversant
l'antiméridien ne sont pas optimisées ; les requêtes qui l'enjambent ne sont
pas prises en charge. Un CRS inconnu ne matche pas ce filtre.

## Réutilisation et suite R&D

Le code utilise `source_scan`, `source_role` et `pattern_rules` déjà présents
dans Parcimonia. Les motifs restent des indicateurs nommés, pas un jugement
global sur le logiciel. Le schéma du diagnostic des PR #20/#21 n'est pas modifié
et cette branche ne dépend pas de leur fusion.

L'inspection de copies locales de Botte Secrète a distingué des briques réutilisables : mémoire
de rapports de qualité d'assets, ingestion et classification lexicale. Son
ancien `media_loader` comprend des sorties simulées d'OCR, transcription et
labels ; ces sorties et ses constantes d'économie ne qualifient pas de perception.
Le codec `vector_protocol` ne constitue pas un espace d'embeddings multimodaux.

Les prochaines étapes sont :

1. Qualifier chaque extracteur sur de vrais fichiers autorisés et des exemples
   réservés : formats trompeurs, préfixes, coordonnées ambiguës, labels erronés.
2. Ajouter des adaptateurs explicitement choisis : décodeurs et outils natifs,
   puis petits modèles locaux si une mesure justifie leur usage. Conserver version,
   coût inconnu ou mesuré, erreur, abstention et segments/regions de preuve.
3. Séparer tags proposés, acceptés et rejetés avec provenance de la décision ;
   relier la qualité des assets à ses contrôles propres.
4. Ajouter un index persistant et la recherche sémantique après qualification.
   Une similarité visuelle ou sonore ne prouve pas un doublon exact.
5. Préparer ensuite des propositions de classement ou de sidecars avec retour
   arrière, sans modifier l'identité ni perdre les tags d'origine.

Cette version ne lance ni modèle, OCR, transcription, lecteur multimédia,
rendu 3D, géocodage ni déplacement. Les routes d'exécution existantes restent
inchangées. Aucun gain de vitesse, de coût ou de tokens n'est mesuré.

## Sources primaires des formats

- [RFC 7946 : GeoJSON](https://www.rfc-editor.org/rfc/rfc7946).
- [Khronos : glTF 2.0 et conteneur GLB](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html).
- [Graphdeco Inria : propriétés PLY exportées](https://github.com/graphdeco-inria/gaussian-splatting/blob/main/scene/gaussian_model.py).
