FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
COPY *.json ./
EXPOSE 8000
# Import idempotent (upsert) des cartes au demarrage : garantit que la base du
# volume /data contient les cartes apres chaque (re)deploiement, sans shell manuel.
# Port = $PORT si fourni (Railway), sinon 8000 (local).
CMD ["sh", "-c", "python import_cards.py cards.json || true; exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
