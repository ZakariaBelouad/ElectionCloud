FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN groupadd --gid 10001 electioncloud \
    && useradd --uid 10001 --gid 10001 --no-create-home electioncloud \
    && install -d -m 0700 -o electioncloud -g electioncloud /data /keys
COPY requirements.txt requirements-cosmos.txt ./
RUN python -m pip install --no-cache-dir -r requirements-cosmos.txt
COPY electioncloud.py cosmos_store.py ./

FROM base AS web
COPY web.py .
USER electioncloud
CMD ["python", "web.py", "--db", "/data/election.db", "--bind", "0.0.0.0", "--port", "8767", "--kafka"]

FROM base AS worker
COPY requirements-kafka.txt .
RUN python -m pip install --no-cache-dir -r requirements-kafka.txt
COPY kafka_worker.py .
USER electioncloud
CMD ["python", "kafka_worker.py", "--db", "/data/election.db", "--broker", "broker:9092"]

FROM worker AS azure-web
COPY app_service.py web.py ./
CMD ["python", "app_service.py"]
