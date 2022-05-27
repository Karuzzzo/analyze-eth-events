import telegram_bot
import transfer_parser
import event_signatures
from handlers.handler_interface import handlerInterface

class WithdrawEventHandler(handlerInterface):
    def __init__(self, w3, eth_limit, no_hundred_eth=False, text_telegram=False) -> None:
        event_sig_text = "Withdrawal(address,bytes32,address,uint256)"
        self.w3 = w3
        self.event_name = 'Tornado withdrawal()'
        self.eth_limit = eth_limit
        self.no_hundred_eth = no_hundred_eth
        self.text_telegram = text_telegram
        self.event_signature = w3.keccak(text=event_sig_text).hex()
        # Add it to global json w signatures

    def __repr__(self):
        return self.event_name

    def get_event_signature(self):
        return self.event_signature

    def handle_event(self, withdrawal_event):
        receipt = self.w3.eth.getTransactionReceipt(withdrawal_event['transactionHash'])
        transaction = self.w3.eth.getTransaction(withdrawal_event['transactionHash'])
        transfer_event = dict()
        # TODO move restrictions to library
        # Exception for 100 ETH, we can't track it directly from tx
        if withdrawal_event.address == '0xA160cdAB225685dA1d56aa342Ad8841c3b53f291':
            if self.no_hundred_eth: return None
            transfer_event['amount'] = 100 * (10 ** 18)
            transfer_event['decimals'] = 18
            transfer_event['symbol'] = 'ETH'
            transfer_event['eth_transfer_amount'] = 100
            transfer_event['from'] = transaction['from']
            transfer_event['to'] = transaction['to']
        else:
            # Find all Transfer events in this transaction
            token_transfer_events = transfer_parser.search_transfers_in_receipt(receipt)
            if token_transfer_events == None:
                return None
            transfer_event = transfer_parser.analyze_biggest_transfer(self.w3, token_transfer_events)
            # asset_symbol = 'ETH'
        if transfer_event is None:
            print("[ERROR] Unhandled Transfer or something at tx: {}"
            .format(transaction['transactionHash']))

        # This transfer amount converted inside of analyze_biggest_transfer
        if transfer_event['eth_transfer_amount'] < self.eth_limit:
            # print("Withdrawwant {} have {} at {}".format(transfer_event['eth_transfer_amount'], self.eth_limit, withdrawal_event['transactionHash'].hex()))
            return None

        # This string is already formatted for Telegram
        # `` code, ** - Bold, _ _ - Italic. Hashtag before words(not numbers tho) will make it clickable.  
        text = (
            '*#{}, #{} index: {}*'
            '\n*Hash:* `{}`'
            '\n*Receiver:* `{}`\n*Amount:* _{} {} => {} ETH_'
            # Overall profit, different strings generated for flashbot transactions 
                .format(
                    self.event_name, withdrawal_event['blockNumber'], withdrawal_event['transactionIndex'],
                    withdrawal_event['transactionHash'].hex(),
                    transfer_event['to'],
                    transfer_event['amount'] / (10 ** transfer_event['decimals']), transfer_event['symbol'],
                    transfer_event['eth_transfer_amount']
                ))
        
        print("Handler {} formed message: {}, sending to tg...".format(self.event_name, text))
        
        if self.text_telegram:
            telegram_bot.send_msg_to_all(text)