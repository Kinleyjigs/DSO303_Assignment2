FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Amazon RDS CA bundle so the API can verify the database's TLS certificate
ADD https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem /app/rds-ca.pem

COPY exam_api ./exam_api

RUN useradd --uid 10001 appuser && chmod 644 /app/rds-ca.pem
USER appuser

EXPOSE 8080
CMD ["uvicorn", "exam_api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
