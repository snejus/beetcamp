FROM python:3.9-alpine AS base
    WORKDIR /app
    ENV PATH=/venv/bin:$PATH
    RUN pip install -U pip setuptools

FROM base AS build
    RUN apk update && \
        apk add gcc build-base && \
        pip install wheel && \
        python -m venv /venv
    COPY poetry.lock .
    RUN sed -nr '\/^(version|category|name) = "([^" ]*)"/{ s//\2 /; H; }; /^\[.*/{ s///; x; s/ \n/==/; s/\n//g; /./p; }' poetry.lock \
        | grep -v dataclass >/tmp/req
    RUN sed -n 's/ main//p' /tmp/req \
        | pip install --no-deps -r /dev/stdin
    COPY beetsplug beetsplug
    COPY README.md pyproject.toml .
    RUN pip wheel --no-deps --wheel-dir dist .

FROM build AS devbuild
    RUN sed -n 's/ dev//p' /tmp/req \
        | pip install --no-deps -r /dev/stdin

FROM base AS main
    COPY --from=build /venv /venv
    COPY --from=build /app/dist .
    RUN pip install --no-deps *.whl beets
    ENTRYPOINT ["beetcamp"]

FROM base AS test
    COPY --from=devbuild /venv /venv
    COPY --from=devbuild /app/dist .
    RUN pip install --no-deps *.whl
    COPY tests tests
    COPY setup.cfg .
    ENTRYPOINT pytest
