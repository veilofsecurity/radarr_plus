# Radarr Plus

A custom Home Assistant integration based on the core [Radarr integration](https://github.com/home-assistant/core/tree/dev/homeassistant/components/radarr), with extra actions for finding and searching for missing movies. It installs side by side with the core integration under the domain `radarr_plus`, so you add it as its own integration with its own Radarr connection.

Everything from core is kept (sensors, binary sensors, calendar, `get_movies`, `get_queue`). Added actions:

## `radarr_plus.get_missing_movies`

Returns monitored movies without a file that were released in the last `days` days (1–3650, default 30).

A movie's release date is the earlier of its digital and physical release dates, falling back to the cinema date when neither is known. Movies with no dates, movies not yet released, unmonitored movies and movies that already have a file are never returned.

| Field | Required | Description |
|---|---|---|
| `entry_id` | yes | Radarr Plus config entry |
| `days` | no | Look-back window in days (default 30) |

Response: `count`, `movie_ids` (ready to pass to the search action) and `movies` (details keyed by title, each with a `release_date`).

## `radarr_plus.search_movies`

Sends a `MoviesSearch` command to Radarr for the given movie IDs. Duplicate IDs are dropped.

| Field | Required | Description |
|---|---|---|
| `entry_id` | yes | Radarr Plus config entry |
| `movie_ids` | yes | List of Radarr movie IDs |

Response: `count` and `command` (`id`, `status`).

## Example: search everything missing from the last 30 days

```yaml
sequence:
  - action: radarr_plus.get_missing_movies
    data:
      entry_id: YOUR_ENTRY_ID
      days: 30
    response_variable: missing
  - condition: template
    value_template: "{{ missing.count > 0 }}"
  - action: radarr_plus.search_movies
    data:
      entry_id: YOUR_ENTRY_ID
      movie_ids: "{{ missing.movie_ids }}"
```

## Install

Copy `custom_components/radarr_plus` into your Home Assistant `config/custom_components/` folder (or add the repo to HACS as a custom repository), restart, then add **Radarr Plus** under Settings → Devices & services.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install pytest-homeassistant-custom-component aiopyarr==23.4.0
.venv/bin/pytest
```

Notes: the integration targets released Home Assistant (2026.8+, `voluptuous`; core `dev` has moved to `probatio`), so the setup/unload functions return `bool` and `DeviceInfo` is built as a dict. `translations/en.json` is generated from `strings.json` with `[%key:...%]` references resolved, since custom integrations only load `translations/`. aiopyarr has no `MoviesSearch` command, so it is posted through `async_command_other`.
