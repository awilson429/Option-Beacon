# OptionBeacon React frontend

Phase 1 contains the application shell and the single production page at `/options`. It runs alongside Streamlit and consumes FastAPI only.

## Local development

From the repository root, start FastAPI:

```powershell
python -m uvicorn api.main:app --reload --port 8000
```

In a second terminal:

```powershell
cd frontend
Copy-Item .env.example .env.local
pnpm install
pnpm dev
```

Open `http://localhost:3000/options`. Configure another API using `NEXT_PUBLIC_OPTIONBEACON_API_URL`.

For isolated visual development without FastAPI, run `pnpm dev:mock-api` in place of the Python command. The mock server is development-only and never participates in production builds.

## Refresh policy

- Strategy state: 10 seconds
- Scalp research state: 5 seconds
- System status: 15 seconds
- Scalp performance and comparison: 60 seconds

SWR keeps the prior successful value during revalidation. Endpoint errors stay local to the affected section and provide a retry control.

## Validation

```powershell
pnpm test
pnpm lint
pnpm build
```

## Known API gaps

The current persisted Options Desk response does not yet supply strategy score, entry zone, maximum chase, stop, targets, risk/reward, exit score/state, contract bid/ask, delta, volume, or open interest. Components support those optional fields and render intentional empty states instead of manufacturing values. Add these fields in a future additive backend contract task; do not calculate them in TypeScript.
