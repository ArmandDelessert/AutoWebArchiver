<img src="docs/logo.svg" height="70" alt="">

# AutoWebArchiver

Archivage automatique de pages web sur l'[Internet Archive](https://web.archive.org/).

Surveille une liste de sites (flux RSS ou sitemap XML, voir [`config/sources.yaml`](config/sources.yaml)),
détecte les nouveaux articles, et déclenche leur archivage via l'API [Save Page Now 2](https://web.archive.org/save).
Conçu pour tourner périodiquement via [GitHub Actions](.github/workflows/archive.yml).

📊 [**Page de statistiques et de monitoring**](https://armanddelessert.github.io/AutoWebArchiver/) — état des sources,
tendances (succès/erreurs/429), backlog restant.

## Installation locale

```bash
pip install -e . -r requirements-dev.txt
cp .env.example .env  # renseigner ARCHIVE_ORG_ACCESS_KEY / ARCHIVE_ORG_SECRET_KEY
                      # (clés gratuites sur https://archive.org/account/s3.php)
```

## Exécution

```bash
python -m autowebarchiver.main
```

## Tests

```bash
pytest
```

## Sources surveillées

Configurées dans [`config/sources.yaml`](config/sources.yaml) : flux RSS ou sitemap XML, avec un indicateur
`exhaustive` par source (un sitemap qui liste tout l'historique d'un site, sans urgence de capture, vs un flux
qui tourne et dont les anciens articles peuvent disparaître — voir le scheduler dans
[`src/autowebarchiver/main.py`](src/autowebarchiver/main.py)).

| Source | Type | Exhaustif |
| --- | --- | --- |
| [letemps.ch](https://www.letemps.ch/articles.rss) | RSS | non |
| [rts.ch](https://www.rts.ch/info/toute-info/?format=rss/news) | RSS | non |
| [lemonde.fr](https://www.lemonde.fr/sitemap_news.xml) | Sitemap | non |
| [apreslabiere.fr](https://www.apreslabiere.fr/sitemap.xml) | Sitemap | oui |
| [frenchspin.fr](https://frenchspin.fr/wp-sitemap.xml) | Sitemap | oui |
| [le-courrier.ch](https://www.le-courrier.ch/wp-sitemap.xml) | Sitemap | oui |
| [techcafe.fr](https://techcafe.fr/sitemap_index.xml) | Sitemap | oui |

`24heures.ch` a été essayé puis retiré : la découverte des articles fonctionnait, mais toutes les tentatives
de capture échouaient systématiquement (502 *bad gateway*) — le site bloque vraisemblablement les requêtes
en provenance de l'infrastructure d'Internet Archive.
