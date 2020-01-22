from telegram.ext import Updater, MessageHandler, Filters, Handler
from telegram import Bot
import json
import logging
import os

import time
from os import listdir
from os.path import isfile, join

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                     level=logging.INFO)

with open("config.json", "r") as read_file:
    config = json.load(read_file)


updater = Updater(config["TOKEN"])
dispatcher = updater.dispatcher


def get_single_song(bot, update):
    chat_id = update.effective_message.chat_id
    message_id = update.effective_message.message_id
    logging.log(logging.INFO, f'start to query message {message_id} from {chat_id}')

    url = update.effective_message.text
    os.system('mkdir -p .temp')
    logging.log(logging.INFO, f'start downloading')
    bot.send_message(chat_id=chat_id, text="downloading...")
    os.system(f'spotdl --song {url} --folder ./.temp --file-format track{message_id}{chat_id}')

    logging.log(logging.INFO, 'sending to client')
    bot.send_message(chat_id=chat_id, text="sending to you...")
    bot.send_audio(chat_id=chat_id, audio=open(f'./.temp/track{message_id}{chat_id}.mp3', 'rb'), timeout=1000)

    logging.log(logging.INFO, 'sent')
    os.system(f'rm ./.temp/track{message_id}{chat_id}.mp3')


handler = MessageHandler(Filters.text, get_single_song)
dispatcher.add_handler(handler=handler)


POLLING_INTERVAL = 0.2
updater.start_polling(poll_interval=POLLING_INTERVAL)
updater.idle()