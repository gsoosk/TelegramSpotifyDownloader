FROM python:3.12-slim

WORKDIR /app

# ffmpeg is required by spotdl to convert audio.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY config.json /app/config.json
COPY main.py /app/main.py

CMD ["python", "./main.py"]
