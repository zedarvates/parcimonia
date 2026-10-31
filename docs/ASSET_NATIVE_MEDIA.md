# Pistes audio et vidéo observées avec ffprobe

Cette étape complète l'inspection par en-têtes : Parcimonia peut appeler
explicitement un `ffprobe` local pour relever les pistes rapportées, leurs codecs,
dimensions, fréquence audio, canaux et durées disponibles. Ces observations
produisent des propositions de tags avec des preuves par piste, compatibles avec
le catalogue et le journal de revue existants.

Un MP4 peut être uniquement audio. Une pochette intégrée peut être rapportée
comme une piste de type vidéo. Le profil conserve ces distinctions ; il ne
reconnaît ni les objets visibles, ni les paroles, ni le genre musical.

## Utilisation

`ffprobe` doit déjà être installé. Le paquet Python conserve ses dépendances
d'exécution vides ; aucun outil ou modèle n'est téléchargé automatiquement.

```bash
python -m tiberium_ai.asset_cli inspect clip.mp4 --source-id clip-001 --revision v1 > inspection.json
python -m tiberium_ai.asset_cli probe-media clip.mp4 --source-id clip-001 --revision v1 > observation.json
python -m tiberium_ai.asset_cli enrich-media inspection.json observation.json > enriched.json
```

`probe-media` choisit son démultiplexeur à partir des octets reconnus par
l'inspection d'en-tête, et non du suffixe. `--executable` permet de choisir un
exécutable local précis ; sinon, `ffprobe` est recherché dans `PATH`. `--timeout`
vaut 10 secondes par défaut, avec un maximum de 30. L'import d'un module ou
l'inspection initiale ne déclenchent pas le sondage natif.

`enrich-media` relit l'observation sauvegardée sans relancer l'outil. La source,
la révision, le nom et le SHA des octets doivent correspondre exactement à
l'inspection. La réponse JSON native est reparsée, son hash stdout vérifié et sa
projection comparée au contenu sauvegardé. Cela vérifie la cohérence de la
déclaration fournie, sans authentifier son exécution.

| Code de sortie | Sens |
| --- | --- |
| 0 | Observation terminée ou enrichissement produit |
| 2 | Entrée, lecture, argument ou contrat refusé |
| 3 | Observation indéterminée ou outil indisponible |
| 4 | Échec natif ou réponse inexploitable |

Un code zéro signifie que le sondage a produit une réponse conforme, ou que
l'enrichissement a été produit. Les champs indisponibles restent inconnus. Il ne
certifie ni la décodabilité de toutes les images/échantillons, ni la qualité du
fichier, ni un inventaire exhaustif des pistes.

## Formats admis et portée du sondage

| En-tête reconnu | Démultiplexeur forcé |
| --- | --- |
| WAV avec en-tête accepté par le lecteur existant | `wav` |
| FLAC | `flac` |
| Ogg | `ogg` |
| ISO-BMFF dans le profil MPEG/QuickTime ci-dessous | `mov` |

Pour ISO-BMFF, le profil accepte seulement les marques principales `isom`, `iso2`,
`mp41`, `mp42`, `M4A `, `M4V ` et `qt  ` (espaces conservés dans les trois dernières).
Les marques compatibles d'images AVIF/HEIF connues sont aussi refusées. Une marque
principale inconnue reste hors profil, sans appel natif. Cette restriction évite
notamment d'étiqueter une image AVIF comme vidéo sur la seule réponse de ffprobe.
Elle ne constitue pas une classification universelle de tous les fichiers BMFF.

La commande demande une sélection fermée de champs JSON, avec validation des
chaînes UTF-8. Elle force le protocole `file` et le démultiplexeur retenu. Pour
MOV, `enable_drefs` et `use_absolute_path` sont désactivés explicitement. Le fichier
source est copié dans un répertoire temporaire privé, sous un nom constant ;
le nom déclaré par l'appelant n'est pas passé comme chemin ou option natif.

Le sondage utilise `probesize=1048576`, `analyzeduration=1000000` et
`max_probe_packets=128`. Ce sont des budgets de sondage FFmpeg :
`analyzeduration` est une durée média en microsecondes, sans rapport direct avec
le délai mural ; le nombre de paquets est une limite de tampon de détection.
Ces options ne bornent pas à elles seules toutes les lectures, la mémoire ou
le CPU. Le sondage peut analyser des paquets et initialiser des décodeurs.

## Tags et inconnues

Le rapport enrichi garde le format, les indices de suffixe et les propositions
initiales, avec une nouvelle identité `asset-media-enrichment/1`. Les preuves
ajoutées lient le hash de l'observation complète et les indices des pistes.
Les tags restent `proposed`, en mode `shadow`, avec le statut global `partial`.

| Observation rapportée | Proposition ajoutée |
| --- | --- |
| Type de piste | `stream_type:<type>` |
| Codec disponible | `codec:<nom>` |
| Piste audio | `modality:audio` |
| Piste vidéo et `attached_pic=0` | `modality:video` |
| Piste vidéo et `attached_pic=1` | `modality:image`, `media_feature:attached_picture` |
| Piste vidéo sans flag de pochette | Pas de nouvelle modalité image/vidéo |
| Sous-titre | Type de piste conservé ; pas de modalité texte déduite |

