from telegram.ext import Updater, MessageHandler, Filters, Handler
from telegram import Bot
import json
import logging
import os
from dotenv import dotenv_values

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                     level=logging.INFO)

with open("config.json", "r") as read_file:
    config = json.load(read_file)


def update_config():
    with open("config.json", "w") as write_file:
        json.dump(config, write_file)

token = dotenv_values(".env")["TELEGRAM_TOKEN"]
updater = Updater(token)
dispatcher = updater.dispatcher

def get_single_song_handler(bot, update):
    if config["AUTH"]["ENABLE"]:
        authenticate(bot, update)
    get_single_song(bot, update)


def get_single_song(bot, update):
    chat_id = update.effective_message.chat_id
    message_id = update.effective_message.message_id
    username = update.message.chat.username
    logging.log(logging.INFO, f'start to query message {message_id} in chat:{chat_id} from {username}')

    url = "'" + update.effective_message.text + "'"

    os.system(f'mkdir -p .temp{message_id}{chat_id}')
    os.chdir(f'./.temp{message_id}{chat_id}')

    logging.log(logging.INFO, f'start downloading')
    bot.send_message(chat_id=chat_id, text="Fetching...")

    if config["SPOTDL_DOWNLOADER"]:
        os.system(f'spotdl {url}')
    elif config["SPOTIFYDL_DOWNLOADER"]:
        os.system(f'spotifydl {url}')
    else:
        logging.log(logging.ERROR, 'you should select one of downloaders')

    logging.log(logging.INFO, 'sending to client')
    try:
        sent = 0 
        bot.send_message(chat_id=chat_id, text="Sending to You...")
        files = [os.path.join(dp, f) for dp, dn, filenames in os.walk(".") for f in filenames if os.path.splitext(f)[1] == '.mp3']
        for file in files:
            bot.send_audio(chat_id=chat_id, audio=open(f'./{file}', 'rb'), timeout=1000)
            sent += 1
    except:
        pass

    os.chdir('./..')
    os.system(f'rm -rf .temp{message_id}{chat_id}')

    if sent == 0:
       bot.send_message(chat_id=chat_id, text="It seems there was a problem in finding/sending the song.")
       raise Exception("dl Failed")
    else:
        logging.log(logging.INFO, 'sent')



def authenticate(bot, update):
    username = update.message.chat.username
    chat_id = update.effective_message.chat_id
    if update.effective_message.text == config["AUTH"]["PASSWORD"]:
        logging.log(logging.INFO, f'new sign in for user {username}, {chat_id}')
        config["AUTH"]["USERS"].append(chat_id)
        update_config()
        bot.send_message(chat_id=chat_id, text="You signed in successfully. Enjoy🍻")
        raise Exception("Signed In")
    elif chat_id not in config["AUTH"]["USERS"]:
        logging.log(logging.INFO, f'not authenticated try')
        bot.send_message(chat_id=chat_id, text="⚠️This bot is personal and you are not signed in. Please enter the "
                                               "password to sign in. If you don't know it contact the bot owner. ")
        raise Exception("Not Signed In")


handler = MessageHandler(Filters.text, get_single_song_handler)
dispatcher.add_handler(handler=handler)

POLLING_INTERVAL = 0.8
updater.start_polling(poll_interval=POLLING_INTERVAL)
updater.idle()
