import signal
import sys
import time

from eth_typing.evm import BlockNumber
from web3 import Web3
import json
from datetime import datetime
import os
from dotenv import load_dotenv, find_dotenv
import tx_parser
import argparse
import traceback
from web3connect import Web3Connect
import requests
import tx_parser
import chainlink
import telegram_bot
from handlers.tornado_deposit_handler import DepositEventHandler
from handlers.tornado_withdraw_handler import WithdrawEventHandler

# Approx. block number of moving Compound to Chainlink oracle
# BLOCK_NUMBER = 12859160
# no keys for realtime events parsing
parser = argparse.ArgumentParser(description='No arguments for realtime mode')
parser.add_argument('--from-block', type=int, help='submit starting block for liquidation events parsing')
parser.add_argument('--to-block', type=int, help='submit ending block for liquidation events parsing')
parser.add_argument('--go-to-past', action="store_false", help="when set, code will parse old")

# GLOBALS (FIXME later)
w3 = None
ctoken_abi = None
comptroller_abi = None
usdc_abi = None

tokens_cache = {}
AGGR = {}

# LOADING FEEDS DATA FROM JSON FILE
# file can be rebuilt by "chainlink_renew_and_store_feeds_info_in_json()" function
FEED_TO_PAIR_JSON_FILE = "consts/chainlink_feed_info_by_addr.json"
global FEEDS_DATA_BY_ADDR
FEEDS_DATA_BY_ADDR = json.load(open(FEED_TO_PAIR_JSON_FILE))

def parse_data_from_liq_event(liquidation_event):
    data = {}
    data['blockNumber'] = liquidation_event['blockNumber']
    data['index'] = liquidation_event['transactionIndex']
    data['liquidator'] = tx_parser.aave_get_liqAddr(liquidation_event.data, w3)
    data['collateral_amount'] = tx_parser.aave_get_seized_amount(liquidation_event.data)
    data['collateral_addr'] = w3.toChecksumAddress(liquidation_event.topics[1].hex()[-40:])
    data['debt_amount'] = tx_parser.aave_get_repay_amount(liquidation_event.data)
    data['debt_addr'] = w3.toChecksumAddress(liquidation_event.topics[2].hex()[-40:])
    data['borrower'] = w3.toChecksumAddress(liquidation_event.topics[3].hex()[-40:])
    data['txhash'] = liquidation_event.transactionHash.hex()
    return data

def get_last_answer_in_feed(asset_info, tx_block_number, tx_index):
    default_result = {
            'answer': 0,
            'blockNumber': 0,
            'txhash': 0,
            'index': 0,
            'same_block_as_transaction': False
        }    

    if asset_info['symbol'] == 'WETH':
        return default_result
    
    end_block_number = tx_block_number
    same_block_as_transaction = False
    start_block_number = end_block_number - 2000
    sanity_counter = 0
    while True:
        # If we can't find price in 40000 blocks - something is definitely wrong)
        sanity_counter = sanity_counter + 1
        if sanity_counter > 20:
            print("[ERROR] Unable to find price for {} in feed {}"
                .format(asset_info['price_feed'], asset_info['price_feed']))
            return default_result

        event_filter_price_change = w3.eth.filter({
            "fromBlock": start_block_number,
            "toBlock": end_block_number,
            "topics": [chainlink_transmit_price_change_sig],
            "address": asset_info['price_feed']
        })
        entries = event_filter_price_change.get_all_entries()
        if entries == []:
            end_block_number = start_block_number
            start_block_number = end_block_number - 2000
            continue

        latest_price_event = entries[len(entries)-1]
        # TODO too much if's, consider refactor?
        # If it's the same block
        if latest_price_event['blockNumber'] == tx_block_number:
            # Index of price change must be lower
            if latest_price_event['transactionIndex'] > tx_index:
                # If the only one entry, and it was after liq - skip it
                if len(entries) == 1:
                    end_block_number = start_block_number
                    start_block_number = end_block_number - 2000
                    continue
                # If there is something else, we use it instead
                else:
                    latest_price_event = entries[len(entries)-2]
            else:
                same_block_as_transaction = True
                # print(
                #     '[WARN] Price for {} changed in same block as liquidation, possible bundle!'
                #     '\nprice change index: {}, liquidation index: {}'
                #         .format(asset_info['symbol'], 
                #         latest_price_event['transactionIndex'], liquidation_data['index'])
                #  )
        
        return {
            # convert latest price for asset in event to integer
            'answer': int(latest_price_event.topics[1].hex(), base=16),
            'blockNumber': latest_price_event.blockNumber,
            'txhash': latest_price_event.transactionHash.hex(),
            'index': latest_price_event.transactionIndex,
            'same_block_as_transaction': same_block_as_transaction,
        }

