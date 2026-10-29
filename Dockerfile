FROM node:22-bookworm-slim AS ui
WORKDIR /src/ui
COPY ui/package*.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY api/ api/
COPY models/ models/
COPY matching_engine/ matching_engine/
COPY data_ingestion/ data_ingestion/
RUN pip install --no-cache-dir . && useradd -m app && mkdir /app/data && chown app:app /app/data
COPY --from=ui /src/ui/dist /app/ui/dist
USER app
ENV ST_DATABASE_URL=sqlite:////app/data/stocktracker.db
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
