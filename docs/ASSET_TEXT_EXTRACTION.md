# Texte extrait, preuves et tags proposés

Cette étape permet à Parcimonia de proposer des tags à partir du texte réellement
renvoyé par un outil local : OCR d'une image PNG/JPEG avec Tesseract, ou texte
incorporé dans un PDF avec `pdftotext`. Un vocabulaire explicite relie les mots
observés aux sujets recherchés. Un tag reste une proposition jusqu'à une décision
dans le [journal de revue](ASSET_TAG_REVIEW.md).

Par exemple, `{"robotique": ["robot"]}` permet de proposer `topic:robotique`
quand le texte extrait contient le mot « ROBOT ». La preuve conserve sa plage de
caractères et les boîtes des mots OCR ou les pages PDF concernées. Cela ne prouve
pas la présence visuelle d'un robot : le mécanisme reconnaît une occurrence
textuelle, avec les erreurs possibles de l'extracteur.

## Exécution explicite

Le paquet Python conserve ses dépendances d'exécution vides. Les exécutables et,
pour Tesseract, la langue demandée doivent déjà être installés. Aucun modèle,
paquet ou service distant n'est téléchargé ou appelé par cette étape. Importer le
module et lancer l'inspection initiale ne déclenchent aucune extraction.

```bash
python -m tiberium_ai.asset_cli inspect image.png --source-id image-001 --revision v1 > inspection.json
python -m tiberium_ai.asset_cli extract-text image.png --source-id image-001 --revision v1 --backend tesseract --language eng > extraction.json
python -m tiberium_ai.asset_cli enrich-text inspection.json extraction.json --topics topics.json > enriched.json
```

`topics.json` est un objet JSON de labels associés à des listes de termes
littéraux. Les règles lexicales sont celles de l'inspection initiale : limites
de mots Unicode, comparaison insensible à la casse, première occurrence par
sujet. Les préfixes comme `glTF`, `fLaC` ou `%PDF-` présents dans le texte extrait
restent du texte ; ils ne déclenchent pas une seconde détection de format.

Pour un PDF, remplacer le backend par `pdftotext` et, si nécessaire, choisir
`--max-pages 3` (entre 1 et 8). Le traitement commence à la première page.
`pdftotext` ne fait pas d'OCR : un PDF scanné peut produire une extraction vide.
L'absence de texte extrait ne démontre jamais l'absence de contenu.

`--executable` désigne facultativement un exécutable local précis ; à défaut,
le backend est recherché dans `PATH`. `--timeout` vaut 10 secondes par défaut,
avec un maximum de 30. La langue par défaut est `eng`. Une langue Tesseract
absente produit un échec explicite, sans repli vers une autre langue.

La CLI ne lit que des fichiers réguliers explicites et refuse les liens et
périphériques. Elle imprime le résultat JSON sur stdout. Les codes sont :

| Code | Sens |
| --- | --- |
| 0 | Rapport exploitable produit ; une extraction vide peut être terminée |
| 2 | Argument, lecture ou contrat de données invalide |
| 3 | Inspection indéterminée, extraction indéterminée ou outil indisponible |
| 4 | Échec de l'outil natif ou réponse native inexploitable |

## Contrats et attribution

`extract_asset_text(data, filename=..., source_id=..., revision=..., backend=...)`
dans `tiberium_ai.asset_text_extract` renvoie un rapport
`parcimonia.asset-text-extraction/v1`. Il contient notamment :

| Élément | Portée |
| --- | --- |
| Source, révision, nom et SHA-256 des octets | Liaison à l'échantillon complet fourni |
| Backend, version déclarée, chemin et SHA-256 de l'exécutable | Identité observée avant et après, sans authentification |
| Texte et plages de caractères | Coordonnées en points de code Unicode, fin exclusive |
| Boîtes OCR | `[gauche, haut, largeur, hauteur]` en pixels de l'image sélectionnée |
| Pages PDF | Numéro de page et plage dans le texte exact, séparateurs conservés |
| Appels natifs | Phase, code de retour, complétude, hachages stdout/stderr et temps observé |
| Couverture et limites | Image sélectionnée ou intervalle de pages demandé, document complet non établi |

Les scores Tesseract restent des valeurs natives entre 0 et 100 avec
`score_status: uncalibrated`. Ils ne deviennent pas des probabilités de justesse.
Les poids OCR ne sont pas attestés. Tesseract utilise ici son moteur OCR local
`--oem 1` ; le rapport enrichi ne conserve donc pas le `model_calls: 0` de
l'inspection par en-têtes. Il indique `model_calls: null` et comptabilise
séparément les deux appels natifs, version et extraction. `pdftotext` ne fait pas
d'inférence OCR et conserve `model_calls: 0`.

