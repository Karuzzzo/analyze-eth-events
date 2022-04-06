import telebot
from telebot.types import Message
import requests
import os
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())
import json
import pprint
import random
from handlers.dummy_handler import WHATEVER
from handlers.tornado_withdraw_handler import WHAT

bot = telebot.TeleBot(os.environ.get("TELEGRAM_API_KEY"))
USERS_ID_INFO = json.load(open("consts/existing_ids_info.json")) 

lexa_chat_id = 275916122
# kirill_chat_id = 398438615
# chat_ids = [lexa_chat_id]

MADARA_SPEECH = [
            'Wake up to reality!',
            'Nothing ever goes as planned in this accursed world. ',
            'The longer you live, the more you realize that the only things that truly exist in this reality are merely pain. ',
            'Suffering and futility. ',
            'Listen, everywhere you look in this world, wherever there is light, there will always be shadows to be found as well.',
            'As long as there is a concept of victors, the vanquished will also exist.',
            'The selfish intent of wanting to preserve peace, initiates war.',
            'And hatred is born in order to protect love.',
            'There are nexuses causal relationships that cannot be separated'
]

def send_msg_to_all(text):
    payload = dict()
    # print("Got new text: {}".format(text))
    
    for chat_id in USERS_ID_INFO['users'].values():
        payload['chat_id'] = chat_id
        payload['text'] = text 
        payload['parse_mode'] = 'Markdown'
        p = requests.post("{}sendMessage".format(os.environ.get("TELEGRAM_BASE_ADDRESS")), data=payload) 
        print("Sent to the {}".format(chat_id))


@bot.message_handler(commands=['start'])
def welcome(message: Message):
    chat_id = message.chat.id
    # If it's a group chat
    if message.chat.title is None:
        title = message.chat.username
        # If it's a chat with user
    else:
        title = message.chat.title
        
    print('{} id ({}) sent `{}`'.format(title, chat_id, message.text))
    if chat_id not in USERS_ID_INFO['users'].values():
        title = None
        # If it's a group chat
        if message.chat.title is None:
            title = message.chat.username
        # If it's a chat with user
        else:
            title = message.chat.title
            
        write_to_json(title, chat_id)

        bot.reply_to(message, 'You will now receive stuff! Run /stop to stop receiving these msgs. \n{}'
        .format(random.choice(MADARA_SPEECH)))
    else: 
        bot.reply_to(message, 'Now you will never escape from my notifications, mortal! \n{}'
        .format(random.choice(MADARA_SPEECH)))

# TODO Make unsubscribe
# @bot.message_handler(commands=['stop'])
# def stop(message: Message):
#     chat_id = message.chat.id
#     if chat_id not in USERS_ID_INFO['users']:
#         title = None
#         # If it's a group chat
#         if message.chat.title is None:
#             title = message.chat.username
#         # If it's a chat with user
#         else:
#             title = message.chat.title
            
#         write_to_json(title, chat_id)

#         bot.reply_to(message, 'You will now receive stuff! Run /stop to stop receiving these msgs')
#         bot.reply_to(message, random.choice(MADARA_SPEECH))

#     else: 
#         bot.reply_to(message, "You will get everything, mortal")
#         bot.reply_to(message, random.choice(MADARA_SPEECH))


def write_to_json(title, id):
    USERS_ID_INFO['users'][title] = id
    with open("consts/existing_ids_info.json", 'w') as json_file:
        json.dump(USERS_ID_INFO, json_file, 
                        indent=4,  
                        separators=(',',': '))
good_text = '`Tornado_deposit`, 13879405 index: 340 Hash: `0x99c335300557237f613845957896b3ff0a63e9654f68b88395c573701f6e040c`'
bad_text = '*#Tornado_deposit, Block 13879405 index: 340*\nHash: `0x99c335300557237f613845957896b3ff0a63e9654f68b88395c573701f6e040c`\nSender: `0x5367B571f79dfEDB9D3Ba54920E3911a086A4f15`\nAmount: 100.0 ETH => 100.0 ETH'
def send_custom_msg():
    payload = dict()
    payload['chat_id'] = 275916122
    payload['text'] =  'Привет. Я только что добавил тебя в бота, так что посыплются уведомления. Be ready.'
    payload['parse_mode'] = 'Markdown'
    p = requests.post("{}getUpdates".format(os.environ.get("TELEGRAM_BASE_ADDRESS")))
    # p = requests.post("{}sendMessage".format(os.environ.get("TELEGRAM_BASE_ADDRESS")), data=payload) 
    print(p.json().message) 



def main():
    # p = requests.post("{}getUpdates".format(os.environ.get("TELEGRAM_BASE_ADDRESS"))) 
    # for msg in p.json()['result']:
    #     chat_id = msg['chat']['id']
    #     if chat_id not in chat_ids:
    #         chat_ids.append(chat_id)
    print('running bot instance..')
    # send_custom_msg()
    
    # send_msg_to_all('Tornado_deposit, 13879405 index: 340 Hash: 0x99c335300557237f613845957896b3ff0a63e9654f68b88395c573701f6e040c Sender: 0x5367B571f79dfEDB9D3Ba54920E3911a086A4f15 Amount: 100.0 ETH => 100.0 ETH')
    bot.polling()

if __name__ == '__main__':
    main()
