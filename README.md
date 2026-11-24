# primer-panel

The Panel of Primer, on the form of the product template `primer-blank`:
FastAPI, SQLAlchemy (async), Postgres, Redis, alembic and Vue 3. The deploy
machine `pridem` installs it from `primer.yaml`.

- `primer.yaml` -- what the machine installs: the stack `primer-panel`,
  edition `core`, the sources of its environment, routes for the frontend and
  the API. It declares no `test`: the Panel's unit tests run in its CI (the
  owner's decision of 22.11), and no dependency, so there is no `primer.lock`.
- `backend/` -- the API. `app/main.py` is the factory
  (`uvicorn --factory app.main:create_app`): it builds the application's state
  -- settings, the database engine and its sessions, the Redis client -- and
  hands it to requests through FastAPI dependencies (`app/core/state.py`);
  nothing is created at import time, and `tests/singletons.py` fences it.
  `app/core/` holds the database sessions, Redis, the one form of errors
  (`{"error": {"class", "message"}}`), the client's address and rate limits.
  `primer_report/` serves `/health` (its checks: `db`, `schema`, `redis`) and
  `/ready` and writes JSON logs (TZ section 11).
- People and access (PRIMER-PANEL-TZ-1 sections 2, 3, 5): `app/projects/`
  (projects of two kinds, servers), `app/access/` (people, memberships with
  their permissions -- the closed list `Permission` -- invites, Panel grants,
  the rules of giving and taking, the API under `/api/v1`), `app/audit/`
  (append only). The superadmin is the person whose Telegram id the Panel's
  passport names: `SUPERADMIN_TELEGRAM_ID`, a `param` of `primer.yaml`. The
  API's own description (`/docs`, `/redoc`, `/openapi.json`) is not served.
  Who is signed in comes with sessions (DM-150); until then every route of
  the API answers 401.
- `frontend/` -- the page. It reads `/config.json`, which its container
  renders from `API_BASE_URL`, `LANGUAGES` and `DEFAULT_LANGUAGE` at start;
  the image carries no instance value. Its colors, fonts and logo are CSS
  custom properties (`src/theme.css`). Its texts are built in for its two
  languages, `src/texts/en.json` and `src/texts/ru.json`: these files are the
  product's languages, declared as `languages: [en, ru]` in `primer.yaml`. An
  instance turns some of them on in its passport (`languages`,
  `default_language`); the machine gives them as `LANGUAGES` (codes by commas,
  the passport's order) and `DEFAULT_LANGUAGE`. The page speaks the first of
  the browser's languages the instance turns on, else the instance's default.
- `probes/` -- checks of the built images and of the live stack against the
  machine's conformance; they need docker.

Tests of the backend need Postgres and Redis: `DATABASE_URL` of a database
whose name ends with `_test`, and `REDIS_URL` of Redis database 15.

CI (`.github/workflows/ci.yml`) runs four jobs: backend, frontend, image
(the probes) and check (`primer.yaml` through the machine's loader,
`pridem check` of the repository, the pins of the images). The machine is
release v0.1.8, `PRIDEM_COMMIT` in the workflow.
