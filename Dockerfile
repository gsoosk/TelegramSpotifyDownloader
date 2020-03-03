FROM python:3.7-buster
WORKDIR /app
COPY config.json /app/config.json
COPY main.py /app/main.py
RUN pip install python-telegram-bot
RUN pip install spotdl

RUN apt-get update
RUN apt-get install -y ffmpeg


CMD ["python", "./main.py"]
