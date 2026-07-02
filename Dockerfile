FROM python:3.11-slim

WORKDIR /app

COPY templates/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY templates/scripts/ scripts/
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
