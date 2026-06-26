# AutoWebArchiver

Archivage automatique de pages web sur l'[Internet Archive](https://web.archive.org/).

Surveille une liste de sites (flux RSS ou sitemap XML, voir [`config/sources.yaml`](config/sources.yaml)),
détecte les nouveaux articles, et déclenche leur archivage via l'API [Save Page Now 2](https://web.archive.org/save).
Conçu pour tourner périodiquement via [GitHub Actions](.github/workflows/archive.yml).

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

## Flux RSS & sitemap

### 24 heures

Notes :

- `24heures.ch` semble bloquer les requêtes en provenance du robot d'Internet Archive.

#### Flux RSS

- `https://partner-feeds.publishing.tamedia.ch/rss/24heures/`

#### Sitemap

- `https://www.24heures.ch/news.xml`
- `https://www.24heures.ch/sitemaps/category.xml`
- `https://www.24heures.ch/sitemaps/sitemapindex.xml`

### Le Monde

#### Flux RSS

[Liste des flux RSS du Monde](https://www.lemonde.fr/le-monde-et-vous/article/2025/07/14/les-flux-rss-du-monde-fr_5498778_3237.html)

#### Sitemap

- `https://www.lemonde.fr/sitemap_news.xml`

### Le Temps

#### Flux RSS

- `https://www.letemps.ch/articles.rss`

#### Sitemap

- `https://www.letemps.ch/sitemap/AAAA-MM.xml`

Notes :

- Il y a un sitemap par mois, nommé `AAAA-MM.xml`.
- Le premier semble être `https://www.letemps.ch/sitemap/1998-03.xml`.

### RTS

#### Flux RSS

- `https://www.rts.ch/info/toute-info/?format=rss/news`

#### Sitemap

- `https://www.rts.ch/sitemaps/pages.xml`
