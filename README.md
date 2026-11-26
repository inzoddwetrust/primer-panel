# primer-panel

The Panel of Primer, on the form of the product template `primer-blank`:
FastAPI, SQLAlchemy (async), Postgres, Redis, alembic and Vue 3. The deploy
machine `pridem` installs it from `primer.yaml`.

- `primer.yaml` -- what the machine installs: the stack `primer-panel`,
  edition `core`, the sources of its environment, routes for the frontend and
  the API. It declares no `test`: the Panel's unit tests run in its CI (the
  owner's decision of 22.11), and no dependency, so there is no `primer.lock`.
- `docker-compose.storage.yml` -- the second entry, `panel-storage` (DM-203):
  the Panel's object storage, RustFS pinned by digest, `persistent: true`,
  its root secret minted. No port, no route: its point `files` is for the
  services that take `PRODUCT_STORAGE_ADDRESS` (comms v4.2.0 asks every
  product for it), the value `panel-storage-panel-storage:9000`. No code of
  the Panel uses it yet.
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
- A server's passport (DM-158): `/servers/:serverId/passport`, from the
  server's card -- its fields, the rules of those that are not obvious, the
  secrets by name and state, "apply" with "are you sure?" on `prod`; a
  secret's value leaves the page with its request. `GET
  /api/v1/servers/{id}/passport` reads it from `primer-ops` with the Panel's
  age key -- the secrets of `asked` and `policies.tls` by name and state,
  never a value; `PUT .../passport/field` and `.../passport/secret` (the
  permission `passport`) are one commit of `primer-ops` each, the value of a
  secret on `sops`' stdin, the version one up, checked by the pinned machine's
  loader; a stale `base` is refused 409, no merge. `POST .../passport/apply`
  queues `update`; it is applied when a green verdict read the server's file
  at the head. `OPS_REPO` is `ssh.github.com:443` or `file://`; the write key
  and the age key are files of the stack (`app/ops/`). A server whose box reads
  its passport from a file (`state: file`) is not edited here, nor one
  primer-ops holds damaged (`state: damaged`: `sops-damaged`, `not-a-file`);
  "apply" reads primer-ops first and refuses a passport the box would fail
  on -- absent, damaged, refused by the machine.
- A new server (DM-157): `/projects/:projectId/servers/new` -- a one-time
  registration token (an hour, the permission `servers`), shown once with the
  command a box registers by (` PRIDEM_REGISTER_TOKEN=<token> pridem register
  --panel <api>`: the token in the environment, never an argument) and, for a
  bare VPS, the machine's `install.sh` of the Panel's pinned release; the page
  waits for the box (`GET .../registration-tokens/{id}`, never the token).
- A run waiting for a key to a repository (DM-159): on the run's page and the
  server's card, the public key (no secret: every member of the project sees
  it), the page of the repository's deploy keys when the machine named one,
  the rights it needs, until when -- read from the run's own lines: the last
  `notice` `key_needed` opens the wait, the first `step_finished` after it
  closes it (`ok` -- granted), `run_finished` ends it (`app/runs/keys.py`).
  The box goes on by itself; the Panel sends it nothing. The page gets
  `key_wait`, the stream `event: key`, the card `GET
  /api/v1/servers/{id}/key-wait`.
- A run (DM-156): `/servers/:serverId/runs/:runId` -- its ladder of steps
  live, its log, its verdict, "repeat" and "copy for an LLM" (the report the
  box sent in the envelope, byte for byte). The lines come as server-sent
  events from `GET /api/v1/streams/servers/{id}/runs/{run_id}` -- `id` is the
  line's `seq`, `Last-Event-ID` goes on, a gap waits for its line; the path
  `/api/v1/streams/` has `buffering: false` and `read_timeout: 120s` on the
  route. The state of a run -- running, finished, abandoned, a silent box --
  is the box's fields (`app/runs/status.py`).
- A server's card (DM-155): `/servers/:serverId` -- its head (the fleet's
  row), what stands on it as the box measured it, its runs, and the verbs of
  the machine's registry that end with a verdict as buttons (`GET
  /api/v1/servers/{id}/verbs`; DM-202: not `check`, `register`, `ssl status`,
  `db connect` -- and what is not a button is not queued either): each
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
