# Enseignements

Les résultats positifs sont dans `docs/`. Cette page garde ce qui a coûté : les
prédictions qui ont échoué, les mesures qui ont menti, et les erreurs corrigées.

## Une mesure peut mentir par son corpus

- **Le corpus authoré flatte.** La règle par mots-clés est parfaite sur sa propre
  moitié alignée et se trompe **à chaque fois** qu'elle consent à répondre sur la
  moitié paraphrase. Agréger les deux moitiés produit un accord flatteur qui cache
  exactement cela : c'est pourquoi les deux populations se mesurent à part.
- **Un corpus étiqueté par des étrangers a renversé le classement.** Sur le bench
  authoré, le cadre verbe+objet gagnait ; sur une tranche publique de Dolly-15k, il
  perd, parce que `172` des `300` instructions sont des questions et qu'un cadre
  guidé par le verbe n'a pas de verbe tête à lire dans une question.
- **Le harnais gonflait tout.** Le compteur de masquages est tombé de `6863` à
  `206` une fois le texte injecté retiré, et la part des demandes qu'aucun
  vocabulaire n'atteint est montée de `45.8 %` à `72.8 %` : le harnais fournissait
  de faux verbes. Une proposition de vocabulaire dérivée d'un corpus sale déclare
  le bruit comme vocabulaire.
- **Une mesure sans révision citée n'est pas une mesure.** Deux relevés de la même
  voie sur deux révisions différentes donnent `0.27` et `0.565` de couverture avec
  les mêmes dénominateurs ; rien ne permet de savoir lequel on lit si l'artefact
  ne porte pas sa révision.

## Différence de tranche et bruit

La règle par mots-clés a marqué `0.737` puis `0.715`, puis `0.750` puis `0.630` sur
des tranches successives : quelques points d'écart entre deux candidats sont dans
le bruit de tranche (±4 mesuré) et ne sont pas un classement. Seul ce qui se
répète sur trois tranches vaut d'être retenu.

## Prédictions qui ont échoué

- **Le départage par spécificité** (un hint précis bat un marqueur générique) a
  rapporté zéro sur les classes visées, en a coûté sept ailleurs, et est resté
  **inert** faute de hint déclaré dans la classe concernée : le goulot est le
  vocabulaire, pas le marqueur. Il est désactivé par défaut et conservé, parce que
  l'expérience doit rester reproductible.
- **La mémoire KNN** : couverture croissante de `0.155` à `0.355` de `25` à `200`
  exemples, mais accord **non monotone** (`0.694`, `0.621`, `0.686`, `0.725`) — une
  petite mémoire répond juste sur un sous-ensemble facile, puis se charge de cas
  plus durs avant d'avoir assez de voisins pour les départager.
- **La route à deux étages** n'a pas tenu l'accord d'acte annoncé, parce qu'un
  plancher unique décide par question alors que le primaire est plus sûr d'un acte
  que d'un champ.
- **Le signal interrogatif** a tenu sa cible mais coûté ailleurs : les demandes de
  brainstorming formulées en question basculent vers la classe `answer`.

## Ce que la récupération est, et n'est pas

La récupération est un instrument de précision, jamais de couverture : elle répond
un tiers des cas et elle est la plus exacte sur ceux-là, là où la règle et le cadre
répondent sept à huit fois sur dix et se trompent plus. Le champ (« quel texte est
attaché ») est bien mieux atteint par similarité à des cas étiquetés que par
n'importe quel mot-clé : quelques dizaines d'exemples suffisent à le gagner.

## Vérification sur des demandes arrivées après la déclaration

Les verbes manquants avaient été déclarés après lecture du recensement. La porte
TASK-102 fixe donc la révision de référence `3244946e` et ne mesure que des
textes absents de celle-ci, avec un seuil annoncé avant la mesure : couverture en
volume du cadre supérieure à `0.50`.

Sur la révision `22de4af5`, le cadre atteint `0.7128` en volume sur `154`
demandes nouvelles (`195` occurrences), contre `0.1590` pour la règle. Le seuil
est franchi. La composition du groupe limite cependant la portée de ce résultat :
`92` des `154` textes dépassent 1000 caractères et le cadre répond à tous les
`92`. Sur la bande de 30 à 99 caractères, il répond à `10` occurrences sur `44`.
Le test établit la couverture sur ce groupe nouveau ; il ne mesure ni la justesse
des signatures ni la couverture future des demandes courtes.

Un premier essai avait trouvé cinq messages supplémentaires mais aucun texte
nouveau. La révision, adressée par contenu, restait identique et le groupe à
mesurer était vide. Des répétitions nouvelles ne remplacent pas des situations
nouvelles dans un test tenu à l'écart.

## Erreurs corrigées, à ne pas refaire

- **Nommer une action n'est pas vérifier un résultat.** Le pont d'escalade
  empruntait le motif `verified_accept` de la politique ; il porte désormais
  `signature_determined`, parce que la signature n'exécute rien.
- **`odycer` n'est pas un verbe.** Deux listes séparées sont obligatoires : verbes
  contre termes de domaine (nom de projet). Seule la capitale tranche entre un nom
  de projet en `-er` et un infinitif.
- **Une tolérance à une édition** attrape un vrai lapsus et produit un faux positif
  sur un nom court : d'où le plancher à six caractères, et le choix de **déclarer**
  une faute vue dix fois plutôt que de la deviner.
- **Un texte long qui est atteint n'est pas un succès** : il contient presque
  toujours un verbe, et le premier trouvé est arbitraire. La bande la plus
  fréquente, elle, reste la moins atteinte.
- **Le harnais de conversation n'est pas l'utilisateur** : le texte injecté par
  l'outil doit être retiré avant toute dérivation de vocabulaire, sinon il déclare
  ses propres avis comme intentions.
