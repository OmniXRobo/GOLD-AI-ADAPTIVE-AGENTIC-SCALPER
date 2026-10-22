# Gold AI Scalper dashboard

Vite + React + TypeScript single-page app for the GOLD AI ADAPTIVE AGENTIC SCALPER
backend. Every number on screen comes from the FastAPI API. If an endpoint fails or
returns nothing, the page shows "Endpoint unavailable" or "No data yet" and no
placeholder figures.

## Development

```bash
cd dashboard
npm install
npm run dev            # http://localhost:5173
```

The dev server proxies `/api` and `/ws` to `http://127.0.0.1:8000`. To point it at
another backend, run `GOLD_AI_BACKEND=http://host:port npm run dev`.

Sign in with a backend user. The client calls `POST /api/auth/login`, keeps the
token in `sessionStorage` (it is cleared when the tab closes) and sends it as
`Authorization: Bearer <token>` on every request. A `401` response signs you out.

## Typecheck and build

```bash
npm run typecheck      # tsc --noEmit
npm run build          # tsc --noEmit && vite build  -> dashboard/dist/
```

## Serving the build from FastAPI

The build is a static SPA that uses relative `/api` and `/ws` URLs, so the backend
must serve it from the same origin. Register the API and WebSocket routes first,
then add a catch-all that returns `index.html` for client-side routes such as
`/market` or `/authorization`:

```python
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

DIST = Path(__file__).resolve().parents[2] / "dashboard" / "dist"   # adjust to your layout

if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith(("api/", "ws/")):
            raise HTTPException(404)
        f = DIST / full_path
        if full_path and f.is_file() and DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
```

`dashboard/node_modules/` and `dashboard/dist/` are already ignored by the root
`.gitignore`.

## Layout

| Path | Purpose |
|---|---|
| `src/api.ts` | Typed API client, response types, domain badge labels, WebSocket helper |
| `src/state.tsx` | Auth context, plus live status (`/ws/live`, with `/api/overview` polling when the socket is down) and `/api/authorization` |
| `src/lib.ts` | `useApi` fetch hook and formatters (missing values render as `n/a`) |
| `src/components/` | Layout (banner, sidebar, mobile bottom nav), shared UI, domain metric/trade components |
| `src/pages/` | One component per route (24 pages) |

## Labeling rules built into the UI

- Every trade table and metric card has a domain badge: `SIMULATED (historical backtest)`,
  `SIMULATED (walk-forward OOS)`, `SIMULATED (live virtual, estimated fills)` or
  `ACTUAL BROKER FILLS`. Walk-forward is always described as historical, never live.
- Domains are never merged. Virtual and real results appear side by side, not combined.
- A sticky banner on every page shows the real-trading status and has an Emergency
  Stop button that asks for confirmation.
- The Owner Authorization page sends the grant request only after the exact phrase
  `I AUTHORIZE REAL MONEY TRADING`, a password, accounts, max lots and duration are
  all entered. The backend checks them again.
