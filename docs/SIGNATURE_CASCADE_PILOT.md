# Pilote de cascade sur reponses capturees — 5 octobre 2026

Le cadre verbe/objet est execute sur les six paraphrases francaises du pilote
existant. Si sa probabilite de type est inferieure au seuil declare de 0.90,
la cascade consulte le lot complet de reponses Laya deja capture pour ce cas.
Le hash de l'entree et toutes les questions doivent correspondre exactement.
La comparaison controle aussi le schema, les cas et les identifiants de memoire.

```powershell
rtk .venv/Scripts/python.exe examples/signature_cascade_pilot.py runs/local-decision-pilot/laya-report.json --output runs/local-decision-pilot/cascade-replay-20261005.json
```

Le fichier de sortie est cree exclusivement ; choisir un nouveau nom pour une
nouvelle execution. Le pilote exporte les routes, compteurs et etapes par cas,
ainsi que la latence locale mesuree de chaque lot et les metriques de signature.

## Resultat local

- Six demandes et deux appels au repli.
- Quatre types corrects acceptes, comme le cadre seul sur ces six cas.
- Le repli capture n'augmente pas ici le nombre de types corrects acceptes.
- 872 tests locaux passent, dont les tests de budgets de cascade et de refus
  d'une capture portant un contrat de questions different.

L'origine est `fixture` : cas et etiquettes sont rediges pour le banc. Les temps
exportes mesurent le cadre, la validation et la lecture des reponses capturees.
Ils ne mesurent pas une nouvelle inference Laya et ne justifient aucune economie
de modele. Les champs du lot choisi restent ceux de son backend ; aucune fusion
par champ n'est effectuee. L'accord avec ces etiquettes n'autorise aucune action.

## Comparaison appariee du 7 octobre

Le pilote execute maintenant aussi la baseline sur les memes cas et exporte
`paired_comparison`. Ce bloc distingue les types corrects acceptes, les erreurs
acceptees et les abstentions, puis compte ameliorations, regressions et nouvelles
erreurs acceptees. Les traces sont appariees par hash et contrat de questions.

Resultat du replay Laya : quatre types corrects et deux abstentions dans les deux
bras ; zero amelioration, zero regression, zero nouvelle erreur acceptee.
Les deux replis concernent `paraphrase-05` et `paraphrase-07` et restent sous le
seuil. Le rapport local est `runs/local-decision-pilot/cascade-paired-20261007.json`.
Les dix tests cibles du backend et du pilote passent. Aucune nouvelle inference
n'est necessaire pour reproduire cette comparaison avec la capture existante.

## Comparaison avec Jeff capture

La capture `runs/jeff-pilot/report.json` respecte le meme schema, les memes
questions et les memes six cas. Commande executee le 7 octobre :

```powershell
rtk .venv/Scripts/python.exe examples/signature_cascade_pilot.py runs/jeff-pilot/report.json --arm jeff.sdk.qwen-0.8b@1 --output runs/jeff-pilot/cascade-paired-20261007.json
```

| Bras | Types corrects acceptes | Erreurs acceptees | Abstentions | Replis |
| --- | ---: | ---: | ---: | ---: |
| Cadre seul | 4 | 0 | 2 | 0 |
| Cadre puis Laya capture | 4 | 0 | 2 | 2 |
| Cadre puis Jeff capture | 5 | 0 | 1 | 2 |

Jeff resout `paraphrase-07` ; `paraphrase-05` reste une abstention. Les quatre
reponses acceptees du cadre sont conservees. Le gain observe est une reponse
sur six dans ce corpus fixture ; il n'etablit pas un gain sur les demandes
reelles. Le pilote conserve desormais le SHA-256 exact du fichier source dans
chaque nouveau rapport, en plus du hash du corpus. Les latences restent celles
du replay local et n'etablissent pas d'economie d'inference.

## Champs : la limite du gain de type

Les rapports `cascade-fields-20261007.json` des deux pilotes comptent maintenant
les champs predits sur les six cas, y compris quand le type s'abstient, au seuil
de champ existant de 0.5. Cette lecture porte sur les scores des descripteurs,
pas sur des valeurs extraites ni sur des actions executees.

| Bras | Champs attendus retrouves | Champs supplementaires | Champs attendus omis |
| --- | ---: | ---: | ---: |
| Cadre seul | 0 | 0 | 3 |
| Cadre puis Laya capture | 0 | 0 | 3 |
| Cadre puis Jeff capture | 0 | 4 | 3 |

Jeff ajoute `language` sur `paraphrase-05`, et `language`, `path`, `schema` sur
`paraphrase-07`. Ce dernier cas est aussi celui dont Jeff resout le type : le
gain de type accompagne donc un lot de champs non attendus. Ces ecarts sont
mesures contre les etiquettes authored du banc ; leur interpretation doit etre
revue independamment, notamment la distinction entre un champ fourni dans le
prompt et un champ requis pour executer la tache. Aucune promotion de la cascade
ne decoule du gain de type seul. Onze tests cibles passent.
