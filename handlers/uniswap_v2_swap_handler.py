import telegram_bot
import transfer_parser
import event_signatures
import json
from handlers.handler_interface import handlerInterface

class UniswapV2SwapEventHandler(handlerInterface):
    def __init__(self, w3, text_telegram=False, dump_to="consts/swap_routers.json") -> None:
        event_sig_text = "Swap(address,uint256,uint256,uint256,uint256,address)"

        self.w3 = w3
        self.event_name = 'Uniswap V2 Swap()'
        self.text_telegram = text_telegram
        self.event_signature = w3.keccak(text=event_sig_text).hex()
        self.event_emitters = dict()
        self.dump_to = dump_to
    def __repr__(self):
        return self.event_name
    
    # Save all data to json
    def on_close(self):
        event_emitters_sorted = dict(sorted(self.event_emitters.items(), key=lambda x: x[1], reverse=True))
        with open(self.dump_to, 'w') as json_file:
            json.dump(event_emitters_sorted, json_file, 
                            indent=4,  
                            separators=(',',': '))
        print("Handler {} saved to json".format(self.event_name))
        print("Handler {} deleted".format(self.event_name))

    # Save all data to json
    def on_update(self):
        event_emitters_sorted = dict(sorted(self.event_emitters.items(), key=lambda x: x[1], reverse=True))
        with open(self.dump_to, 'w') as json_file:
            json.dump(event_emitters_sorted, json_file, 
                            indent=4,  
                            separators=(',',': '))
        print("Handler {} saved to json".format(self.event_name))


    def get_event_signature(self):
        return self.event_signature

    def handle_event(self, event):
        # receipt = self.w3.eth.getTransactionReceipt(event['transactionHash'])
        transaction = self.w3.eth.getTransaction(event['transactionHash'])
        transfer_event = dict()
        # TODO possible trickery with || or && stuff, think for 5 mins later
        
        if self.event_emitters.get(transaction['to']) is None:
            self.event_emitters[transaction['to']] = 1
        else:
            self.event_emitters[transaction['to']] += 1

        # TODO move restrictions to library
        # Exception for 100 ETH, we can't track it directly from tx
        # if event.address == '0xA160cdAB225685dA1d56aa342Ad8841c3b53f291':
        #     if self.no_hundred_eth: return None
        #     transfer_event['amount'] = 100 * (10 ** 18)
        #     transfer_event['decimals'] = 18
        #     transfer_event['symbol'] = 'ETH'
        #     transfer_event['eth_transfer_amount'] = 100
        #     transfer_event['from'] = transaction['from']
        #     transfer_event['to'] = transaction['to']
        # else:
        #     # Find all Transfer events in this transaction
        #     token_transfer_events = transfer_parser.search_transfers_in_receipt(receipt)
        #     if token_transfer_events == None:
        #         return None
        #     transfer_event = transfer_parser.analyze_biggest_transfer(self.w3, token_transfer_events)
        
        # if transfer_event is None:
        #     print("[ERROR] Unhandled Transfer or something at tx: {}"
        #     .format(transaction['transactionHash']))

        # # This transfer amount converted inside of analyze_biggest_transfer
        # if transfer_event['eth_transfer_amount'] < self.eth_limit:
        #     return None
        
        # # This string is already formatted for Telegram
        # # `` code, ** - Bold, _ _ - Italic. Hashtag before words(not numbers tho) will make it clickable.  
        # text = (
        #     '*#{}, #{} index: {}*'
        #     '\n*Hash:* `{}`'
        #     '\n*Sender:* `{}`\n*Amount:* _{} {} => {} ETH_'
        #     # Overall profit, different strings generated for flashbot transactions 
        #         .format(
        #             self.event_name, event['blockNumber'], event['transactionIndex'],
        #             event['transactionHash'].hex(),
        #             transfer_event['from'],
        #             transfer_event['amount'] / (10 ** transfer_event['decimals']), transfer_event['symbol'],
        #             transfer_event['eth_transfer_amount']
        #         ))
        
        # print("Handler {} formed message: {}, sending to tg...".format(self.event_name, text))
        
        # if self.text_telegram:
        #     telegram_bot.send_msg_to_all(text)
