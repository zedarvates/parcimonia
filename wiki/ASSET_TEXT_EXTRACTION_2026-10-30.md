# Vérification — extraction locale du texte — 2026-10-30

Objectif : prolonger la perception/classification des fichiers par un premier
texte extrait localement, puis des sujets lexicaux attribués aux mots OCR ou aux
pages PDF. Cette proposition est empilée sur la PR de revue des tags #23, tête
`406cdd3ee91df4a7ec1fad9483cb37985859fdab`, sans fusion ni activation.

## Réalisation

- Lanceur natif sans shell, flux bornés, échéance monotone partagée et arrêt
  best-effort ; aucune promesse de sandbox OS ou de délai mural absolu.
- Adaptateurs explicites Tesseract PNG/JPEG et pdftotext PDF ; snapshot privé,
  source complète exigée, identité du binaire observée avant/après, pas de
  téléchargement ou de repli implicite.
- Parseurs stricts TSV OCR et texte PDF, plages Unicode, boîtes et pages,
  scores OCR non calibrés et couverture documentaire non établie.
- Enrichissement sans relancer l'outil, hash du rapport d'extraction exact,
  liaison à l'inspection initiale, tags proposés et revue existante.
- Deux commandes CLI, un démonstrateur et un guide :
  [ASSET_TEXT_EXTRACTION.md](../docs/ASSET_TEXT_EXTRACTION.md).

## Validation locale

Python 3.12.14 : **1 571 tests passent**, dont les 1 233 tests de la base et
338 nouveaux cas : 53 lanceur, 78 parseurs, 56 adaptateur, 127 enrichissement,
22 CLI et 2 intégrations natives. Un avertissement de dépréciation vient du
plugin pytest `anyio` de l'environnement, sans échec de test.

Les tests de protocole fabriquent les sorties natives ; ils ne mesurent pas la
qualité d'un OCR. Les deux tests d'intégration sont optionnels si les binaires
ou la langue `eng` ne sont pas installés. Ils ont réellement tourné ici.

Les deux démonstrations natives ont lu `PARCIMONIA ROBOT GARDEN 2026` dans des
fichiers fabriqués pour la vérification, sans données personnelles :

| Outil réellement présent | Résultat | Attribution | Recherche |
| --- | --- | --- | --- |
| Tesseract 5.5.0, langue eng | Texte attendu exact | 4 boîtes de mots, image sélectionnée | `topic:robotique` retrouvé |
| pdftotext 25.03.0 | Texte attendu avec nouvelles lignes et séparateur de page | Page 1 renvoyée, pages 1 à 3 demandées | `topic:robotique` retrouvé |

L'[observation JSON](ASSET_TEXT_EXTRACTION_NATIVE_SMOKE_2026-10-30.json) conserve
les hachages de fixtures, les versions et identités observées des exécutables,
les mesures et le résultat de recherche. Ces temps sont des observations
ponctuelles, sans comparaison de performance ni qualification générale.

Revue indépendante : deux défauts reproduits et corrigés. Un `backend.id`
non textuel est refusé par `ValueError`. Le texte extrait qui commence par
`glTF`, `fLaC` ou `%PDF-` est traité directement par le lexique partagé, sans
redétection de format ; six régressions PDF/OCR vérifient aussi les offsets
Unicode et la preuve de page ou de zone. Les tests CLI vérifient un parcours
persisté jusqu'à l'acceptation, puis l'invalidation après une extraction modifiée.

## Reproduction et limites

```bash
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python examples/native_text_demo.py --backend tesseract
PYTHONPATH=src python examples/native_text_demo.py --backend pdftotext
```

Pas de reconnaissance d'objets, transcription audio, lecture vidéo/3D ou
reclassement de fichiers. Pas de qualité qualifiée sur les fichiers de
l'utilisateur, de poids OCR attestés ni de gains mesurés. Une extraction vide
ne démontre pas une absence. Les déclarations de provenance et les décisions
ne sont pas signées. Toute nouvelle extraction, même au texte identique, peut
changer le hash par ses temps observés : réutiliser l'enregistrement sauvegardé
pour reconstruire un rapport stable. Le nettoyage best-effort ne garantit pas
l'arrêt de descendants échappés. Le guide décrit ces limites et les budgets.

Repli : conserver l'inspection initiale et le catalogue de propositions ; ne pas
appeler les nouvelles fonctions ou commandes. Aucune modification des assets
sources et aucune activation automatique du routage.
