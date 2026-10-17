FROM python:3.13-slim-bookworm AS http-base
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV RAKATHON_HTTP_PORT=18765
WORKDIR /opt/rakathon/backend
COPY pyproject.toml ./pyproject.toml
COPY README.md ./README.md
COPY src ./src
COPY scripts/run_converter.py ./scripts/run_converter.py
COPY docker/http/entrypoint.py ./docker/http/entrypoint.py
COPY docker/http/healthcheck.py ./docker/http/healthcheck.py
RUN pip install --no-cache-dir --root-user-action=ignore . && pip check && python3 -c "import rakathon_backend.cli; import rakathon_backend.converter.prompt; from rakathon_backend.converter.prompt import prompt_path; assert prompt_path().is_file()"
FROM http-base AS http-with-converter
COPY --from=docker:27.5.1-cli /usr/local/bin/docker /usr/local/bin/docker
RUN mkdir -p /state/auth /run/rakathon /run/secrets && chown 65532:65532 /state/auth /run/rakathon && chmod 755 /usr/local/bin/docker && docker --version
USER 65532:65532
EXPOSE 18765
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD ["python3", "/opt/rakathon/backend/docker/http/healthcheck.py"]
ENTRYPOINT ["python3", "/opt/rakathon/backend/docker/http/entrypoint.py"]
FROM http-base AS http
RUN mkdir -p /state/auth /run/rakathon /run/secrets && chown 65532:65532 /state/auth /run/rakathon
USER 65532:65532
EXPOSE 18765
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD ["python3", "/opt/rakathon/backend/docker/http/healthcheck.py"]
ENTRYPOINT ["python3", "/opt/rakathon/backend/docker/http/entrypoint.py"]
