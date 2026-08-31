FROM python:3.14-slim-trixie
WORKDIR /app
COPY requirements.txt ./
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y build-essential gcc krb5-user libmariadb-dev libssl-dev libicapapi-dev libkrb5-dev python3-dev libpq-dev && \
    rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["python", "app.py"]
