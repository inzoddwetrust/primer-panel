# Backend image in stages; the last one is the default target.
#
#   builder  runtime dependencies from requirements.lock, hashes required
#   sops     the sops binary at the machine's pin, checked by its sha256
#   test     runtime + dev dependencies + tests/: primer.yaml test.target
#   runtime  what runs on a box: no tests, no dev tools, no documents
#
# PRIMER_RELEASE and PRIMER_COMMIT are build arguments the machine passes to
# every build (contract 3 rule 19); /health and every log line carry them.
# A build without either stops at the first RUN of `base` with its name.
#
# git, ssh and sops: the Panel reads and edits the passports of primer-ops
# (DM-158). sops is not in Debian's apt at this version: its release binary,
# at the pin of the machine's install.sh, refused on another sha256.

FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 AS builder
WORKDIR /build
COPY requirements.lock ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.lock

FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 AS sops
ARG SOPS_VERSION="v3.13.3"
ARG SOPS_SHA256="e5bec3346a873ae91d871550f3e698c1aad962aff462a080e40f25fde17fef6b"
RUN python -c "import hashlib, sys, urllib.request; \
url = 'https://github.com/getsops/sops/releases/download/' + sys.argv[1] + '/sops-' + sys.argv[1] + '.linux.amd64'; \
data = urllib.request.urlopen(url, timeout=120).read(); \
found = hashlib.sha256(data).hexdigest(); \
sys.exit(f'sops {sys.argv[1]}: sha256 {found}, not {sys.argv[2]}') if found != sys.argv[2] else None; \
open('/sops', 'wb').write(data)" "${SOPS_VERSION}" "${SOPS_SHA256}" \
 && chmod 0755 /sops

FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 AS base
ARG PRIMER_RELEASE
ARG PRIMER_COMMIT
RUN : "${PRIMER_RELEASE:?PRIMER_RELEASE build argument is not set}" \
 && : "${PRIMER_COMMIT:?PRIMER_COMMIT build argument is not set}"
RUN apt-get update \
 && apt-get install -y --no-install-recommends git openssh-client \
 && rm -rf /var/lib/apt/lists/*
COPY --from=sops /sops /usr/local/bin/sops
RUN groupadd --gid 1000 panel && useradd --uid 1000 --gid panel --shell /bin/sh panel
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY alembic.ini logging.json ./
COPY migrations/ ./migrations/
COPY primer_report/ ./primer_report/
COPY app/ ./app/
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app" \
    PYTHONDONTWRITEBYTECODE=1 \
    PRIMER_RELEASE="${PRIMER_RELEASE}" \
    PRIMER_COMMIT="${PRIMER_COMMIT}"

FROM base AS test
COPY requirements-dev.lock pyproject.toml ./
RUN pip install --no-cache-dir --require-hashes -r requirements-dev.lock
COPY tests/ ./tests/
USER panel

FROM base AS runtime
USER panel
EXPOSE 8000
# --no-proxy-headers: uvicorn keeps the TCP peer as the OS reported it; the
# client's address is the app's to read (app/core/client_ip.py: X-Real-IP from
# the machine's nginx only, never X-Forwarded-For).
CMD ["uvicorn", "--factory", "app.main:create_app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--log-config", "logging.json", "--no-proxy-headers"]
