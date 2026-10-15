FROM python:3.12.7-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

# Run unprivileged; /data holds the SQLite state and is a named volume.
RUN useradd --system --uid 10001 bridge && mkdir /data && chown bridge /data
USER bridge

CMD ["python", "app.py"]
