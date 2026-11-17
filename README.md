# Loras - Standalone Civitai Metadata Catalog

Turn Civitai links into a browsable, locally stored metadata catalog.

Paste one or more Civitai links, optionally add your Civitai API token, and the
tool fetches the **metadata only**: model name, creator, tags, description,
**preview images**, **trigger words**, version list, file names/sizes/hashes and
generation stats. Nothing else. **No model files are ever downloaded** - preview
images stream straight from the Civitai CDN in your browser.

This is a fork-in-spirit of
[willmiao/ComfyUI-Lora-Manager](https://github.com/willmiao/ComfyUI-Lora-Manager)
(GPLv3), rebuilt as a small standalone web app that is **totally independent of
any ComfyUI installation** - no `folder_paths`, no model directories, no nodes,
no build step.

## Features

- **Link + token -> metadata.** Accepts every Civitai link shape:
  - `https://civitai.com/models/12345`
  - `https://civitai.com/models/12345/some-slug?modelVersionId=67890`
  - `https://civitai.com/model-versions/67890`
  - bare ids (`12345`) and `modelId/versionId` shorthand (`12345/67890`)
  - `civitai.com`, `civitai.red` and `civitai.green` hosts, with or without `www.`
- **Metadata only.** The server performs exactly one kind of network request:
  `GET https://civitai.com/api/v1/...` JSON calls. It never downloads model
  files, preview images or example images to disk.
- **Trigger words** from every version, with click-to-copy chips and a
  copy-all button.
- **Preview images and videos** shown from the Civitai CDN, with cheap
  `width=450,optimized=true` CDN thumbnails (the same trick ComfyUI-Lora-Manager
  uses), an image gallery in the detail view, and blur-until-clicked NSFW handling.
- **Persistent local catalog.** Each fetch is saved as one JSON document under
  `data/metadata/{modelId}.json`, so the catalog survives restarts. Existing
  entries are updated in place when you fetch them again.
- **Search and filters.** Full-text search across name/creator/tags/trigger
  words, plus type and base-model filters (SDXL, Flux.1 D, Illustrious, ...).
- **Export.** Download the whole catalog as a single JSON file (`/api/export`).
- **Token management.** Tokens can be typed per fetch, remembered in the
  browser, or stored server-side in gitignored `data/settings.json`. A token is
  required for mature or early-access models that are hidden from anonymous
  visitors; it is sent only to Civitai as `Authorization: Bearer ...`.
- **Zero build step UI.** Vanilla HTML/CSS/JS, dark theme, responsive.

## Quick start

```bash
pip install -r requirements.txt
python main.py
# open http://127.0.0.1:8199
```

Options:

```text
--host HOST        bind address (default 127.0.0.1)
--port PORT        port (default 8199)
--data-dir PATH    where metadata/settings live (default: ./data,
                   env: LORAS_DATA_DIR)
--log-level LEVEL  DEBUG / INFO / WARNING / ERROR
```

## Typical workflow

1. Start the server and open the UI.
2. Click **+ Add links**, paste one Civitai link per line.
3. Optionally paste a Civitai API token (Account settings -> API keys) and
   tick *remember on server* if you fetch mature models.
4. Click **Fetch metadata**. Each link shows a per-URL success/error line.
5. Browse the catalog: trigger words are copy-ready chips on every card;
   click a card for the full detail view (gallery, description, version/file
   table, raw JSON).

## API

The UI talks to the same JSON API you can script against:

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/fetch` | `{"urls": [...], "token": "..."}` -> fetch + store metadata |
| `GET` | `/api/models` | list summaries (`?q=`, `?type=`, `?baseModel=`) |
| `GET` | `/api/models/{id}` | full stored document |
| `DELETE` | `/api/models/{id}` | remove from catalog |
| `POST` | `/api/models/{id}/refresh` | re-fetch from Civitai |
| `GET` | `/api/export` | whole catalog as one JSON download |
| `GET/PUT/DELETE` | `/api/token` | manage the optional server-side token |
| `GET` | `/api/meta` | counts, filter options, token status |

Example:

```bash
curl -X POST http://127.0.0.1:8199/api/fetch \
  -H "Content-Type: application/json" \
  -d '{"urls": ["https://civitai.com/models/12345"], "token": "optional"}'
```

## What is stored where

```text
data/
  settings.json          # optional {"civitai_token": "..."}  (gitignored)
  metadata/
    {modelId}.json       # full Civitai model document + bookkeeping fields
```

The stored document is the Civitai API response enriched with:

- `_linkedVersionId` - which version your link pointed at
- `_fetchedAt` - ISO timestamp of the last fetch
- `_sourceUrls` - every canonical link you fetched it through

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Project layout:

```text
main.py               # entry point (aiohttp server)
app/
  urls.py             # Civitai link parsing
  civitai.py          # Civitai REST client (metadata endpoints only)
  store.py            # JSON persistence + summaries
  server.py           # routes
static/               # single-page UI (vanilla JS)
tests/                # pytest units for urls/store
```

## Privacy and safety notes

- Run it locally (the default binds to `127.0.0.1`). There is no built-in
  authentication, so do not expose it to the public internet while a token is
  stored.
- Your Civitai token never leaves the machine except in requests **to
  civitai.com**.
- `data/` is gitignored so tokens and your catalog are never committed.

## License

GPL-3.0, inherited from the upstream project. See [LICENSE](LICENSE).
Upstream: [willmiao/ComfyUI-Lora-Manager](https://github.com/willmiao/ComfyUI-Lora-Manager) -
this repo keeps only the metadata-fetching ideas and URL/CDN handling patterns,
rewritten as a standalone service; all ComfyUI plugin code was removed.