def get_info_from_flashbots(txhash, block_number):
    transaction = {}
    try:
        response = requests.get("https://blocks.flashbots.net/v1/blocks?block_number={}".format(block_number))
        data = response.json()
        if not data.get('blocks'):
            return (None, None, None)
        for block in data['blocks']:
            for tx in block['transactions']:
                if tx['transaction_hash'] == txhash:
                    transaction = tx
    except:
        return (None, None, None)
    if transaction == {}:
        return (None, None, None)
    
    miner_reward = int(transaction['total_miner_reward']) / (10 ** 18)

    parsed_tx = ('FLASHBOTS_TX, bundle_type: {}, bundle_index: {}, bribe_amount: {:.4f} ETH, is_megabundle: {}'
    .format(transaction['bundle_type'], transaction['bundle_index'], miner_reward, transaction.get('is_megabundle', False)))

    info = {'bundle_type': transaction['bundle_type'],
            'bundle_index': transaction['bundle_index'],
            'bribe_amount': transaction['total_miner_reward'],
            'is_megabundle': transaction.get('is_megabundle', False)
            }
    
    return (parsed_tx, miner_reward, info)


def get_block_timestamp(block_number):
    block = w3.eth.get_block(block_number)
    timestamp = block['timestamp']
    return datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

def route_event(event):
    event_sig = event.topics[0].hex()
    event_name = EXISTING_EVENTS.get(event_sig)
    if event_name == None:
        print("[ERROR] Unknown event signature {}".format(event_sig))
        return None
    if event_name == "aave liquidation":
        handle_liquidation_event(event)
    elif event_name == "tornado deposit":
        handle_tornado_deposit(event)
    elif event_name == "tornado withdrawal":
        handle_tornado_withdrawal(event)
    else:
        print("unknown shit dunno")

def handle_tornado_deposit(deposit_event):
    receipt = w3.eth.getTransactionReceipt(deposit_event['transactionHash'])
    transaction = w3.eth.getTransaction(deposit_event['transactionHash'])
    transfer_event = dict()
    # TODO move restrictions to library
    # Exception for 100 ETH, we can't track it directly from tx
    if deposit_event.address == '0xA160cdAB225685dA1d56aa342Ad8841c3b53f291':
        transfer_event['amount'] = 100 * (10 ** 18)
        transfer_event['decimals'] = 18
        transfer_event['symbol'] = 'ETH'
        transfer_event['eth_transfer_amount'] = 100
        transfer_event['from'] = transaction['from']
        transfer_event['to'] = transaction['to']
    else:
        # Find all Transfer events in this transaction
        token_transfer_events = search_transfers_in_receipt(receipt)
        if token_transfer_events == None:
            return None
        transfer_event = analyze_biggest_transfer(token_transfer_events)
        # asset_symbol = 'ETH'
    if transfer_event is None:
        print("[ERROR] Unhandled Transfer or something at tx: {}"
        .format(transaction['transactionHash']))

    # This string is already formatted for Telegram
    # `` code, ** - Bold, _ _ - Italic. Hashtag before words(not numbers tho) will make it clickable.  
    text = (
        '*#Tornado_deposit, #{} index: {}*'
        '\n*Hash:* `{}`'
        '\n*Sender:* `{}`\n*Amount:* _{} {} => {} ETH_'
         # Overall profit, different strings generated for flashbot transactions 
            .format(
                deposit_event['blockNumber'], deposit_event['transactionIndex'],
                deposit_event['transactionHash'].hex(),
                transfer_event['from'],
                transfer_event['amount'] / (10 ** transfer_event['decimals']), transfer_event['symbol'],
                transfer_event['eth_transfer_amount']
            ))
    print(text)
    
    telegram_bot.send_msg_to_all(text)

