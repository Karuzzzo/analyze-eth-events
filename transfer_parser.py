import chainlink
import tx_parser
import event_signatures

# Transfer event signature
ALL_EVENT_SIGS = event_signatures.get_event_signatures()

def search_transfers_in_receipt(receipt):
    something_found = False
    token_transfer_events = list()
    for log in receipt.logs:
        if log.topics[0].hex() == ALL_EVENT_SIGS['transfer']:
            something_found = True
            token_transfer_events.append(log)
    if not something_found: 
        # no ERC20 transfers
        return None
    return token_transfer_events

# Finds the biggest transfer, returns struct with fields TODO write them here
# TODO split
def analyze_biggest_transfer(w3, token_transfer_events):
    asset_amount = None
    asset_symbol = None
    biggest_transfer_eth = 0
    transfer_information = dict()

    for token_transfer_event in token_transfer_events:
        token_amount = tx_parser.get_amount_from_transfer_event(token_transfer_event)
        token_addr = tx_parser.get_token_from_transfer_event(token_transfer_event, w3)
        token_from = tx_parser.get_sender_from_transfer_event(token_transfer_event, w3)
        token_to = tx_parser.get_receiver_from_transfer_event(token_transfer_event, w3)

        token_symbol = chainlink.get_symbol_by_addr(token_addr)
        asset_info = chainlink.get_asset_info(token_addr)
        # Get token price to ETH
        transfer_price_info = chainlink.get_last_answer_in_feed(
            w3,
            asset_info, 
            token_transfer_event['blockNumber'], 
            token_transfer_event['transactionIndex']
        )

        # Calc ETH with decimals
        if token_symbol == 'WETH':
            transfer_amount_eth = token_amount / (10 ** asset_info['decimals'])
        else: # decimals for token and for X / ETH price oracle is always 18
            transfer_amount_eth = (token_amount * transfer_price_info['answer']) / (10 ** (asset_info['decimals'] + 18))
        # Finding the biggest transfer in whole transaction (Usually there is 2-3)
        if biggest_transfer_eth < transfer_amount_eth:
            biggest_transfer_eth = transfer_amount_eth

            transfer_information['amount'] = token_amount
            transfer_information['decimals'] = asset_info['decimals']
            transfer_information['symbol'] = token_symbol
            transfer_information['eth_transfer_amount'] = transfer_amount_eth
            transfer_information['token'] = token_addr
            transfer_information['from'] = token_from
            transfer_information['to'] = token_to

    return transfer_information
