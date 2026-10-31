# Inventaire des ressources core d'un GLB

L'inspection GLB lit désormais les limites des chunks, le JSON glTF 2.0 et un
profil borné de déclarations `buffers`, `bufferViews` et `images`. Elle permet
de rechercher les modèles qui déclarent des ressources externes ou des données
intégrées, avec des références au fichier effectivement lu.

**Une référence externe ne signifie pas un fichier manquant.** Son existence
reste inconnue : aucun chemin ou URI lié n'est ouvert. Une plage présente dans
BIN ne prouve pas que ses octets forment une image ou une géométrie décodable.

## Utilisation et propositions

```bash
PYTHONPATH=src python -m tiberium_ai.asset_cli inspect modele.glb --source-id modele-001 --revision v1
PYTHONPATH=src python -m tiberium_ai.asset_cli search reports.json --tag resource:external_uri_declared
PYTHONPATH=src python -m examples.glb_catalog_demo
```

`reports.json` est un tableau de rapports d'inspection. Les snapshots du
[catalogue](ASSET_CATALOG_SNAPSHOTS.md) et le [journal de revue](ASSET_TAG_REVIEW.md)
réutilisent ces rapports et leurs propositions.

| Proposition | Sens limité |
| --- | --- |
| `resource:glb_json_read` | Le JSON a été lu et ce profil de ressources a pu être inventorié. |
| `resource:external_uri_declared` | Un buffer ou une image core déclare un URI hors du schéma `data:`. |
| `resource:data_uri_declared` | Un buffer ou une image core déclare un URI de schéma `data:`, sans décodage. |
| `resource:bin_buffer_range_present` | Les octets déclarés du premier buffer core sans URI sont présents dans BIN. |
| `resource:buffer_view_image_declared` | Une image core référence un bufferView contrôlé par ce profil ; son contenu n'est pas décodé. |

Ces tags restent proposés. La revue d'une déclaration ne certifie ni présence
de la ressource externe ni qualité du modèle. Un changement du binaire ou du
rapport invalide l'application d'une ancienne acceptation au nouveau rapport.
L'ancien snapshot conserve son rapport ; les décisions restent dans le journal
séparé et peuvent encore s'appliquer à ce rapport.

## Ce qui est lu

Le lecteur conserve les plages exactes des chunks. JSON doit être premier,
BIN est facultatif et doit être second lorsqu'il est présent. Les types
connus ne peuvent être dupliqués ; les autres chunks sont comptés et bornés,
sans interprétation de leur contenu.

Le document doit déclarer `asset.version = "2.0"`. Une éventuelle `minVersion`
différente de `"2.0"` sort de ce profil. Les comptes des tableaux de scènes,
nœuds, meshes, matériaux, textures, samplers, accessors, animations, skins et
caméras sont conservés comme **déclarations**. Les objets de ces tableaux ne
sont pas validés comme des scènes ou géométries complètes.

Pour les buffers, le profil contrôle les longueurs entières déclarées. Seul
le premier buffer sans URI est relié à BIN : sa longueur doit tenir dans ce
chunk, avec zéro à trois octets de padding nul. Un buffer implicite d'un autre
indice n'est pas pris en charge. Un BIN non relié au premier buffer core peut
être inventorié comme chunk ; aucun tag de buffer disponible n'en est déduit.

Les bufferViews sont contrôlés contre la longueur déclarée de leur buffer :
indice, offset et longueur entière. Un buffer externe reste non vérifié,
même si sa plage déclarée est cohérente. Une image core doit désigner soit un
URI, soit un bufferView ; dans le second cas, une déclaration MIME est requise.
Le type MIME n'est pas comparé aux octets et les accessors ne sont pas décodés.

Les URI restent opaques. Ils ne sont ni résolus, ni normalisés, ni décodés,
même lorsqu'ils ressemblent à un chemin local, HTTP, relatif ou `data:`. Les
références externes sont conservées littéralement, avec SHA-256 et taille UTF-8.
Pour un URI `data:`, seul le hash et la taille sont conservés, sans recopier son
payload. La syntaxe ou le contenu d'un URI n'est pas validé par cet inventaire.

