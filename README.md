# veille-tech

Service de veille automatisee avec deux pipelines independants:
- pipeline IA (digest quotidien)
- pipeline cyber/CVE (check quotidien)

Le projet lit des flux RSS, priorise les contenus via OpenAI, puis envoie le resultat sur Discord via webhook.

## Capacites

- Selection automatique des sujets prioritaires (fallback modele inclus)
- Generation de syntheses en Markdown
- Envoi Discord en message texte ou embeds (mode cyber)
- Suivi de consommation tokens par run et en cumul
- Deduplication des alertes cyber avec persistance locale
- Scheduling via APScheduler ou via cron

## Prerequis

- Python 3.10+
- Un compte OpenAI avec acces modele
- Un ou deux webhooks Discord (IA et cyber)

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

```bash
cp .env.example .env
```

Renseigner ensuite les variables dans `.env`.

### Variables IA (digest quotidien)

| Variable | Requise | Description | Defaut |
|---|---|---|---|
| `OPENAI_API_KEY` | Oui | Cle API OpenAI | - |
| `DISCORD_WEBHOOK_URL` | Oui | Webhook Discord du digest IA | - |
| `RSS_FEEDS` | Oui | Liste de flux RSS separes par virgules | - |
| `OPENAI_MODEL` | Non | Modele principal IA | `gpt-4.1-mini` |
| `OPENAI_MODEL_FALLBACKS` | Non | Modeles de secours (csv) | `gpt-4.1-mini,gpt-4o-mini` |
| `MAX_ITEMS_PER_FEED` | Non | Max items lus par flux | `20` |
| `MAX_CANDIDATES` | Non | Max candidats avant shortlist | `60` |
| `SHORTLIST_SIZE` | Non | Taille de la shortlist IA | `12` |
| `DISCORD_SUPPRESS_EMBEDS` | Non | Supprime les previews lien Discord | `true` |
| `TOKEN_USAGE_STATS_PATH` | Non | Fichier JSON de stats tokens IA | `data/token_usage_stats.json` |
| `TOKEN_USAGE_REPORT_IN_DISCORD` | Non | Ajoute stats tokens dans le message | `true` |
| `TIMEZONE` | Non | Timezone scheduler | `Europe/Paris` |
| `RUN_HOUR` | Non | Heure du run quotidien (0-23) | `8` |
| `RUN_MINUTE` | Non | Minute du run quotidien (0-59) | `30` |

### Variables cyber (check quotidien CVE)

| Variable | Requise | Description | Defaut |
|---|---|---|---|
| `CYBER_DISCORD_WEBHOOK_URL` | Oui | Webhook Discord cyber | - |
| `CYBER_RSS_FEEDS` | Oui | Flux RSS cyber/CVE (csv) | - |
| `CYBER_OPENAI_MODEL` | Non | Modele principal cyber | herite de `OPENAI_MODEL` |
| `CYBER_OPENAI_MODEL_FALLBACKS` | Non | Fallbacks cyber (csv) | herite de `OPENAI_MODEL_FALLBACKS` |
| `CYBER_MAX_ITEMS_PER_FEED` | Non | Max items lus par flux cyber | `30` |
| `CYBER_MAX_NEW_ITEMS_PER_RUN` | Non | Max nouveaux items traites par run | `30` |
| `CYBER_SHORTLIST_SIZE` | Non | Nombre max d'alertes prioritaires envoyees | `12` |
| `CYBER_RUN_HOUR` | Non | Heure du run cyber quotidien (0-23) | `10` |
| `CYBER_RUN_MINUTE` | Non | Minute du run cyber quotidien (0-59) | `0` |
| `CYBER_SEEN_ITEMS_PATH` | Non | Stockage des items deja vus | `data/cyber_seen_items.json` |
| `CYBER_SUPPRESS_INITIAL_BACKLOG` | Non | Si `true`, initialise sans envoyer le backlog initial | `false` |
| `CYBER_DISCORD_USE_EMBEDS` | Non | Envoi cyber en embeds | `true` |
| `CYBER_DISCORD_SUPPRESS_EMBEDS` | Non | Supprime les previews en mode texte | `true` |
| `CYBER_DISCORD_INCLUDE_ITEM_EMBEDS` | Non | Ajoute des embeds detail par alerte | `false` |
| `CYBER_DISCORD_ITEM_EMBEDS_MAX` | Non | Nombre max d'embeds detail | `3` |
| `CYBER_TOKEN_USAGE_STATS_PATH` | Non | Fichier JSON de stats tokens cyber | `data/cyber_token_usage_stats.json` |
| `CYBER_TOKEN_USAGE_REPORT_IN_DISCORD` | Non | Ajoute stats tokens dans la notif cyber | `true` |

## Execution manuelle

Run unique IA:

```bash
python3 run_once.py
```

Run unique cyber:

```bash
python3 run_cyber_once.py
```

Comportement cyber important:
- si aucun nouvel item n'est detecte, aucun message Discord n'est envoye
- si des nouveautes existent mais qu'aucune n'est jugee prioritaire, aucun message n'est envoye
- les IDs deja envoyes sont persistes dans `CYBER_SEEN_ITEMS_PATH`

## Execution en service

### APScheduler (process bloquant)

Lancer le scheduler IA quotidien:

```bash
python3 main.py
```

Lancer le scheduler cyber quotidien:

```bash
python3 main_cyber.py
```

### Cron (recommande pour prod)

Configurer la crontab avec l'assistant interactif:

```bash
python3 setup_cron.py
```

Le script:
- demande les horaires IA/cyber
- demande timezone (`CRON_TZ`) et binaire Python
- met a jour un bloc crontab gere et idempotent
- cree `logs/` si necessaire
- ecrit les sorties vers `logs/ai-cron.log` et `logs/cyber-cron.log`

## Sorties et persistance

- `data/token_usage_stats.json`: cumul tokens pipeline IA
- `data/cyber_token_usage_stats.json`: cumul tokens pipeline cyber
- `data/cyber_seen_items.json`: etat deduplication cyber
- `logs/ai-cron.log`: logs cron IA
- `logs/cyber-cron.log`: logs cron cyber

## Structure du projet

- `app/config.py`: chargement/validation de la configuration
- `app/rss.py`: collecte RSS IA
- `app/cyber_rss.py`: collecte RSS cyber + extraction CVE
- `app/graph.py`: pipeline IA (fetch -> shortlist -> digest -> notify)
- `app/cyber_graph.py`: pipeline cyber (fetch -> shortlist -> digest -> notify)
- `app/discord.py`: envoi Discord (texte/embeds)
- `app/token_usage.py`: suivi tokens par run et cumul
- `app/cyber_seen_store.py`: stockage des items cyber deja vus
- `run_once.py`: execution ponctuelle IA
- `run_cyber_once.py`: execution ponctuelle cyber
- `main.py`: scheduler IA quotidien
- `main_cyber.py`: scheduler cyber quotidien
- `setup_cron.py`: assistant de configuration crontab

## Securite

- Ne jamais versionner `.env`
- Regenerer les webhooks/cles si un secret a fuite
- Limiter les permissions du webhook Discord au strict necessaire

## Depannage rapide

- Erreur `OPENAI_API_KEY est manquant`: verifier `.env` et le repertoire courant
- Aucun message cyber: verifier `CYBER_RSS_FEEDS`, `CYBER_SEEN_ITEMS_PATH` et les logs
- Erreur modele OpenAI: verifier `OPENAI_MODEL`/`CYBER_OPENAI_MODEL` et les fallbacks
- Cron inactif: verifier `crontab -l` et les fichiers dans `logs/`
