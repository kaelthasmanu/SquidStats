FROM python:3.13.7-slim-trixie
WORKDIR /app
COPY requirements.txt ./
RUN apt-get update && \
    apt-get install -y build-essential gcc libmariadb-dev libssl-dev libicapapi-dev python3-dev libpq-dev && \
    rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["python", "app.py"]
