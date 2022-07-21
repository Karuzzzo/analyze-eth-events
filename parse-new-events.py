import signal
import sys
import time
import math

from web3 import Web3
import json
from datetime import datetime
import os
from dotenv import load_dotenv, find_dotenv
import argparse
import traceback
from handlers.uniswap_v2_swap_handler import UniswapV2SwapEventHandler
from web3connect import Web3Connect

from handlers.tornado_deposit_handler import DepositEventHandler
from handlers.tornado_withdraw_handler import WithdrawEventHandler
from handlers.aave_liquidation_handler import AAVELiquidationEventHandler
from handlers.ipfs_example_handler import IpfsEventHandler

import event_signatures
import asyncio
import inspect

# Approx. block number of moving Compound to Chainlink oracle
# BLOCK_NUMBER = 12859160
# no keys for realtime events parsing
parser = argparse.ArgumentParser(description='No arguments for realtime mode')
parser.add_argument('--from-block', type=int, help='submit starting block for events parsing')
parser.add_argument('--to-block', type=int, help='submit ending block for events parsing')
parser.add_argument('--chunk-size', type=int, help='size of blocks, downloaded simultaneously')
parser.add_argument('--monitor', action="store_true", help="when set, code will monitor only new events")

#  TODO 
# parser.add_argument('--send-to-telegram')
tokens_cache = {}

# LOADING FEEDS DATA FROM JSON FILE
# file can be rebuilt by "chainlink_renew_and_store_feeds_info_in_json()" function
FEED_TO_PAIR_JSON_FILE = "consts/chainlink_feed_info_by_addr.json"
global FEEDS_DATA_BY_ADDR
FEEDS_DATA_BY_ADDR = json.load(open(FEED_TO_PAIR_JSON_FILE))

def log_loop(event_filter, poll_interval):
    while True:
        try:
            for event in event_filter.get_new_entries():
                # print('routing {}'.format(event))
                route_event(event)
        except Exception as e:
                # TODO add erroneous events handling, skip for now
                print("[ERROR] {} in handle events: {}. Event: {}".format(type(e).__name__, e, event))
                traceback.print_exc()
                continue
        time.sleep(poll_interval)

def log_all(event_filter):
    failed = True
    ntries = 0
    while ((failed or ntries == 0) and ntries < 10):
        failed = True
        try:
            for event in event_filter.get_all_entries():
                # print(event)
                route_event(event)
            failed = False
            ntries = 0
            break
        except Exception as e:
            print("[ERROR] {} in handle events: {}. Event: {}".format(type(e).__name__, e, event))
            traceback.print_exc()
            print("Sleeping 5 sec...")
            time.sleep(5)
            ntries += 1
            failed = True

def route_event(event):
    event_sig = event.topics[0].hex()
     
    for handler in HANDLERS:
        # If we have handler for this exact topic - we call his function
        if event_sig == handler.get_event_signature():
            # If handler contains heavy requests and async - await it
            handler.handle_event(event)
            return repr(handler)
    
    return None

def main():
    # exit by Ctrl+C
    signal.signal(signal.SIGINT, lambda signal,frame: { print("Interrupt by SIGINT"), sys.exit(0)})
    # Connect node
    global w3
    load_dotenv(find_dotenv())
    nodeAddr = os.environ.get("NODE_ENDPOINT")
    w3 = Web3(Web3.WebsocketProvider(nodeAddr))
    if not w3.isConnected():
        print('Node is not connected')
        exit()
    
    ARGS = parser.parse_args()
    # Generate all basic event sigs 
    event_signatures.generate_event_signatures(w3)
    
    # VVV...IMPORT NEW HANDLERS HERE...VVV
    # Instance all handlers
    global HANDLERS 
    HANDLERS = [ 
        # DepositEventHandler(w3, eth_limit=30, no_hundred_eth=False), 
        # WithdrawEventHandler(w3, eth_limit=30, no_hundred_eth=False),
        # AAVELiquidationEventHandler(w3, eth_limit=10),
        # IpfsEventHandler(w3),
        UniswapV2SwapEventHandler(w3, dump_to="consts/swap_routers_bsc.json"),
    ]
    list_of_events = list()
    for handler in HANDLERS:    
        # We also add all signatures from handlers, might use them later 
        event_signatures.add_to_event_sigs(w3, repr(handler), handler.get_event_signature())
        list_of_events.append(handler.get_event_signature())

    print('Listening for: {}'.format(', '.join(map(lambda h: repr(h), HANDLERS))))
    # Realtime mode 
    if ARGS.monitor:
        print('Started listening for new events...')
        print("=" * 80)

        event_filter = w3.eth.filter({
            "fromBlock": 'latest',
            "topics": [list_of_events, None]
        })
        poll_interval = 15
        
        log_loop(event_filter, poll_interval)
        
    # 6400 blocks ~= day
    block_number = w3.eth.blockNumber
    start_block = ARGS.from_block or block_number - 6400 * 2
    end_block = ARGS.to_block or w3.eth.blockNumber
    
    if ARGS.from_block is ARGS.to_block is None:
        print("No parameters supplied, processing latest two days")

    chunk_size = ARGS.chunk_size or 2000
    current_start_block = start_block

    # Some statistics
    total_chunks = math.ceil((end_block - start_block) / chunk_size)
    current_chunk = 0
    print("Running from {} to {}, chunk length: {} blocks, total: {} block chunks"
            .format(start_block, end_block, chunk_size, total_chunks))
    print("=" * 80)

    total_filtered = 0

    while (current_start_block <= end_block):
        current_end_block = current_start_block + chunk_size - 1
        if current_end_block > end_block:
            current_end_block = end_block
        
        event_filter = w3.eth.filter({
            "fromBlock": current_start_block,
            "toBlock": current_end_block,
            "topics": [list_of_events, None]
        })

        total_filtered = len(event_filter.get_all_entries())

        print("({} / {} block chunks) running from {} to {}. Processing total of {} events"
            .format(
                current_chunk,
                total_chunks,
                current_start_block, 
                current_end_block,
                total_filtered
            ))

        log_all(event_filter)

        current_start_block = current_end_block + chunk_size
        current_chunk = current_chunk + 1
        for handler in HANDLERS:
            handler.on_update()

    # call on_close for each handler
    for handler in HANDLERS:
        handler.on_close()

if __name__ == '__main__':
    main()





