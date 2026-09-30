# syntax=docker/dockerfile:1
#
# Imagen de la API de Librería, en dos etapas (multistage):
#
#   builder  instala Poetry, las dependencias de producción y el paquete en un
#            entorno virtual (/opt/venv). Aquí sí hay herramientas de compilación.
#   runtime  parte de una imagen limpia y solo copia /opt/venv, las migraciones
#            y alembic.ini. No lleva Poetry, pip de más, pruebas ni código fuente
#            suelto: la imagen es más chica y tiene menos cosas que atacar.
#
# Construir:  docker build -t libreria-api .
# Correr:     docker run -p 8000:8000 -v "$(pwd)/data:/app/data" \
#                 -e LIBRERIA_JWT_SECRETO=... libreria-api
# (ver la sección "Docker" del README)

ARG PYTHON_VERSION=3.13

# ── Etapa 1: construir ───────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VERSION=2.5.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Poetry solo existe en esta etapa; la imagen final no lo necesita
RUN pip install "poetry==${POETRY_VERSION}" \
    && python -m venv /opt/venv

WORKDIR /build

# Primero SOLO los archivos de dependencias: mientras no cambien, Docker
# reutiliza esta capa (la más lenta) aunque cambie el código.
# --only main y SIN extras: ni herramientas de desarrollo ni el extra "ml"
# (scikit-learn, pandas...), que la API no usa.
COPY pyproject.toml poetry.lock README.md ./
RUN poetry install --only main --no-root

# Después el código: se empaqueta como wheel y se instala en /opt/venv
COPY src ./src
RUN poetry build --format wheel \
    && pip install --no-deps dist/*.whl

# ── Etapa 2: ejecutar ────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    LIBRERIA_URL_BD=sqlite:////app/data/libreria.db

# Usuario sin privilegios: si alguien compromete la app, no es root
RUN useradd --create-home --uid 1000 libreria

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY alembic.ini ./
COPY migraciones ./migraciones
RUN mkdir -p data logs && chown libreria:libreria data logs

USER libreria

# La base SQLite vive en un volumen: sobrevive a que se borre el contenedor
VOLUME ["/app/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/docs', timeout=4)"]

# Al arrancar: primero se actualiza el esquema de la base y después se levanta
# la API. `exec` hace que uvicorn reciba directamente las señales de Docker
# (docker stop) y se apague limpio.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn libreria.api.app:app --host 0.0.0.0 --port 8000"]
