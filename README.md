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

## Flux RSS

### 24 heures

- `https://partner-feeds.publishing.tamedia.ch/rss/24heures/`

### Le Monde

- **Actualités** : [A la une](https://www.lemonde.fr/rss/une.xml) l [En continu](https://www.lemonde.fr/rss/en_continu.xml) | [Vidéos](https://www.lemonde.fr/videos/rss_full.xml) | [Portfolios](https://www.lemonde.fr/photo/rss_full.xml) | [Les plus lus](https://www.lemonde.fr/rss/plus-lus.xml) | [Les plus partagés](https://www.lemonde.fr/rss/plus-partages.xml)
- **International** : [La une International](https://www.lemonde.fr/international/rss_full.xml) | [Europe](https://www.lemonde.fr/europe/rss_full.xml) | [Amériques](https://www.lemonde.fr/ameriques/rss_full.xml) | [Afrique](https://www.lemonde.fr/afrique/rss_full.xml) | [Asie Pacifique](https://www.lemonde.fr/asie-pacifique/rss_full.xml) | [Proche-Orient](https://www.lemonde.fr/proche-orient/rss_full.xml) | [Royaume-Uni](https://www.lemonde.fr/royaume-uni/rss_full.xml) | [Etats-Unis](https://www.lemonde.fr/etats-unis/rss_full.xml)
- **France** : [Politique](https://www.lemonde.fr/politique/rss_full.xml) | [Société](https://www.lemonde.fr/societe/rss_full.xml) | [Les décodeurs](https://www.lemonde.fr/les-decodeurs/rss_full.xml) | [Justice](https://www.lemonde.fr/justice/rss_full.xml) | [Police](https://www.lemonde.fr/police/rss_full.xml) | [Campus](https://www.lemonde.fr/campus/rss_full.xml) | [Education](https://www.lemonde.fr/education/rss_full.xml)
- **Economie** : [La une Economie](https://www.lemonde.fr/economie/rss_full.xml) | [Entreprises](https://www.lemonde.fr/entreprises/rss_full.xml) | [Argent](https://www.lemonde.fr/argent/rss_full.xml) | [Économie française](https://www.lemonde.fr/economie-francaise/rss_full.xml) | [Industrie](https://www.lemonde.fr/industrie/rss_full.xml) | [Emploi](https://www.lemonde.fr/emploi/rss_full.xml) | [Immobilier](https://www.lemonde.fr/immobilier/rss_full.xml) | [Médias](https://www.lemonde.fr/actualite-medias/rss_full.xml)
- **Planète** : [La une Planète](https://www.lemonde.fr/planete/rss_full.xml) | [Climat](https://www.lemonde.fr/climat/rss_full.xml) | [Agriculture](https://www.lemonde.fr/agriculture/rss_full.xml) | [Environnement](https://www.lemonde.fr/afrique-climat-et-environnement/rss_full.xml)
- **Pixels** : [La une Pixels](https://www.lemonde.fr/pixels/rss_full.xml) | [Jeux vidéo](https://www.lemonde.fr/jeux-video/rss_full.xml) | [Culture web](https://www.lemonde.fr/cultures-web/rss_full.xml)
- **Sciences :** [La une Sciences](https://www.lemonde.fr/sciences/rss_full.xml) | [Espace](https://www.lemonde.fr/espace/rss_full.xml) | [Biologie](https://www.lemonde.fr/biologie/rss_full.xml) | [Médecine](https://www.lemonde.fr/medecine/rss_full.xml) | [Physique](https://www.lemonde.fr/physique/rss_full.xml) | [Santé](https://www.lemonde.fr/sante/rss_full.xml)
- **Opinions** : [La une Opinions](https://www.lemonde.fr/idees/rss_full.xml) | [éditoriaux](https://www.lemonde.fr/editoriaux/rss_full.xml) | [chroniques](https://www.lemonde.fr/chroniques/rss_full.xml) | [tribunes](https://www.lemonde.fr/tribunes/rss_full.xml)

### Le Temps

- `https://www.letemps.ch/articles.rss`

### RTS

- `https://www.rts.ch/info/toute-info/?format=rss/news`
