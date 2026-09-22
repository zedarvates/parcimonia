# Wiki Parcimonia

Ce dossier est la couche de reprise : ce qui a été décidé, où en est le dépôt, ce
qui a été appris — y compris ce qui a échoué — et sur quoi tout cela s'appuie. Il
ne remplace pas `docs/`, qui documente chaque mécanisme ; il relie, et il date.

| Fichier | Contenu |
| --- | --- |
| [DECISIONS.md](DECISIONS.md) | les choix tenus, leur raison, et ce qu'ils interdisent |
| [ETAT_ET_REPRISE.md](ETAT_ET_REPRISE.md) | l'état au 22 septembre 2026 et la marche à suivre pour reprendre |
| [ENSEIGNEMENTS.md](ENSEIGNEMENTS.md) | résultats, résultats négatifs et erreurs corrigées |
| [SOURCES.md](SOURCES.md) | d'où vient la ligne technique, avec licences et frontières |
| [RELEVE_2026-09-22.json](RELEVE_2026-09-22.json) | le relevé chiffré de cette date, citable |

Trois règles de lecture, les mêmes que partout ailleurs dans ce dépôt :

- une mesure cite sa révision et son origine (`fixture`, `public`, `measured`) ;
- une estimation ne s'écrit jamais comme une mesure, et un poids déclaré n'est pas
  un poids mesuré ;
- une abstention est un résultat, et un refus de claim en est un aussi.

## Reprendre en trois commandes

```powershell
.\\.venv\\Scripts\\python.exe -m pytest -q
.\\.venv\\Scripts\\python.exe examples\\fixture_suite.py --out runs\\fixtures
.\\.venv\\Scripts\\python.exe examples\\flagship.py
```

La première prouve que rien n'est cassé, la deuxième que la chaîne mesurée et
vérifiée fonctionne de bout en bout, la troisième montre le comportement qui
compte : ce que le routeur refuse, et pourquoi.

## Ce que ce wiki n'est pas

Ce n'est pas un second backlog : les cartes vivent dans `kanban.md`, et les
horizons en sont des vues générées. Ce n'est pas non plus une source de mesures :
le relevé daté cite ses commandes, et toute mesure non datée dans ces pages est
un renvoi vers `docs/`.
