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
