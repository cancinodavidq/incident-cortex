FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN pip install \
    "numpy<2.0" \
    "httpx<0.28" \
    chromadb==0.5.0 \
    openai==1.30.1 \
    sentence-transformers==3.0.0 \
    sqlalchemy==2.0.30 \
    asyncpg==0.29.0 \
    gitpython==3.1.43 \
    tiktoken==0.7.0 \
    psycopg2-binary==2.9.9

COPY index_codebase.py .

CMD ["python", "index_codebase.py"]
