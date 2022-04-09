import signal
import sys
import time

from eth_typing.evm import BlockNumber
from web3 import Web3
import json
from datetime import datetime
import os
from dotenv import load_dotenv, find_dotenv
import argparse
import traceback
from web3connect import Web3Connect

from handlers.tornado_deposit_handler import DepositEventHandler
from handlers.tornado_withdraw_handler import WithdrawEventHandler
from handlers.aave_liquidation_handler import AAVELiquidationEventHandler

import event_signatures

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

def route_event(event):
    event_sig = event.topics[0].hex()
     
    for handler in HANDLERS:
        # If we have handler for this exact topic - we call his function
        if event_sig == handler.get_event_signature():
            handler.handle_event(event)
    
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
    # Generate all basic event sigs 
    event_signatures.generate_event_signatures(w3)

    # Instance all handlers
    deposit_handler = DepositEventHandler(w3)
    withdraw_handler = WithdrawEventHandler(w3)
    aave_liquidation_handler = AAVELiquidationEventHandler(w3)
    global HANDLERS 
    HANDLERS = [ withdraw_handler, deposit_handler ]
    
    all_events = event_signatures.get_event_signatures()

    for handler in HANDLERS:
        # We append to default events all events from new handlers
        all_events[handler.get_name()] = handler.get_event_signature() 
        event_signatures.add_to_event_sigs(w3, handler.get_name(), handler.get_event_signature())
    # event_sigs.g
    # all_first_topics = list(EXISTING_EVENTS.keys())
    print(all_events)
    global atoken_abi
    atoken_abi = json.load(open("consts/AAVE/ABI_aToken.json"))
    global lending_pool_abi
    lending_pool_abi = json.load(open("consts/AAVE/ABI_aave_lending_pool.json"))
    global usdc_abi
    usdc_abi = json.load(open("consts/ABI_USDC.json")) 

    global AGGR

    if (ARGS.go_to_past):
        event_filter = w3.eth.filter({
            # Proxy
            "fromBlock": 'latest',
            "topics": [list(all_events.values()), None]
        })
        poll_interval = 15
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
    step_size = 10
    print("Running from {} to {}".format(start_block, end_block))
    current_start_block = start_block
    
    while (current_start_block <= end_block):
        print("+1")
        current_end_block = current_start_block + step_size - 1
        if current_end_block > end_block:
            current_end_block = end_block

        event_filter = w3.eth.filter({
            # Proxy
            "fromBlock": current_start_block,
            "toBlock": current_end_block,
            "topics": [list(all_events.values()), None]
        })

        failed = True
        ntries = 0
        # print("Processing blocks from {} to {}".format(current_start_block, current_end_block))
        while((failed or ntries == 0) and ntries < 10):
            failed = True
            try:
                for event in event_filter.get_all_entries():
                    print(event)
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