def handle_tornado_withdrawal(withdrawal_event):
    receipt = w3.eth.getTransactionReceipt(withdrawal_event['transactionHash'])
    transaction = w3.eth.getTransaction(withdrawal_event['transactionHash'])
    transfer_event = dict()
    # TODO move restrictions to library
    # Exception for 100 ETH, we can't track it directly from tx
    if withdrawal_event.address == '0xA160cdAB225685dA1d56aa342Ad8841c3b53f291':
        transfer_event['amount'] = 100 * (10 ** 18)
        transfer_event['decimals'] = 18
        transfer_event['symbol'] = 'ETH'
        transfer_event['eth_transfer_amount'] = 100 
        transfer_event['from'] = transaction['from']
        transfer_event['to'] = transaction['to']
    else:
        # Find all Transfer events in this transaction
        token_transfer_events = search_transfers_in_receipt(receipt)
        if token_transfer_events == None:
            return None
        transfer_event = analyze_biggest_transfer(token_transfer_events)
        # asset_symbol = 'ETH'
    if transfer_event is None:
        print("[ERROR] Unhandled Transfer or something at tx: {}"
        .format(transaction['transactionHash']))
    # `` code, ** - Bold, _ _ - Italic. Hashtag before words(not numbers tho) will make it clickable.  
    text = (
        '*#Tornado_withdrawal, #{} index: {}*\n*Hash:* `{}`'
        '\n*Receiver:* `{}`\n*Amount:* _{} {} => {} ETH_'
         # Overall profit, different strings generated for flashbot transactions 
            .format(
                withdrawal_event['blockNumber'], withdrawal_event['transactionIndex'],
                withdrawal_event['transactionHash'].hex(),
                transfer_event['from'],
                transfer_event['amount'] / (10 ** transfer_event['decimals']), transfer_event['symbol'],
                transfer_event['eth_transfer_amount']
            ))
    print(text)
    telegram_bot.send_msg_to_all(text)

def search_transfers_in_receipt(receipt):
    something_found = False
    token_transfer_events = list()
    for log in receipt.logs:
        if log.topics[0].hex() == transfer_event:
            something_found = True
            token_transfer_events.append(log)
    if not something_found: 
        # no ERC20 transfers
        return None
    return token_transfer_events

# Finds the biggest transfer, returns struct with fields TODO write them here
# TODO split
def analyze_biggest_transfer(token_transfer_events):
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
        transfer_price_info = get_last_answer_in_feed(
            asset_info, 
            token_transfer_event['blockNumber'], 
            token_transfer_event['transactionIndex']
        )
        # Recalc to ETH
        transfer_amount_eth = calculate_asset_profit(
            token_amount, 
            transfer_price_info['answer'], 
            asset_info['decimals'], 
            token_symbol
        )
        # Finding the biggest transfer in whole transaction (Usually there is 2-3)
        if biggest_transfer_eth < transfer_amount_eth:
            transfer_information['amount'] = token_amount
            transfer_information['decimals'] = asset_info['decimals']
            transfer_information['symbol'] = token_symbol
            transfer_information['eth_transfer_amount'] = transfer_amount_eth
            transfer_information['token'] = token_addr
            transfer_information['from'] = token_from
            transfer_information['to'] = token_to

    return transfer_information

