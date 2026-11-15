# Chercher les preuves dans un dépôt

Voir aussi [reprise, diff et extraits de logs](EVIDENCE_WORKFLOW.md).

Depuis la racine du dépôt Parcimonia, avec le paquet disponible sur le chemin Python :

```powershell
$env:PYTHONPATH = 'C:\TiberiumAI\src'
python -m tiberium_ai.repo_evidence --root C:/TiberiumAI --goal "Retrouver le contrôle de provenance des mesures et ses tests"
```

La recherche lit les fichiers texte suivis par Git dans l’arbre de travail,
y compris les modifications locales de ces fichiers. Elle ne dépend pas de
l’inventaire de capacités. Les résultats sont séparés en code, tests et
documentation. Chaque extrait donne le chemin, les numéros de lignes et le
SHA-256 des octets lus. Le nom d’un fichier ne suffit pas : un extrait doit
contenir au moins une correspondance de contenu.

`--format json` conserve les références structurées. Par défaut les trois
catégories sont demandées ; `--role docs` permet de chercher seulement dans
la documentation. Pour demander un contrôle précis par catégorie, ajouter
par exemple `--need 'tests:mesure provenance'` (option répétable).
Les mots significatifs d’une exigence explicite doivent apparaître
dans un même extrait. Le rapprochement lexical ne valide pas le sens
ni la réussite d’un test.

Pour chercher une déclaration Python précise dans tous les fichiers
admissibles de la catégorie, ajouter `--need 'tests:@test_my_feature'`
ou `--need 'code:@my_function'`. Les chaînes et les commentaires ne
comptent pas. Deux déclarations ou davantage donnent une ambiguïté ;
si un fichier pertinent ne peut pas être analysé, l’unicité reste à
vérifier. Ces références de déclaration sont séparées du classement
des extraits et peuvent viser un fichier hors de la sélection principale.

Dans `requirement_links`, un identifiant relie chaque besoin à un
passage candidat (chemin, lignes et SHA-256), ou à un état : absent,
insuffisant ou ambigu. Les liens automatiques portent sur les catégories
et les parties de l’objectif. Plusieurs passages partiels ne sont pas
fusionnés pour déclarer un besoin couvert. Le filtre borne l’objectif
à 24 parties et signale le dépassement.

`--limit` borne le nombre de fichiers de 1 à 16. Après un premier choix
de trois passages au plus, Parcimonia conserve les déclarations, titres
et mots retrouvés, puis réemploie la place libérée pour chercher d’autres
passages autour des fonctions, tests et titres de section. Les blocs de
code clôturés dans un document ne sont pas de nouveaux titres. Au plus
cinq extraits sont rendus, dans le même budget de lignes et d’octets
de source que le premier passage, sans tronquer les lignes citées.

Si une catégorie tests ou documentation reste sans extrait suffisamment
lié à l’objectif, Parcimonia cherche une relation source avec le code
déjà retenu. Il reconnaît les appels directs dans les tests Python via
des imports absolus (y compris les alias) et les liens Markdown vers un
fichier Python, un nom qualifié ou une déclaration Python unique. Les
liaisons dynamiques, appels indirects via des helpers et exemples dans les
blocs clôturés ne sont pas résolus. Un import seul ne constitue pas un
appel. Le parcours s’arrête après 1 000 fichiers tests/doc admissibles.

Chaque relation cite les deux côtés dans `source_relations`. Elle peut
lever une alerte de catégorie, sans lever une exigence explicite ni
déclarer l’objectif couvert. Elle ajoute au plus une courte citation par
catégorie, dans la limite globale de fichiers, sans enlever d’extrait
déjà cité. Un appel trouvé dans le source ne signifie pas que le test a
été exécuté ou réussi.

`--follow-paths` active un parcours expérimental plus profond. Il suit
un seul helper Python de premier niveau dans le même fichier de test,
si sa déclaration est unique et l’appel direct. Il cite séparément
l’appel du test, l’appel effectué dans le helper et, si nécessaire,
la déclaration cible. Pour Markdown, il peut également citer le
titre qui contient la référence. Les chaînes de plusieurs helpers,
les alias masqués et les appels dynamiques restent hors périmètre.
Le mode ajoute quelques lignes seulement et n’enlève aucun extrait.
Il reste à la demande : les mesures n’ont pas montré de gain sur
les cinq nouveaux cas au regard de son coût.

- `gaps_detected` : une catégorie, une exigence ou une partie du but manque
  de correspondances suffisantes, ou le périmètre n’a pas pu être lu en entier.
- `review_required` : pas de lacune détectée par le filtre lexical. Cela ne
  prouve pas que chaque fait nécessaire est présent ou correct.

Les tests trouvés sont des sources à lire, pas des résultats d’exécution.
La recherche n’exécute ni tests, ni code des sources, ni modèle. Pour
vérifier un fait, relire l’extrait et le contexte du fichier sur la même
révision ; utiliser une sortie réelle pour toute affirmation sur une
exécution. Aucun résultat n’autorise une action automatique.

Le périmètre est borné aux formats texte pris en charge, à 5 000 fichiers,
32 Mio au total et 256 Kio par fichier. Les fichiers hors Git, les liens
symboliques, les chemins d’environnement et certains noms de secrets
ne sont pas lus. Les fichiers admissibles omis sont comptés. Le paquet de
préparation par inventaire reste disponible pour la sélection des capacités ;
cette commande le complète pour la recherche des sources.
