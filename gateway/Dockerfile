FROM pathwaycom/pathway:latest

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY gateway/requirements.txt /app/requirements.txt
RUN pip install uv && uv pip install --system --no-cache -r requirements.txt

# Install local langgraph-redis library
COPY langgraph-redis /app/langgraph-redis
RUN uv pip install --system -e /app/langgraph-redis

# Copy entire project (Pathway needs access to layer0-4, orcestrator, etc.)
COPY . /app

# Data directory
RUN mkdir -p /app/data /app/models

WORKDIR /app

EXPOSE 8080

CMD ["python", "gateway/main.py"]
