import telegram_bot
import transfer_parser
import event_signatures
from handlers.handler_interface import handlerInterface
import requests
import asyncio
import time
from datetime import datetime

class IpfsEventHandler(handlerInterface):
    def __init__(self, w3) -> None:
        # Just some event which will trigger handle_event function
        event_sig_text = "Transfer(address,address,uint256)"
        self.w3 = w3
        self.event_name = 'IPFS download'
        self.event_signature = w3.keccak(text=event_sig_text).hex()
        self.counter = 0

    def get_name(self):
        return self.event_name
    
    def get_event_signature(self):
        return self.event_signature

    # TODO this should moved to library later
    async def _fetch_image(link):
        loop = asyncio.get_event_loop()
        future_image = loop.run_in_executor(None, requests.get, link)
        before = time.time()
        image = await future_image
        after = time.time()
        return image.content

    async def handle_event(self, transfer_event):
        monke = 'https://ipfs.io/ipfs/QmRRPWG96cmgTn2qSzjwr2qvfNEuhunv6FNeMFGa9bx6mQ'
        counter_str = 'Algys, check out: image {}, ipfs request took {} seconds'.format(self.counter, after - before)
        image = await this._fetch_image(monke)
        telegram_bot.send_image_to_all(image, counter_str) 
        