`stream_type:video` reproduit le type technique rapporté, qui peut inclure une
pochette. La modalité proposée tient compte du flag. Elle ne démontre pas un
mouvement dans les images. Un sous-titre peut être une image bitmap ; son type
ne suffit donc pas à conclure à du texte extrait. Les indices de suffixe restent
séparés : un MP4 audio seul peut garder `modality_hint:video` lié au nom, sans
recevoir de proposition native `modality:video`.

La durée du conteneur et celle de chaque piste restent séparées, en secondes,
comme valeurs rapportées ou estimées par l'outil. Un champ absent ou `N/A` devient
`null`, jamais zéro par défaut ; une durée zéro effectivement rapportée reste
zéro. L'absence de piste rapportée ne prouve pas l'absence de contenu.

Les [snapshots de catalogue](ASSET_CATALOG_SNAPSHOTS.md) et le
[journal de revue](ASSET_TAG_REVIEW.md) réutilisent ce rapport. Une recherche de
tags acceptés demande toujours une décision applicable au rapport exact. Une
nouvelle observation, même avec la même projection, peut changer ses temps ou
sa provenance et invalider l'application d'une ancienne décision. Réutiliser
l'observation sauvegardée permet de reconstruire un enrichissement stable.

## Contrats et limites

API : `asset_media_probe.probe_asset_media(data, filename=..., source_id=...,
revision=..., executable=None, timeout_s=10, complete=True)`.
Elle renvoie `parcimonia.asset-media-observation/v1`, avec source, hash de requête,
profil, backend déclaré, identité observée de l'exécutable, statut, JSON natif
exact, projection, appels et limites. Une observation non terminée n'expose ni
JSON exploitable ni projection partielle.

`media_evidence.parse_ffprobe_json(payload, expected_demuxer=...)` est un parseur
pur. Il conserve les indices uniques et trie les pistes par index, sans les
renuméroter. Sa projection est fermée. Les sections non demandées ne sont tolérées
que sous leurs formes vides connues ; les contenus supplémentaires sont refusés.
Les nombres non finis, booléens à la place d'entiers, coercitions, clés dupliquées
et formes non couvertes sont refusés.

`asset_media_enrichment.enrich_asset_with_media(inspection, observation)` ne fait
aucune I/O et retourne un nouveau rapport. L'enveloppe d'inspection reste
inchangée ; les consommateurs autorisent explicitement la nouvelle identité.
Les preuves et métadonnées retiennent la source de chaque observation, sans
transformer les durées ou champs techniques en probabilités de qualité.

| Ressource | Borne |
| --- | --- |
| Source | 1 MiB complète ; préfixe non sondé |
| Exécutable haché | Fichier régulier d'au plus 64 MiB |
| Sortie du sondage | 64 KiB stdout, 32 KiB stderr |
| Prévol de version | 8 KiB par flux |
| JSON natif | 2 000 nœuds, profondeur 16, au plus 32 pistes |
| Délai demandé | Échéance commune, de plus de zéro à 30 secondes |

Le lanceur existant capture les flux avec des tampons bornés, sans shell ni entrée
interactive. L'échéance couvre identité, prévol, sondage, parsing et nettoyage ;
les opérations système bloquantes et le lancement du processus ne sont pas
interruptibles par ce code. Le nettoyage best-effort peut attendre jusqu'à 0,25 s
supplémentaire. Les descendants échappés peuvent survivre. Ce n'est ni une sandbox
OS, ni une limite mémoire native, ni une garantie absolue de durée murale.

Le protocole `file` ne confine pas l'exécutable au seul snapshot. Le hash avant et
après est une identité observée, sans authentification ou verrou atomique, et
n'atteste pas les bibliothèques chargées. Les observations fournies par un tiers
restent des déclarations non signées. Aucun modèle, transcription, reconnaissance
visuelle, lecteur interactif, reclassement physique ou gain de coût/vitesse mesuré
n'est ajouté.

## Reproduction

```bash
PYTHONPATH=src python examples/native_media_demo.py --kind wav
PYTHONPATH=src python examples/native_media_demo.py --kind audio-mp4
PYTHONPATH=src python examples/native_media_demo.py --kind video-mp4
PYTHONPATH=src python -m pytest -q
```

Les fixtures sont fabriquées pour la vérification. WAV est produit avec la
bibliothèque standard ; les deux MP4 sont générés par un `ffmpeg` déjà installé,
avec un appel borné et un répertoire temporaire. Cette génération appartient à
la démonstration et non à l'API de sondage. Les tests natifs sont optionnels si
les exécutables ou encodeurs requis manquent ; les tests protocolaires restent
indépendants de ces binaires. Voir le
[point de vérification](../wiki/ASSET_NATIVE_MEDIA_2026-10-31.md).

Sources primaires : [ffprobe](https://ffmpeg.org/ffprobe.html),
[formats et options de sondage](https://ffmpeg.org/ffmpeg-formats.html),
[protocoles](https://ffmpeg.org/ffmpeg-protocols.html).
