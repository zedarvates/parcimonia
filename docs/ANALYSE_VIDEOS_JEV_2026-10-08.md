# Jev : enseignements pour Parcimonia

Date : 8 octobre 2026. Statut : propositions, aucune route activee.

Analyse des transcriptions completes des deux videos de Cole Medin, confrontee
au code local de `C:\TiberiumAI`. HEAD consulte :
`0c2404fd949ce5d1edf4e852ae546f95d9fbc6fe`. Les nombreux ajouts et modifications
deja presents appartiennent au travail partage ; presence locale ne signifie
pas disponibilite dans une version publiee.

**Recommandation : reutiliser la cascade et les recettes existantes, puis ajouter
un pilote de tri des sources et de detection de nouveaute.** La condition de
promotion reste une comparaison avec des resultats independants et le cout de
toute la chaine. Le choix d'un mecanisme ne donne aucune autorisation d'agir.

## Sources et methode

- [Video 1 : AI Coding](https://www.youtube.com/watch?v=qwnJJMNGwgY), publiee le
  30 septembre 2026 selon les metadonnees YouTube. Transcription horodatee :
  534 segments, pagination terminee, dernier segment a 17:37.
- [Video 2 : AI Second Brain](https://www.youtube.com/watch?v=Cl3OWig5hkk), publiee
  le 8 octobre 2026 selon les metadonnees. Transcription : 402 segments,
  pagination terminee, dernier segment a 13:15. La description declare un
  partenariat avec OpenRouter.
- [Documentation TypeSafe](https://docs.typesafe.ai/introduction), consultee pour
  les questions atomiques et les types Choice, Score, Noul.
- [jev-ultrafast](https://github.com/browser-use/jev-ultrafast) et
  [jev-use](https://github.com/shitianfang/jev-use), lies par la premiere video,
  consultes en lecture seule pour preciser les mecanismes et leurs limites.

L'analyse porte sur les propos transcrits et les descriptions. Les sequences
visuelles, tableaux a l'ecran et demonstrations n'ont pas ete inspectes image
par image ou reproduits. Aucun plugin externe, poids ou service n'a ete installe.
Les chiffres presentes par l'auteur sont ses observations, pas nos mesures.

## Ce que les videos apportent

| Passage | Idee | Consequence pour Parcimonia |
| --- | --- | --- |
| Video 1, [2:48](https://www.youtube.com/watch?v=qwnJJMNGwgY&t=168s) | Examiner les actions avant les outils : secrets, destruction, exfiltration, derive de tache | Une recette d'analyse des effets, reliee aux controles de l'hote |
| Video 1, [7:45](https://www.youtube.com/watch?v=qwnJJMNGwgY&t=465s) | Tester un jeu avec un etat structure et des actions bornees | Un banc interactif avec horloge, trace et verification du resultat |
| Video 1, [10:21](https://www.youtube.com/watch?v=qwnJJMNGwgY&t=621s) | Un LLM prepare les choix et exploite les resultats | Conserver directeur, decision et verification comme responsabilites explicites |
| Video 1, [11:10](https://www.youtube.com/watch?v=qwnJJMNGwgY&t=670s) | Navigation rapide ; generation du texte deleguee au LLM | Etendre le navigateur existant par un adaptateur reel et une action de saisie controlee |
| Video 1, [13:36](https://www.youtube.com/watch?v=qwnJJMNGwgY&t=816s) | Classer issue, profondeur de revue et niveau de modele | Classer une demande puis choisir une route effectivement eligible |
| Video 2, [3:30](https://www.youtube.com/watch?v=Cl3OWig5hkk&t=210s) | Decider si un brouillon de reponse est utile | Un tri d'attention avant de payer la generation |
| Video 2, [4:04](https://www.youtube.com/watch?v=Cl3OWig5hkk&t=244s) | Reperer les instructions hostiles dans une source externe | Marquer les signaux et conserver la provenance de donnees non fiables |
| Video 2, [8:08](https://www.youtube.com/watch?v=Cl3OWig5hkk&t=488s) | Filtrer le bruit puis solliciter un LLM pour la pertinence contextuelle | Donner explicitement objectifs et contexte au filtre ; escalader les cas complexes |
| Video 2, [11:33](https://www.youtube.com/watch?v=Cl3OWig5hkk&t=693s) | Eviter de traiter une information deja connue | Distinguer doublon, mise a jour, contradiction et nouveaute |

L'enseignement commun est de deplacer les decisions repetitives vers un
mecanisme borne. La seconde video expose aussi une limite utile : le modele de
decision seul ne suffit pas toujours pour juger l'adequation a un public et a
des priorites evolutives. Cela justifie une cascade sensible au contexte.

## Ce qui existe deja dans le depot

| Besoin | Base locale verifiee | Limite actuelle |
| --- | --- | --- |
| Questions typees, etat structure, calibration | `reflex.py`, `decision_json.py`, `provider_answers.py`, [contrats](DECISION_CONTRACTS.md) | La calibration doit correspondre a la question, au lot, au backend et a sa version ; qualite hors domaine a mesurer |
| Selection de skills, classement de fichiers, revue, feedback | `agent_recipes/recipes.py`, [recettes](AGENT_RECIPES.md) | Propositions bornees ; leur verificateur structurel ne prouve pas la pertinence semantique |
| Cascade avec contexte et budgets | `task_context.py`, `signature_cascade.py`, `cascade_resources.py` | Le contexte controle la preparation ; le predicteur recoit encore le prompt historique seul |
| Cache et dedoublonnage | `agent_recipes/cache.py`, audit des skills, normalisation du corpus | Reutilisation exacte ; pas une preuve de redondance semantique entre deux informations |
| Navigateur | `agent_recipes/browser.py`, adaptateur distinct `webbrain.py` | BrowserRunner offre click/focus et callbacks ; pas un driver navigateur installe ni un parcours de saisie complet |
| Temporalite et transitions | `decision_clock.py`, `world_model.py` | Horloge et calculs sur vecteurs existent ; pas de modele de jeu appris ou de preuve de playtest reel |
| Sources et comparaison | `context_provenance.py`, `context_input_audit.py`, `context_comparison.py` | Audit d'enveloppes, pas detecteur general d'injection ; labels independants encore manquants |
| Mesure de pipeline | `agent_recipes/benchmark.py`, `measurement.py`, `route_experiment.py` | Cout inconnu conserve comme inconnu ; correction humaine et verification a inclure selon le perimetre |

Le routage minimal, l'abstention, les verificateurs et le cache sont donc deja
des bases pertinentes. Il faut maintenant leur donner des cas d'usage observes.

## Ameliorations proposees et priorites

### P0 - Terminer la preuve sur les demandes reelles

Le paquet audite a ete relu en tant que JSON, sans afficher les demandes privees :
114 cas, zero label de type, zero groupe ratifie et
`split_status=input_audited_awaiting_independent_review`. Le rapport local de
preparation declare aussi zero cas de test et des metriques de qualite nulles.

Terminer la revue independante de langue, source, groupes, type et contexte ;
figer developpement/test par conversations et paraphrases ; regler les seuils
sur developpement ; capturer les memes cas pour baseline et cascade. Mesurer
accord avec les labels, erreurs acceptees, couverture, champs et abstentions.
Une issue verifiee est une preuve plus forte qu'un simple accord d'annotation.
Ce lot concerne les signatures ; il ne valide pas les nouvelles familles de
filtrage, de doublons ou de risque, qui auront besoin de leurs propres labels.

### P1 - Filtrer les sources selon l'interet pour le projet

Ajouter une recette proposee `attention.triage@1`. Entree : source, extrait
borne, date de publication et d'evenement, objectif courant, contraintes,
revision du contexte et candidats de connaissance deja retrouves localement.
Le contexte de confiance vient de l'hote ; le contenu externe reste une donnee.

Questions atomiques : pertinence pour l'objectif, caractere exploitable,
urgence observee et besoin de contexte supplementaire. Politique de sortie :
`process`, `defer`, `skip_candidate` ou `needs_context`. Une premiere application
peut trier des articles, videos et issues pour Parcimonia, avec une file locale
consultable et un budget d'attention. Le brouillon de reponse est un usage
possible de `process`, sans coupler la recette a une messagerie.

Reutiliser `DecisionSession.evaluate`, les contrats et les budgets. Une nouvelle
entree modele contenant objectifs et contexte doit avoir son propre protocole,
ses captures et ses cles de cache. Le controle de disponibilite actuel n'ajoute
pas ces informations au predicteur : l'appeler ne suffit pas pour personnaliser
la pertinence. Mesurer d'abord le rappel des elements utiles et le taux d'elements
utiles proposes au rejet ; conserver les cas incertains dans la file.

### P1 - Distinguer redondance et evolution de la connaissance

Ajouter une recette proposee `knowledge.novelty@1`. Faire d'abord une recherche
locale bornee : hashes exacts, puis candidats lexicaux/FTS ou retrieval disponible.
Comparer l'element a ces candidats avec les labels `duplicate`, `update`,
`contradiction`, `novel`, `uncertain`. Un score de similarite aide a trouver des
candidats ; il ne prouve pas l'absence de nouveaute.

Exemple : deux articles qui annoncent la meme revision peuvent etre redondants ;
un article corrigeant sa limite de contexte doit rester une mise a jour, meme
avec un vocabulaire presque identique. Lier chaque avis aux sources, extraits,
dates et hashes compares. Un doublon possible reste recuperable. Une absence
de candidat ne prouve pas une recherche exhaustive ; une contradiction ne
reecrit pas automatiquement le wiki. Mesurer surtout les mises a jour perdues
par erreur et les contradictions confondues avec des doublons.

### P1 - Analyser les effets des actions et la confiance des sources

Ajouter deux recettes proposees : `action.risk@1` et `source.trust-signals@1`.
La premiere recoit outil, arguments, cible resolue, effets declares, objectif
et perimetre autorise. La seconde examine une source externe pour exfiltration,
usurpation d'instruction, changement de regles ou tentative d'edition de memoire.
Elles retournent signaux, motifs et besoin de revue ; l'hote applique sa politique.

Les controles deterministes des chemins, permissions et effets restent requis.
Un avis negatif d'injection ne change jamais une source en instruction fiable.
L'audit d'enveloppes existant peut preceder ces recettes, mais ne les remplace pas.
Tester les faux positifs sur des citations innocentes, exemples `.env` et cours
de securite, puis les faux negatifs sur des effets indirects. Debuter en observation
pour comparer aux decisions effectivement prises par l'hote.

### P2 - Mesurer un vrai parcours navigateur local

Relier `BrowserRunner` a un environnement de test local explicite : observation,
execution et verificateur distinct. Ajouter une saisie dont la valeur vient du
LLM ou d'une fixture, et une confirmation par observation du resultat. Garder
versions d'etat, reobservation, bornes et detection des boucles.

Le README de [jev-ultrafast](https://github.com/browser-use/jev-ultrafast)
documente un etat DOM structure, des controles observes et des cibles revues
avant execution. Ces mecanismes inspirent l'adaptateur ; sa performance publiee
sur quelques parcours n'est pas notre mesure. Comparer une baseline deterministe
sur un parcours fixe, puis un parcours exploratoire borne, sur la meme application.
Verifier succes de bout en bout, actions inutiles, etats perimes, p95 et cout total.

### P2 - Regrouper les questions et choisir une route eligible

`classify_feedback` fait actuellement deux appels par record : sentiment puis
signaux help/bug. Une nouvelle version peut grouper les questions independantes
dans `DecisionSession.evaluate`. Mesurer appels, taille d'etat et latence ; ne pas
supposer qu'un appel logique equivaut a une seule passe interne de tous les backends.
Un schema modifie invalide la liaison de calibration correspondante.

Pour issues et revues, combiner type de travail, contexte disponible et liste
de routes reelles avec cout, preuve, localite et disponibilite. Un label
"modele fort" ne suffit pas a choisir une route ou son budget. Reutiliser registre,
vecteurs de ressources et politique d'escalade plutot qu'une nouvelle table de
preferences de marques. La proposition de revue rapide reste a mesurer avant
de reduire la profondeur effective.

### P3 - Playtests avec contraintes temporelles

Creer ensuite un environnement synthetique ou de jeu explicitement choisi,
avec etat structure, actions eligibles, repli deterministe, seed et journal
des transitions. Reutiliser `DecisionBudget` et le verificateur de resultat.
Le module `world_model.py` traite des vecteurs et des predictions fournies :
il ne prouve pas a lui seul l'existence d'un predicteur appris.

La frequence d'affichage et celle des decisions sont differentes. Par calcul,
250 ms par decision sequentielle donne au plus 4 decisions/s avant les autres
couts, tandis que 60 images/s donne 16,7 ms par image. La valeur de 250 ms est un
ordre de grandeur cite pour un autre usage dans la video, pas une mesure de
son jeu. Pour un playtest, mesurer le budget propre a la tache, les decisions
tardives, l'age des etats et les bugs reproduits, meme si le jeu affiche a 60 Hz.

## Comparaison des options

| Option | Effort et ressources | Choix propose |
| --- | --- | --- |
| Completer les labels et mesurer l'existant | Faible code ; revue humaine necessaire | Premier passage de preuve |
| Ajouter tri et nouveaute sur les primitives actuelles | Moyen ; fonctionne hors reseau avec captures/fixtures | Premier nouveau pilote fonctionnel |
| Installer un plugin Jev et brancher un fournisseur cloud | Integration et flux de donnees supplementaires | Bras optionnel apres contrat et corpus, si utile |
| Ajouter un nouveau gros modele local | Memoire, chargement et inference a mesurer | Reprendre le protocole CLEF/GEV existant ; pas un prerequis aux recettes |
| Construire un controleur interactif general | Effort eleve et verificateurs propres a chaque domaine | Apres un parcours navigateur borne et mesure |

## Protocole de preuve et cout

Comparer sur les memes entrees : traitement systematique par la baseline,
regles/cache seuls, puis regles/cache + decision bornee + secours si necessaire.
Conserver developpement et test separes ; grouper aussi les versions d'un meme
evenement pour le filtre et les paires de doublons. Donner aux bras le meme
contexte pertinent et le meme objectif de qualite.

Mesurer par famille : rappel utile, elements utiles ecartes, erreurs acceptees,
abstention, escalades, calibration, exactitude des sources et resultat final.
Mesurer aussi collecte, recherche, preparation, decision, generation, verification,
correction humaine, cache, chargement et attente. RAM/VRAM/energie et monnaie
restent des dimensions distinctes ; une valeur absente reste inconnue.

Pour une chaine simplifiee avec fraction `r` envoyee au LLM :
`C_candidat = C_collecte + C_recherche + C_decision + r*C_LLM + C_verification + C_correction`.
Comparer ce total au total de la baseline a qualite comparable. Economiser des
appels en supprimant des informations utiles ne constitue pas un gain valide.
Les ordres de grandeur annonces dans les videos ne fixent ni nos seuils ni nos
economies ; les petits essais juges par leur auteur ne prouvent pas la generalisation.
Probabilite d'un choix, score de pertinence et confiance calibree restent distincts.

## Verification de cette analyse

- Lecture locale des modules cites et des documents de contrats/cascade.
- Controle JSON actuel : 114 cas, zero label de type, zero groupe ratifie.
- 109 tests cibles passes le 8 octobre : recettes, regressions des contrats,
  comparaison de contexte, cascade de contexte et horloge de decision.
- Commande : `rtk proxy .venv/Scripts/python.exe -m pytest -q tests/test_agent_recipes.py tests/test_decision_contract_regressions.py tests/test_context_comparison.py tests/test_context_signature_cascade.py tests/test_decision_clock.py`.
- Ces tests couvrent des contrats et fixtures hors reseau. Aucune nouvelle
  inference neuronale, preuve visuelle, economie de production ou execution
  de parcours navigateur n'est revendiquee.
- Deux documents ajoutes seulement ; aucun changement du code applicatif,
  installation, commit, publication ou redemarrage de service.

Prochain increment conseille : formaliser `attention.triage@1` et
`knowledge.novelty@1`, leur corpus independant et un pilote local avec sorties
recuperables. Poursuivre en parallele logique la revue des signatures existantes,
sans reutiliser ses labels pour valider d'autres familles de decisions.