def handle_liquidation_event(liquidation_event):

    # Parse all stuff from event
    receipt = w3.eth.getTransactionReceipt(liquidation_event['transactionHash'])
    liquidation_data = parse_data_from_liq_event(liquidation_event)
    # Also add gas used from tx receipt
    liquidation_data['txfee'] = int(receipt['effectiveGasPrice'] * receipt['gasUsed'])
    
    collateral_asset_info = None
    debt_asset_info = None
    # Exception for WETH, as he does not have any price providers
    if liquidation_data['collateral_addr'] == '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2':
        collateral_asset_info = {
            'symbol': 'WETH',
            'decimals': 18
        }

    if liquidation_data['debt_addr'] == '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2':
        debt_asset_info = {
            'symbol': 'WETH',
            'decimals': 18
        }

    # Find feeds addresses for debt and collateral
    if collateral_asset_info == None:
        collateral_asset_info = chainlink.get_asset_info(liquidation_data['collateral_addr'])
    if debt_asset_info == None:
        debt_asset_info = chainlink.get_asset_info(liquidation_data['debt_addr'])

    if collateral_asset_info == None or debt_asset_info == None:
        print("[ERROR] Unable to find price provider for collateral({}) or debt {} in liquidation"
            .format(collateral_asset_info, debt_asset_info))
        return None
    
    # Now we check AnswerUpdated events, finding closest to liquidation
    # TODO - it was written for analysis of SINGLE liquidation
    # and is very ineffective and slow (performing price change lookup backward for EACH liquidation)
    collateral_latest = get_last_answer_in_feed(
        collateral_asset_info, 
        liquidation_data['blockNumber'], 
        liquidation_data['index']
    )
    debt_latest = get_last_answer_in_feed(
        debt_asset_info,  
        liquidation_data['blockNumber'], 
        liquidation_data['index']
    )

    # Format output to match the timeline
    print("###################################################################################")
    latest_price_change = debt_latest
    if collateral_latest['blockNumber'] >= debt_latest['blockNumber']:
        latest_price_change_bn = collateral_latest

        formatted_print_price_change(debt_latest, debt_asset_info)
        formatted_print_price_change(collateral_latest, collateral_asset_info)
    else: 
        formatted_print_price_change(collateral_latest, collateral_asset_info)
        formatted_print_price_change(debt_latest, debt_asset_info)
    
    profit_collateral = calculate_asset_profit(
        liquidation_data['collateral_amount'], 
        collateral_latest['answer'], 
        collateral_asset_info['decimals'], 
        collateral_asset_info['symbol']
    )
    profit_debt = calculate_asset_profit(
        liquidation_data['debt_amount'], 
        debt_latest['answer'], 
        debt_asset_info['decimals'], 
        debt_asset_info['symbol']
    ) 
    gasCalculated = calculate_asset_profit(liquidation_data['txfee'], 0, 18, 'WETH')
    
    (flashbots_info, bribe, fbinfo) = get_info_from_flashbots(liquidation_data['txhash'], liquidation_data['blockNumber'])
    
    if flashbots_info != None and bribe != None:
        price_calc_string = ('*Profit:* seized: {:.4f} repayed: {:.4f} pure: {:.4f} fee: {:.4f} bribe {:.4f} ({:.1f}%) total: _{:.4f} ETH_'
            .format(profit_collateral, profit_debt, (profit_collateral - profit_debt), gasCalculated, bribe, 
                    bribe / (profit_collateral - profit_debt) * 100,
                    profit_collateral - profit_debt - gasCalculated - bribe))
    else:
        price_calc_string = ('*Profit:* seized: {:.4f} repayed: {:.4f} pure: {:.4f} fee: {:.4f} bribe 0.0000 (0.0%) total: _{:.4f} ETH_'
            .format(profit_collateral, profit_debt, (profit_collateral - profit_debt), gasCalculated, 
                    profit_collateral - profit_debt - gasCalculated))

    # `` code, ** - Bold, _ _ - Italic. Hashtag before words(not numbers tho) will make it clickable.  
    text = (
        '\n*#AAVE_liquidation, #{} index: {}*'
        '\n*Hash:* `{}`' 
        '\n*Borrower:* `{}`'
        '\n*Liquidator:* `{}`'
        '\n*Repay:* _{:.4f} {}_\n*Seize:* _{:.4f} {}_'
        '\n*Flashbots:*  {}'
        '\n{}' # Overall profit, different strings generated for flashbot transactions 
        '\n*Last price change:* `{}`'
        '\n*Diff in blocks:* {}'
            .format(
                liquidation_data['blockNumber'], liquidation_data['index'],
                liquidation_data['txhash'],
                liquidation_data['borrower'],
                liquidation_data['liquidator'],
                liquidation_data['debt_amount'] / (10 ** debt_asset_info['decimals']), debt_asset_info['symbol'],
                liquidation_data['collateral_amount'] / (10 ** collateral_asset_info['decimals']), collateral_asset_info['symbol'],
                flashbots_info,
                price_calc_string,
                latest_price_change['txhash'],
                liquidation_data['blockNumber'] - latest_price_change['blockNumber'],
            ))
    print(text)
    telegram_bot.send_msg_to_all(text)
    
def calculate_asset_profit(amount, latest_price, decimals, symbol):
    if symbol == 'WETH':
        return amount / (10 ** decimals)
    # decimals for token and for X / ETH price oracle is always 18
    return (amount * latest_price) / (10 ** (decimals + 18))

def formatted_print_price_change(asset_latest, asset_info):
    if asset_info['symbol'] == 'WETH':
        # print('WETH does not change it\'s price to ETH, skipping..')
        return
    (flashbots_info, bribe, fbinfo) = get_info_from_flashbots(asset_latest['txhash'], asset_latest['blockNumber'])

    print(
        '[PRICE_CHANGE, {} #{} index:  {}, same block as liquidation: {}]'
        '\n[TXHASH]:     {}'
        '\n[ASSET]:      {} / ETH price changed to {:.4f}'
        '\n[FLASHBOTS]:  {}' 
            .format(
                get_block_timestamp(asset_latest['blockNumber']), asset_latest['blockNumber'], asset_latest['index'],
                asset_latest['same_block_as_transaction'],
                asset_latest['txhash'],
                asset_info['symbol'], asset_latest['answer'] / (10 ** 18),
                flashbots_info,
            )   
    )

