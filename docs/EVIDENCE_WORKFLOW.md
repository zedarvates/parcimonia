# Reprise, diff, logs et références exactes

Ces commandes locales ne font aucun appel à un modèle. Depuis un
environnement où `tiberium_ai` est disponible :

```powershell
# Références exactes : fichier, README et symbole Python
python -m tiberium_ai.repo_evidence --root C:/projet --goal 'Relire README et `archive_receipt`' --reference 'tests/test_archive.py'

# Examiner les modifications suivies depuis HEAD
python -m tiberium_ai.evidence_workflow --root C:/projet diff

# Exécuter explicitement un test précis et produire un reçu
python -m tiberium_ai.evidence_workflow --root C:/projet run-tests 'tests/test_archive.py::test_archive' --out C:/preuves/run-01
python -m tiberium_ai.evidence_workflow --root C:/projet diff --receipt C:/preuves/run-01/receipt.json

# Mémoriser les fichiers effectivement utiles, puis reprendre la tâche
python -m tiberium_ai.evidence_workflow --root C:/projet checkpoint --file README.md --file src/archive.py --receipt C:/preuves/run-01/receipt.json --out C:/preuves/reprise.json
python -m tiberium_ai.evidence_workflow --root C:/projet resume C:/preuves/reprise.json

# Lire le résumé et les premières occurrences d’erreurs, avec liens vers le log intact
python -m tiberium_ai.evidence_workflow logs C:/preuves/run-01/pytest.log --context 2 --limit 8
```

- **Références exactes.** Jusqu’à huit références passent avant le
  classement lexical, dans la limite habituelle de 16 fichiers. Le
  `README` à la racine est prioritaire. Les chemins et symboles Python
  entre accents graves sont reconnus ; `--reference '@nom_du_symbole'`
  précise la demande. Les références manquantes ou ambiguës sont
  signalées. Une mention d’un symbole ne vaut pas déclaration.
- **Reprise.** La sortie donne les fichiers à relire, le nombre de
  citations encore identiques et les tests à relancer. `checkpoint
  --review fichier.json` reprend les fichiers utiles d’une revue
  Parcimonia existante. `--evidence preuve.json` conserve les références
  des seuls fichiers utiles de cette sortie de `repo_evidence --format json`.
  Les citations sont revérifiées sur les octets et les lignes d’origine.
  Un index Git ordinaire et inchangé permet de réutiliser la liste des
  fichiers suivis, sans relancer Git. Si l’index ou sa configuration
  change, la CLI relit l’index via Git. Les octets des sources sont
  toujours revérifiés ; les reçus de test gardent leur contrôle complet.
  Les nouveaux fichiers et les changements hors du point de reprise
  sont proposés à partir du HEAD et des modifications locales enregistrées
  au checkpoint. La liste couvre les formats de source reconnus, suivis
  ou non ignorés, jusqu’à 16 propositions. Les fichiers déjà modifiés
  au checkpoint et restés identiques ne réapparaissent pas. Une ancienne
  sauvegarde sans cette base ne peut pas établir le delta : refaire un
  checkpoint, ou passer `resume --no-repo-delta` pour relire seulement
  les fichiers précédemment utiles. Aucun nouveau fichier n’hérite
  d’un résultat de test.
- **Diff.** `--base <commit>` change la référence Git. Le bilan
  montre les hunks et un aperçu borné. Les fichiers non suivis sont
  exclus et comptés. Un lien statique code/test donne « test trouvé,
  résultat non vérifié ». Seul un reçu courant avec contexte de
  couverture individuel peut associer des lignes modifiées à un
  test exécuté. Un test qui passe sans trace de couverture n’établit
  pas la couverture du diff.
- **Logs.** Le fichier intégral est conservé. Le résumé indique la
  première occurrence de chaque message normalisé et quelques lignes
  voisines. Les débuts explicites et fins reconnues de pytest/build
  séparent les segments ; les formats inconnus restent des extraits
  sans verdict. Les omissions et troncatures par budget sont signalées.
  La CLI utilise `--view auto` par défaut : elle compare la taille
  UTF-8 des deux rendus et conserve le texte entier s’il ne dépasse
  pas les extraits de plus de 10 %, ou si le petit journal n’est pas
  reconnu. Ce choix est une approximation
  de la taille du contexte, sans tokenizer chargé à l’exécution.
  `--view excerpts` force les extraits ; `--view raw` affiche tout le
  texte seulement sous les plafonds (12 Kio source, 16 Kio rendu).
  Les contrôles de terminal sont retirés de l’affichage ; les octets
  du journal restent intacts. Les logs UTF-8 et UTF-16 avec BOM sont pris en charge.

`--format json` se place avant la sous-commande de `evidence_workflow`.
`run-tests` nécessite pytest et, par défaut, pytest-cov. Si la
couverture n’est pas requise, utiliser `--no-coverage`. Le reçu et
le point de reprise sont écrits dans de nouveaux chemins hors du
dépôt source. Pytest reçoit la configuration suivie à la racine ou
une configuration vide ; il n’hérite pas de celle d’un dossier parent.
La comparaison lie le test à HEAD, aux octets suivis,
à l’interpréteur, aux versions installées et à une empreinte de
l’environnement. Les fichiers non suivis non ignorés et les lectures
incomplètes empêchent de réutiliser un résultat. Les fichiers ignorés,
les services externes et le contenu des dépendances installées ne sont
pas attestés : le reçu est une preuve locale d’observation, pas une
attestation signée de reproductibilité.
