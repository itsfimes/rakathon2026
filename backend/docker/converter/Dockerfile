FROM python:3.13-slim-bookworm AS base

ARG OPENCODE_VERSION=2.0.31

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp/home \
    XDG_CONFIG_HOME=/tmp/home/.config \
    XDG_DATA_HOME=/tmp/home/.data \
    XDG_STATE_HOME=/tmp/home/.state \
    XDG_CACHE_HOME=/tmp/home/.cache \
    TMPDIR=/tmp

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --no-create-home --uid 65532 --user-group converter

COPY opencode /usr/local/bin/opencode
RUN chmod 755 /usr/local/bin/opencode \
    && opencode --version \
    && test "$(opencode --version)" = "opencode v${OPENCODE_VERSION}"

COPY pyproject.toml /pkg/pyproject.toml
COPY README.md /pkg/README.md
COPY src /pkg/src
RUN pip install --no-cache-dir --root-user-action=ignore /pkg \
    && pip check \
    && python3 -c "import rakathon_backend.converter.cli" \
    && rm -rf /root/.cache /tmp/home \
    && mkdir -p /tmp/home/.data/opencode/log /tmp/home/.config /tmp/home/.cache /tmp/home/.state \
    && touch /tmp/home/.data/opencode/log/opencode.log \
    && chown -R 65532:65532 /tmp/home \
    && chmod 755 /usr/local/bin/opencode

USER 65532:65532
RUN opencode --version \
    && test "$(opencode --version)" = "opencode v${OPENCODE_VERSION}"

USER 65532:65532
WORKDIR /work
ENTRYPOINT ["python3", "-c", "from rakathon_backend.converter.cli import main; raise SystemExit(main())"]
