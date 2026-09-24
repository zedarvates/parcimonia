# Récupération par action et objet : essai négatif

TASK-081 compare un KNN par mots à un candidat qui sépare l'action du premier
verbe et les mots de son objet. Le candidat partage la mémoire labellisée, le
nombre de voisins, le seuil de similarité, le moyennage des réponses et les
seuils d'abstention du KNN existant.

L'auto-appariement « extract the schema of the file at this path » cesse
d'être dilué par des voisins du même sujet portant d'autres actions. Il passe
de l'abstention à la réponse `extract`.

La contrepartie mesurée est plus importante : sur les 9 paraphrases de la
fixture dont les étiquettes ne sont pas contestées, le KNN par mots répond à
1/9 et le candidat par action/objet à 0/9. Il n'y a donc aucun gain hors
mémoire observé et aucune promotion de la nouvelle route.

Les trois autres cas de paraphrase sont exclus de cette comparaison parce que
leurs étiquettes attendent la décision humaine documentée dans
[LABEL_REVIEW.md](LABEL_REVIEW.md). Même après cette décision, une fixture ne
prouve pas la qualité sur des issues réelles. La prochaine hypothèse serait
de conserver le contrôle par action tout en rapprochant des objets exprimés
avec d'autres mots, puis de mesurer sur une tranche non utilisée pour concevoir
la métrique.
