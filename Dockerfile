FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 WORKSPACE_ONLY=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY outreach/ outreach/
COPY dashboard/ dashboard/
COPY models/ models/
COPY campaigns/_defaults.json campaigns/_defaults.json
# data/ holds the SQLite log, settings, encrypted Gmail token and stage files: mount a persistent volume here
VOLUME ["/app/data"]
EXPOSE 8000
CMD ["sh", "-c", "uvicorn outreach.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
