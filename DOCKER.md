# Extractify – Docker Setup

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (v20+ with Compose v2 plugin)
- Copy `.env.example` to `.env` and fill in real values

```bash
cp .env.example .env
```

---

## Architecture

```
┌────────────┐      ┌──────────────┐      ┌───────────┐
│  Frontend   │─────▶│   Backend    │─────▶│  MongoDB   │
│  Next.js    │:3000 │   FastAPI    │:8000 │  mongo:7   │:27017
└────────────┘      └──────────────┘      └───────────┘
          ▲                  ▲                    ▲
          └──────────────────┴────────────────────┘
                      app-network (bridge)
```

All services communicate on a shared `app-network` bridge network.
The frontend calls the backend via `http://backend:8000` for server-side
requests. Browser-side (client) calls use the `NEXT_PUBLIC_API_BASE_URL`
env var — set it to `http://localhost:8000` locally, or your public domain
in production.

---

## Quick Start (Production)

```bash
# Build and start all services
docker compose up -d --build

# Verify everything is healthy
docker compose ps

# Follow logs
docker compose logs -f
```

The app will be available at:
- **Frontend:** http://localhost:3000
- **Backend API:** http://localhost:8000
- **Health check:** http://localhost:8000/health

---

## Development Mode

Development mode mounts source code into containers for hot-reload.

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

- Backend: uvicorn runs with `--reload` — edit Python files and see changes instantly.
- Frontend: Next.js dev server with Fast Refresh — edit React/TS files and see changes instantly.

---

## Common Commands

| Command | Description |
|---|---|
| `docker compose up -d --build` | Build images and start all services |
| `docker compose down` | Stop and remove containers |
| `docker compose down -v` | Stop, remove containers **and volumes** (deletes DB data!) |
| `docker compose logs -f backend` | Tail backend logs |
| `docker compose logs -f frontend` | Tail frontend logs |
| `docker compose ps` | List running services and health status |
| `docker compose exec backend bash` | Shell into the backend container |
| `docker compose exec mongo mongosh` | Open a MongoDB shell |
| `docker compose restart backend` | Restart just the backend |

### Automated Backend Tests (Pytest)

Run backend tests with pytest inside the backend container:

```bash
docker compose up -d --build backend
docker exec extractify-backend-1 pytest
```

Run a specific test file:

```bash
docker exec extractify-backend-1 pytest tests/download_security_test.py
```

---

## MongoDB Access

The MongoDB instance is configured with authentication via `MONGO_USER` / `MONGO_PASSWORD` in `.env`.

**Connect with mongosh (from host):**
```bash
mongosh "mongodb://extractify:changeme@localhost:27017/extractify?authSource=admin"
```

**Connect with MongoDB Compass:**
```
mongodb://extractify:changeme@localhost:27017/extractify?authSource=admin
```

---

## Running Migrations / DB Seeding

This project uses Beanie ODM. Document models are auto-registered on startup
(see `app/core/database.py`). There is no manual migration step — Beanie
handles schema changes automatically for MongoDB.

If you need to seed data:
```bash
docker compose exec backend python -m app.scripts.seed
```

---

## Environment Variables

See [.env.example](.env.example) for the full list. Key variables:

| Variable | Description | Default |
|---|---|---|
| `MONGO_USER` | MongoDB root username | `extractify` |
| `MONGO_PASSWORD` | MongoDB root password | `changeme` |
| `MONGO_DB_NAME` | Database name | `extractify` |
| `NEXT_PUBLIC_API_BASE_URL` | API URL for browser-side fetch | `http://localhost:8000` |
| `BACKEND_PORT` | Host port for backend | `8000` |
| `FRONTEND_PORT` | Host port for frontend | `3000` |

---

## Rebuilding a Single Service

```bash
docker compose up -d --build backend   # rebuild only backend
docker compose up -d --build frontend  # rebuild only frontend
```

---

## Troubleshooting

**Backend won't start / "mongodb_connection_failed":**
- Check that the `mongo` service is healthy: `docker compose ps`
- Verify `MONGO_USER` and `MONGO_PASSWORD` match in `.env`

**Frontend build fails with "Could not find a production build":**
- Ensure `output: "standalone"` is set in `frontend/next.config.ts`

**Port already in use:**
- Change `BACKEND_PORT` or `FRONTEND_PORT` in `.env`
