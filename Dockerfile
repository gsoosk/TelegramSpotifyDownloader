FROM python:3.7-buster
WORKDIR /app
COPY config.json /app/config.json
COPY main.py /app/main.py
RUN pip install python-telegram-bot==12.3.0
RUN pip install spotdl==3.1.2

RUN apt-get update
RUN apt-get install -y ffmpeg


CMD ["python", "./main.py"]
