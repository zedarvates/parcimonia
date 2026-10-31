# Revue des sources reelles : attention et nouveaute

Increment du 8 octobre 2026, apres le [pilote synthetique](SOURCE_TRIAGE_PILOT.md).
Il prepare une revue humaine hors reseau, avec captures verifiees et labels
vierges, puis controle les conditions d'une comparaison tenue a l'ecart.

## Dossier disponible

Le dossier local courant est `runs/source-triage/review-20261008-v3/` :

- `review.html` : formulaire autonome, sans serveur ni requete reseau ;
- `review-packet.json` : quatorze cas, textes complets, contexte et candidats ;
- `review-template.json` : annotations JSON vierges, utilisables hors formulaire ;
- `capture-provenance.json` : revisions, chemins, hashes et origine des captures ;
- `comparison-readiness.json` : controles et raisons de non-preparation ;
- `manifest.json` : hashes des livrables et bilan de preparation.

Les quatorze fichiers viennent des captures publiques deja presentes dans
`runs/research-clef-gev-20261007/`, consultees le 7 octobre. Ils appartiennent a
Cloudflare/clef, Cloudflare/clef-flash et autotrust/GEV-26B-Decide. Les revisions
Git de quarante caracteres, URLs et hashes sont controles contre le manifeste
local ; 111 080 octets de source ont ete relus. Aucun code externe n'a ete importe
ou execute. Les dates de capture ne deviennent pas des dates de publication.

Il s'agit de sources publiques reelles figees, principalement anglophones,
et d'un objectif de revue explicite pour Parcimonia. Ce choix de trois familles
est un premier lot de protocole, pas un echantillon representatif de la veille.
Les textes et exports complets restent dans `runs/`, ignore par Git.

## Preparer un autre dossier

```powershell
rtk proxy .venv/Scripts/python.exe examples/prepare_source_review.py --manifest runs/research-clef-gev-20261007/sources-manifest.json --output-dir runs/source-triage/nouvelle-revue
```

`--context` peut fournir un JSON de contexte de confiance avec les champs du
contrat attention : objectif, contraintes, revision, valeurs et besoins declares.
Le contexte par defaut est l'objectif de cette experience, pas une capture
historique d'une action utilisateur. Ni le materiel ni le cout d'un modele ne
sont inventes. La recherche lexicale propose deux candidats par cas ; leurs
relations restent non etablies jusqu'a la revue. Ces candidats sont des documents
retrouves dans le meme snapshot, pas une preuve de connaissance anterieure de
l'utilisateur. Une future mesure de veille devra declarer son cutoff temporel.

La lecture est bornee a 32 fichiers, 64 KiB par fichier et 1 MiB au total.
Le manifeste lui-meme est borne a 128 KiB. Un hash ou nombre d'octets incompatible,
une revision non figee, une URL incoherente ou un chemin echappe invalide la
preparation. Les dossiers de sortie doivent rester sous `runs/` et etre nouveaux.
Une absence de `manifest.json` de sortie signale une preparation incomplete.

## Annotation hors ligne

Le formulaire montre le contenu capture, ses references, l'objectif et les
textes candidats. Aucun avis du pilote ou du backend n'est affiche. Il contient :

- traitement attendu : traiter, reporter, ecarter de la file active, contexte
  requis ou non etabli ;
- necessite de conserver la source : oui, non ou non etablie ;
- langue, groupe d'evenement et confirmation de revue de provenance ;
- relation avec chaque candidat : doublon, mise a jour, contradiction, nouveaute
  relative ou non etablie ;
- identite de l'annotateur, justification et completion explicite.

La sauvegarde locale est liee a l'identite du paquet. Import/export utilise JSON.
L'import verifie paquet, hashes de cas et identites de candidat ; le finaliseur
Python constitue le controle de contrat faisant autorite. Une modification du
texte, contexte ou candidat ne peut pas reutiliser silencieusement une annotation.
L'export ne reattribue pas une revue a un nouvel annotateur simplement parce
qu'il ouvre le dossier. Les anciens exports et les captures originales restent
intacts. Une source selectionnee comme protegee ne peut pas etre annotee pour
ecartement ; une information requise ne peut pas etre etiquetee pour ecartement.

Une identite saisie et une case cochee ne prouvent pas une annotation humaine
independante. Le module valide les declarations et leur coherence, puis conserve
`independent_labels_established=false`. L'independance et la qualite doivent etre
etablies par le protocole d'evaluation et des issues verifiees. Des labels
explicitement incertains sont conserves ; ils ne deviennent pas des labels negatifs.

## Finaliser une revue effective

```powershell
rtk proxy .venv/Scripts/python.exe examples/finalize_source_review.py --packet runs/source-triage/review-20261008-v3/review-packet.json --review chemin-vers-export.json --output-dir runs/source-triage/nouvelle-finalisation
```

Par defaut, une revue incomplete est refusee avant creation du dossier.
`--allow-partial` permet seulement d'enregistrer une revue partielle et sa
non-preparation ; il ne cree pas une evaluation. Les schemas interdisent les
champs de prediction dans les annotations. L'absence d'annotateur,
de justification, de revue de provenance ou de relation explicite invalide la
completion. Les labels sont lies au hash du cas de depart.

Apres completion, les lignages, contenus partages, sources candidates communes
et groupes d'evenements forment un graphe conservateur. Le split reutilise
`freeze_context_review_split` et garde ensemble ses composantes et les doublons
normalises. Les hashes du split couvrent les cas finaux, annotations et affectation
incluses. La porte recalcule les groupes pour detecter une fuite ou modification
d'affectation, meme apres un recalcul des hashes de cas.

Si les liens reunissent tout le dossier, le statut devient
`no_source_disjoint_split`. Aucun groupe n'est artificiellement separe pour
obtenir un test. La barre de vingt cas de test etiquetes est un minimum de pilote,
pas une certification. Ce lot de quatorze cas ne peut donc pas ouvrir cette porte
a lui seul, meme apres annotation complete ; il faut diversifier et agrandir
les sources, avec un protocole de situations et de connaissances preexistantes.

## Verification et etat actuel

- Preparation effective : quatorze cas, trois lignages declares, zero revue humaine.
- Porte reelle : `human_review_incomplete`, `split_not_frozen`,
  `insufficient_labelled_heldout`. Aucun split, metrique de qualite ou cout renseigne.
- Tests Python : captures alterees, budgets, identites, inconnus, revue incomplete,
  annotations incoherentes, groupes transitifs, hashes finaux et affectations.
- Controle Chromium isole : desktop 1366 x 900 et mobile 390 x 844, captures
  inspectees, absence de debordement horizontal, import/export et telechargement
  reels, persistence locale, aucune erreur de page ou requete externe.
- Les annotations du controle navigateur sont des fixtures explicites dans
  `runs/source-triage/browser-checks-20261008-v2/`, jamais importees au dossier reel.
- Les dossiers HTML initial et v2 sont conserves ; v3 contient la correction
  de retour a la ligne des references longues sur mobile et le script verifie.
- Aucun appel de modele, collecte nouvelle sur Internet, activation de route,
  modification des signatures historiques ou service partage redemarre.

La prochaine action est la revue des quatorze sources, puis un lot plus diversifie
et source-disjoint. Les captures appariees des backends viendront lorsque la porte
et leur disponibilite seront etablies ; un backend indisponible reste absent,
et les reponses injectees ne le remplacent pas dans une mesure reelle.
