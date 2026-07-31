FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir requests

# Legacy test script (async agents)
COPY test_agents.py .

CMD ["python", "-c", "\
import os, sys, time, subprocess; \
print('Starting test runner...'); \
time.sleep(10); \
\
# Run BDH tests first (fastest, no gateway needed)  \
bdh_url = os.getenv('BDH_URL', 'http://bdh_watchdog:8090'); \
gateway_url = os.getenv('GATEWAY_URL', 'http://gateway:8080'); \
\
print('\\n=== Running async agents tests ==='); \
subprocess.run([sys.executable, 'test_agents.py']); \
"]
