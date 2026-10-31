# Vérification — pistes audio et vidéo natives — 2026-10-31

Objectif : compléter les en-têtes de médias par les pistes, codecs et durées
rapportés par un outil local, puis proposer des tags avec preuves par piste et
revue. Proposition empilée sur la PR #26, tête
`27d847f67920f7ea07e72cd0bdc3191c2d1bf655`, sans fusion ni activation.

## Réalisation

- Parseur JSON ffprobe strict, projection fermée, indices de pistes conservés,
  inconnues explicites, limites de taille, profondeur et nombre de pistes.
- Adaptateur natif explicite : snapshot privé complet, démultiplexeur forcé
  depuis l'en-tête, prévol de version, identité binaire observée avant/après,
  capture bornée et échéance partagée. Les primitives natives existantes sont
  réutilisées, sans changer le lecteur OCR/PDF.
- Enrichissement sans exécution native : liaison exacte à la source et au JSON
  sauvegardé, reproduction de la projection, preuves et tags proposés. Nouvelle
  identité `asset-media-enrichment/1` explicitement autorisée par le catalogue.
- Commandes `probe-media` et `enrich-media`, reprise des catalogues, journal et
  recherche existants. Les fichiers sources restent inchangés.

## Validation locale

**2 194 tests passent sur Python 3.12.14** : les 1 846 tests de la base et
348 nouveaux cas, répartis en 134 parseur, 68 adaptateur, 101 enrichissement,
20 intégration/démonstration et 25 CLI. Aucun test n'a été ignoré ici. Les
exécutables installés ont réellement servi aux fixtures natives. Un avertissement
de dépréciation provient du plugin pytest `anyio` de l'environnement, sans échec.

Les tests vérifient les erreurs de transport, sorties plafonnées, échéances,
nettoyage, changements d'identité, captures incomplètes, raw JSON/hash/projection,
types stricts et champs fermés. Ils couvrent aussi l'isolation des objets, les
preuves de chaque piste, l'agrégation de codecs partagés, la recherche et le cycle
persisté d'acceptation/invalidation après changement de rapport ou d'observation.

Les [observations natives conservées](ASSET_NATIVE_MEDIA_SMOKE_2026-10-31.json)
viennent uniquement de fixtures fabriquées :

| Fixture | Résultat réel avec ffprobe 7.1.5 | Recherche proposée |
| --- | --- | --- |
| WAV PCM, 3 244 octets | Audio `pcm_s16le`, 8 kHz, 1 canal, durée rapportée 0,2 s | 1 résultat audio |
| MP4 audio seul, 867 octets | Audio `aac`, durée rapportée 0,2 s, aucun tag natif de modalité vidéo | 1 résultat audio |
| MP4 vidéo seule, 880 octets | Vidéo `mpeg4`, flag de pochette faux, durée rapportée 0,2 s | 1 résultat vidéo |

WAV est fabriqué avec la bibliothèque standard ; les deux MP4 sont générés par
le `ffmpeg` installé, depuis des échantillons WAV ou un cadre RGB inventés, dans
un temporaire privé et un appel borné. Aucun média personnel ou modèle n'a été
téléchargé. Ces résultats ne qualifient pas la qualité des médias, les performances
ou les codecs sur d'autres fichiers/builds.

## Revue indépendante et correction

Défaut concret reproduit puis corrigé : une image AVIF synthétique de 323 octets
était admise par l'en-tête ISO-BMFF et rapportée par ffprobe comme piste vidéo,
codec AV1, `attached_pic=0`. Elle aurait donc reçu un tag vidéo trompeur. Le profil
restreint désormais les marques principales BMFF admises et refuse aussi les
marques compatibles connues d'images. Le témoin AVIF retourne maintenant
`indeterminate`, raison `unsupported_bmff_brand`, avec zéro appel natif.
Les variantes standard/extended-size et les marques compatibles sont testées.

La contre-revue a aussi exécuté un MP4 audio/vidéo et un FLAC avec couverture PNG :
audio/vidéo sont proposés pour le premier ; image attachée et audio, sans modalité
vidéo, pour le second. L'absence de flag ne crée pas de nouvelle modalité vidéo,
et une piste de sous-titres ne devient pas du texte extrait.

L'oracle de parseur a exploré 368 mutations : 335 refusées par `ValueError`,
33 projections admises conservant leurs invariants, sans autre exception.
Les oracles de liaison ont refusé source divergente, booléens substitués aux
entiers, captures incomplètes, SHA divergent et projection altérée. Une
observation dont seul le temps change n'hérite pas de l'acceptation précédente.
Le témoin de 32 pistes compte 1 141 nœuds JSON et traverse le validateur partagé
limité à 20 000 nœuds. Aucun autre défaut reproductible n'a été identifié dans
le périmètre relu.

## Reproduction et limites

```bash
PYTHONPATH=src python examples/native_media_demo.py --kind wav
PYTHONPATH=src python examples/native_media_demo.py --kind audio-mp4
PYTHONPATH=src python examples/native_media_demo.py --kind video-mp4
PYTHONPATH=src python -m pytest -q
```

Guide : [ASSET_NATIVE_MEDIA.md](../docs/ASSET_NATIVE_MEDIA.md). Les tests natifs
sont optionnels si binaires/encodeurs manquent ; les tests de protocole ne
dépendent pas de leur présence. L'observation peut initialiser des décodeurs,
sans valider toutes les images/échantillons. Les durées restent rapportées ou
estimées, les pistes non exhaustives sous budgets, les déclarations non signées.
Une restriction au protocole `file` ne fournit pas de confinement filesystem.
Le hash binaire n'authentifie pas son origine ou ses bibliothèques. L'échéance et
le nettoyage best-effort ne constituent pas une garantie murale ou mémoire.

Pas de transcription, reconnaissance d'objets, lecture interactive, reclassement
de fichiers ou gain de coût/vitesse mesuré. Repli : garder l'inspection initiale
et omettre les nouvelles commandes. Aucune fusion ou activation automatique.
