FROM python:3.12-slim
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    arp-scan \
    iputils-ping \
    netcat-openbsd \
    iproute2 \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 4000
VOLUME /app/data
CMD ["gunicorn", "-k", "eventlet", "-w", "1", "-b", "0.0.0.0:4000", "movie_selector:app"]
