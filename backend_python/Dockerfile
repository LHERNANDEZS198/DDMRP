# Contexto de build: raiz del monorrepo  (docker compose lo configura asi)
# --- Etapa 1: compilar motor Rust ---
FROM rust:1.82-bookworm AS rust
WORKDIR /src
COPY core_rust/ .
RUN cargo build --release

# --- Etapa 2: backend Python + driver ODBC para MSSQL ---
FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg unixodbc-dev gcc \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft.gpg \
 && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql.list \
 && apt-get update && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend_python/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend_python/app ./app
COPY --from=rust /src/target/release/ddmrp_core /usr/local/bin/ddmrp_core
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
