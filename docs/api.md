# OptionBeacon API (Phase 1)

The FastAPI service is a read-only boundary over existing OptionBeacon persistence. It runs alongside, and independently from, the Streamlit dashboard.

Install the repository requirements, then start it from the repository root:

```bash
uvicorn api.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for OpenAPI documentation.

The API requires `DATABASE_URL` for authoritative production reads. It never reads Streamlit secrets. Configure allowed frontend origins with a comma-separated value:

```text
OPTIONBEACON_CORS_ORIGINS=http://localhost:3000,https://app.example.com
```

The default is only `http://localhost:3000`; wildcard origins are rejected. Phase 1 has no mutation, execution, authentication, or provider endpoints.
