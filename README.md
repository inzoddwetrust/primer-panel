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
- A server's card (DM-155): `/servers/:serverId` -- its head (the fleet's
  row), what stands on it as the box measured it, its runs, and the verbs of
  the machine's registry as buttons (`GET /api/v1/servers/{id}/verbs`): each
  a form by the verb's own JSON Schema, only with the permission for the
  server's role; a destructive action is confirmed by the server's name typed
  exactly, any action but reading on `prod` by "are you sure?" -- both
  checked by the API (`app/agent/verbs.py`).
- The fleet (DM-154): `/`, the servers of the projects a person sees, red
  first, read again every 30 s; `GET /api/v1/servers` gives each with the
  facts its box sent (`null` -- no data) and the reasons it is red
  (`app/fleet/reasons.py`: no heartbeat for 90 s, a verdict not verified, a
  red verdict, a service unhealthy, the machine behind the Panel's pinned
  release, the certificate due by the machine's own moment), in the fleet's
  order. The person's page moved to `/me`.
- The screens of access (DM-152): `/projects` (the projects a person sees;
  the superadmin makes them), `/projects/:projectId` (people and their
  permissions, the admin the superadmin appoints, invites -- a link shown
  once) and `/superadmin/admins` (every admin × every permission). The
  columns are the API's list, `GET /api/v1/permissions`; a member's row shows
  `effective` (an admin's `people` is the API's) and a change sets
  `permissions`, keeping what the giver cannot see. The page shows only what
  a person may do; the API checks every action again.
- The agent's side (DM-153): `app/agent/` -- `/agent/v1/` by contract 4 of
  the deploy machine (`pridem.protocol`, the wheel of its release in
  `requirements.lock`): a box registers by a one-time token of its project
  and signs every request with its ed25519 key, of which the Panel keeps the
  public half; heartbeat, the queue of commands (a long-poll; giving is
  taking; one taken command per server), the events of a run by `(run_id,
  seq)`, its verdict in a signed envelope, history. People put commands in a
  server's queue under `/api/v1/servers/{id}/commands`, each checked against
  the machine's verbs and the person's permission.
- Sign-in (DM-150): comms' sign-in module vouches for who came (Telegram);
  the Panel keeps the binding of the attempt to the browser (the cookie
  `panel_login` against the `state` of the return), decides by the Telegram
  id -- the superadmin, an invite, a member, else refused with the id shown
  -- and keeps the session: `panel_session`, an opaque token whose sha256
  lives in Redis for seven days. Revoking access, deactivating and a new
  superadmin close every session of the person at once (an epoch per person).
  `GET /auth/telegram/start`, `GET /auth/telegram/return`, `POST
  /auth/logout`; every end of sign-in is a redirect to the frontend.
  `COMMS_API_URL` and `COMMS_SERVICE_TOKEN` are optional until comms is a
  dependency of the Panel (DM-160); `DOMAIN_FRONTEND` and `DOMAIN_API` come
  from the passport.
- `frontend/` -- the page (DM-151): Vue with `vue-router`, `pinia` and
  `vue-i18n`, the blank's form. `src/api/client.ts` -- the client of the
  API, made per application and provided (no module state), sending the
  session cookie (`credentials: 'include'`) and reading the one form of
  errors; a 401 drops the person and shows the sign-in. Pages: `/login` --
  the button to the API's `/auth/telegram/start` (an invite link
  `/login?invite=<token>` hands its token on) and a refused sign-in from the
  fragment `#reason=<code>[&telegram_id=<id>]`; `/` -- the person of
  `/api/v1/me`. The API answers CORS with credentials to the frontend's origin
  alone and refuses a changing request to `/api/v1/` or `/auth/logout` from
  any other origin (`app/core/origin.py`).
- The page in general: it reads `/config.json`, which its container
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
