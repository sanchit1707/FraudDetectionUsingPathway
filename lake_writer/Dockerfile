FROM python:3.10-slim

WORKDIR /app

# Install rust & cargo to build deltalake if needed, though wheels are usually available
# but slim sometimes misses libraries. We'll install build-essential just in case.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