def main():
    # exit by Ctrl+C
    signal.signal(signal.SIGINT, lambda signal,frame: { print("Interrupt by SIGINT"), sys.exit(0)})
    print('starting')
    global w3
    load_dotenv(find_dotenv())
    infuraAddr = os.environ.get("NODE_BASE_ENDPOINT") + os.environ.get("NODE_API_KEY")
    w3 = Web3(Web3.WebsocketProvider(infuraAddr))
    if not w3.isConnected():
        print('Node is not connected')
        exit()
    
    ARGS = parser.parse_args()

    exit()

    global cdp_aave_liquidate_event_sig
    cdp_aave_liquidate_event_sig = w3.keccak(text="LiquidationCall(address,address,address,uint256,uint256,address,bool)").hex()
    
    global chainlink_transmit_price_change_sig 
    chainlink_transmit_price_change_sig = w3.keccak(text="AnswerUpdated(int256,uint256,uint256)").hex()


    global atoken_abi
    atoken_abi = json.load(open("consts/AAVE/ABI_aToken.json"))
    global lending_pool_abi
    lending_pool_abi = json.load(open("consts/AAVE/ABI_aave_lending_pool.json"))
    global usdc_abi
    usdc_abi = json.load(open("consts/ABI_USDC.json")) 

    global AGGR
    # Forming list of all event's signatures
    # AAVE liquidation
    aave_liquidation_event = w3.keccak(text="LiquidationCall(address,address,address,uint256,uint256,address,bool)").hex()
    # Tornado funds depositing
    tornado_deposit_event = w3.keccak(text="Deposit(bytes32,uint32,uint256)").hex()
    # Tornado funds withdrawal
    tornado_withdrawal_event = w3.keccak(text="Withdrawal(address,bytes32,address,uint256)").hex()

    global transfer_event
    transfer_event = w3.keccak(text="Transfer(address,address,uint256)").hex()
    global EXISTING_EVENTS
    
    EXISTING_EVENTS = {
        aave_liquidation_event: "aave liquidation",
        tornado_deposit_event: "tornado deposit",
        tornado_withdrawal_event: "tornado withdrawal",

    }
    all_first_topics = list(EXISTING_EVENTS.keys())
    
    if (ARGS.go_to_past):
        event_filter = w3.eth.filter({
            # Proxy
            "fromBlock": 'latest',
            "topics": [all_first_topics, None]
            # "topics": [tornado_deposit_event_sig]

        })
        poll_interval = 20
        while True:
            try:
                for event in event_filter.get_new_entries():
                    print('routing {}'.format(event))
                    route_event(event)
            except Exception as e:
                    # TODO add erroneous events handling, skip for now
                    print("[ERROR] {} in handle events: {}. Event: {}".format(type(e).__name__, e, event))
                    continue
            time.sleep(poll_interval)

    # ~ 6400 blocks/day
    start_block = w3.eth.block_number - 6400 * 100
    end_block = w3.eth.block_number
    step_size = 1000
    print("Running from {} to {}".format(start_block, end_block))
    current_start_block = start_block
    


    while (current_start_block <= end_block):
        current_end_block = current_start_block + step_size - 1
        if current_end_block > end_block:
            current_end_block = end_block

        event_filter = w3.eth.filter({
            # Proxy
            "fromBlock": current_start_block,
            "toBlock": current_end_block,
            "topics": [all_first_topics, None]
            # "topics": [tornado_deposit_event_sig]

        })

        failed = True
        ntries = 0
        # print("Processing blocks from {} to {}".format(current_start_block, current_end_block))
        while((failed or ntries == 0) and ntries < 10):
            failed = True
            try:
                for event in event_filter.get_all_entries():
                    route_event(event)
                failed = False
                ntries = 0
                break
            except Exception as e:
                print("[ERROR] {} in handle events: {}. Event: {}".format(type(e).__name__, e, event))
                traceback.print_exc()
                # print("Sleeping 5 sec...")
                # time.sleep(6)
                ntries += 1
                failed = True

        if (failed == True):
            print("Skipping blocks from {} to {}, trying next pack".format(current_start_block, current_end_block))

        current_start_block = current_end_block + step_size

if __name__ == '__main__':
    main()