Les ressources exposent `availability = "not_checked"`, sauf le buffer BIN
lié et les images situées dans ce buffer, qui indiquent `range_present` avec
la plage exacte d'octets. Une image dont le bufferView dépend d'un buffer URI
reste `not_checked` et ne reçoit pas de plage dans le fichier GLB.

## Preuves et compatibilité

Les métadonnées comprennent `gltf_declared_counts`, `gltf_core_resources`, les
listes d'extensions déclarées, le nombre de chunks et de chunks inconnus.
Les preuves distinguent `glb:chunks`, `glb:json` et chaque déclaration
`glb:resource:buffer:N` ou `glb:resource:image:N`. Chaque ressource renvoie à
son pointeur JSON et, si applicable, à une plage BIN.

Les extensions utilisées/requises sont inventoriées, mais leur contenu n'est
pas parcouru. **L'inventaire n'est donc pas exhaustif**, même sans URI externe
core. Aucun tag « autonome », « complet » ou « rendu valide » n'est produit.
Les coordonnées de `extras` ou d'accessors ne sont pas transformées en GPS :
`spatial` reste `null` et les recherches géographiques ne les retrouvent pas.

L'identité distincte `asset-glb-inspection/1` est explicitement autorisée par
le catalogue. Le hash d'entrée lie le profil
`parcimonia.glb-core-resources/v1` à la source et à l'échantillon. Les anciens
rapports gardent leur identité ; l'API d'en-tête `probe_media` est inchangée.
Le lecteur glTF JSON autonome garde aussi son comportement antérieur.

## Bornes et refus du profil

| Ressource | Limite |
| --- | --- |
| Source GLB complète | 1 MiB |
| Chunks | 16 |
| JSON | 256 KiB, 20 000 nœuds, profondeur 64 |
| Buffers / images core | 64 chacun |
| BufferViews / chacun des dix autres tableaux déclarés | 256 |
| Extensions utilisées / requises | 64 chacune, noms de 128 octets UTF-8 au plus |
| URI externe / URI `data:` | 2 048 / 65 536 octets UTF-8 |
| Indices, offsets et longueurs déclarés | Entiers uint32 ; longueurs strictement positives |

Ces restrictions sont celles du profil, pas une définition de tout glTF valide.
Les champs entiers exigent un type entier exact : booléens, `1.0` et `1e0`
sont refusés, même si leur valeur numérique pourrait être entière.
JSON accepte ses espaces autorisés ; le padding GLB JSON n'est pas certifié
strictement comme une suite de `0x20`. Cette limite figure dans le rapport.
Le profil n'est pas une validation complète du schéma glTF, des extensions,
des graphes de scène, des accessors, des animations ou de leur sens.

Un préfixe n'est pas traité comme corps complet. Une troncature, un dépassement,
un JSON non utilisable ou une incohérence dans les ressources contrôlées refuse
**tout l'inventaire du corps** : aucun compte, ressource ou preuve de corps
partiel n'est conservé. L'en-tête peut rester lisible avec un motif de refus,
tel qu'un buffer BIN demandé mais absent. Cela ne conclut pas à l'absence d'un
fichier externe. Le statut reste `partial` et le code 0 de l'inspection signifie
rapport produit, pas validation du modèle.

Référence primaire : [spécification Khronos glTF 2.0.1](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html),
sections GLB, GLB-stored Buffer et Images. Les règles de profil et budgets
ci-dessus appartiennent à Parcimonia ; aucun code de lecteur n'a été importé.
La [démonstration conservée](../wiki/ASSET_GLB_DEMO_2026-10-31.json) et le
[point de vérification](../wiki/ASSET_GLB_2026-10-31.md) utilisent des fixtures fabriquées.