`enrich_asset_with_text(inspection, extraction, topic_terms=...)` dans
`tiberium_ai.asset_text_enrichment` ne lance aucun outil. Il exige une extraction
terminée, une source complète et une correspondance exacte de source, révision,
nom et hachage. Il vérifie la structure et la cohérence des plages/pages/boîtes.
Il ne peut pas authentifier une extraction fournie par un tiers ni vérifier
qu'un texte déclaré est fidèle à l'image d'origine.

Le résultat reprend l'enveloppe `parcimonia.asset-inspection/v1`, le format et les
observations initiales, avec une identité distincte
`{"id": "asset-text-enrichment", "version": "1"}`. Le catalogue accepte
explicitement ces deux identités versionnées ; les identités inconnues restent
refusées. Le résultat est `partial`, en mode `shadow`, avec des tags `proposed`.
Les mots ou pages utiles sont référencés par les tags, avec le hachage du rapport
d'extraction exact. Le texte complet reste dans le rapport d'extraction séparé.

## Revue et recherche

Ajouter `enriched.json` à un tableau JSON de rapports permet d'utiliser les
commandes de catalogue et de revue existantes :

```bash
python -m tiberium_ai.asset_cli review-init reviews-000.json
python -m tiberium_ai.asset_cli review-tag enriched.json reviews-000.json --tag topic:robotique --decision accept --actor local-reviewer --reason "Occurrence vérifiée dans la source" --event-id review-001 --expected-head none --out reviews-001.json
python -m tiberium_ai.asset_cli search-reviewed catalogue.json reviews-001.json --tag topic:robotique
```

Sans acceptation, la recherche avec tags validés ne renvoie pas le sujet proposé.
Le journal lie la décision au rapport enrichi entier. Un autre lexique, une
preuve modifiée ou une nouvelle extraction invalide cette application de la
décision ; l'historique reste conservé. Même une nouvelle extraction identique
en texte peut produire un rapport différent, notamment par les temps mesurés.
Réutiliser le fichier d'extraction enregistré permet de reconstruire le même
enrichissement et de garder une liaison stable. Les hachages assurent la
cohérence des objets, sans garantir l'identité du réviseur ni la vérité du tag.

## Budgets et limites

| Ressource | Limite de cette première étape |
| --- | --- |
| Source | 1 MiB complet ; un préfixe ne déclenche pas l'outil |
| Image | PNG/JPEG, dimensions connues, au plus 4 millions de pixels |
| Mots OCR | 512, avec refus du résultat entier si dépassé |
| PDF | Pages 1 à 3 par défaut, au plus 8 demandées |
| Sortie d'extraction | 256 KiB stdout et 32 KiB stderr |
| Prévol de version | 8 KiB par flux |
| Exécutable haché | Fichier régulier d'au plus 64 MiB |
| Délai | Échéance commune pour identité, prévol, extraction, validation et nettoyage |

Les sorties sont capturées avec des tampons bornés, sans shell et sans entrée
interactive. Dépassement, délai ou sortie incomplète ne deviennent pas du texte
exploitable. L'échéance est contrôlée autour des opérations locales ; le
lancement de processus et les opérations système bloquantes ne sont pas
interruptibles par ce code. Ce n'est pas une garantie de durée murale stricte.
Le nettoyage attend au plus 0,25 seconde supplémentaire par appel interrompu.
Sur POSIX, la terminaison du groupe de processus est tentée ; sur Windows, elle
cible l'enfant direct. Des descendants échappés peuvent survivre. Il n'y a pas
de sandbox OS, de limite mémoire native ni d'attestation de tous les fichiers
chargés par les outils. L'identité du binaire est observée, sans verrouillage
atomique entre hachage et exécution.

Le fichier source est copié dans un répertoire temporaire privé ; seul ce
snapshot est passé à l'outil. La source n'est pas réécrite. Cette étape ne produit
ni reconnaissance d'objets, ni transcription audio, ni analyse de vidéo/3D, ni
réorganisation automatique des fichiers. La qualité n'est pas qualifiée sur les
documents de l'utilisateur. Aucun gain de temps, coût ou tokens n'est mesuré.

## Reproduction

```bash
PYTHONPATH=src python examples/native_text_demo.py --backend tesseract
PYTHONPATH=src python examples/native_text_demo.py --backend pdftotext
PYTHONPATH=src python -m pytest -q
```

La démonstration utilise un PNG et un PDF fabriqués pour cet essai, contenant
`PARCIMONIA ROBOT GARDEN 2026`. Elle produit extraction, enrichissement et
recherche par sujet. Aucun fichier personnel n'est nécessaire. Les tests de
protocole utilisent des réponses synthétiques clairement attribuées ; les deux
tests d'intégration natifs sont exécutés si le binaire et, pour l'OCR, `eng` sont
disponibles. Sinon, ils sont explicitement ignorés. Voir le
[point de vérification](../wiki/ASSET_TEXT_EXTRACTION_2026-10-30.md).

Références des outils :
[Tesseract, sorties TSV et ligne de commande](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html),
[pdftotext, options de pages et sortie texte](https://manpages.debian.org/bookworm/poppler-utils/pdftotext.1.en.html).
