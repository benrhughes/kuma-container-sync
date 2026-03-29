FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY monitor.py healthcheck.py .

HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 \
	CMD python /app/healthcheck.py || exit 1

CMD ["python", "monitor.py"]
