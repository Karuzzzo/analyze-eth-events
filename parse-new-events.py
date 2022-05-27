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
parser.add_argument('--go-to-past', action="store_true", help="when set, code will parse old")
#  TODO 
# parser.add_argument('--send-to-telegram')
tokens_cache = {}

# LOADING FEEDS DATA FROM JSON FILE
# file can be rebuilt by "chainlink_renew_and_store_feeds_info_in_json()" function
FEED_TO_PAIR_JSON_FILE = "consts/chainlink_feed_info_by_addr.json"
global FEEDS_DATA_BY_ADDR
FEEDS_DATA_BY_ADDR = json.load(open(FEED_TO_PAIR_JSON_FILE))

async def log_loop(event_filter, poll_interval):
    while True:
        try:
            for event in event_filter.get_new_entries():
                # print('routing {}'.format(event))
                await route_event(event)
        except Exception as e:
                # TODO add erroneous events handling, skip for now
                print("[ERROR] {} in handle events: {}. Event: {}".format(type(e).__name__, e, event))
                traceback.print_exc()
                continue
        await asyncio.sleep(poll_interval)

async def log_all(event_filter):
    failed = True
    ntries = 0
    while ((failed or ntries == 0) and ntries < 10):
        failed = True
        try:
            for event in event_filter.get_all_entries():
                # print(event)
                await route_event(event)
            failed = False
            ntries = 0
            break
        except Exception as e:
            print("[ERROR] {} in handle events: {}. Event: {}".format(type(e).__name__, e, event))
            traceback.print_exc()
            print("Sleeping 5 sec...")
            await asyncio.sleep(5)
            ntries += 1
            failed = True

async def route_event(event):
    event_sig = event.topics[0].hex()
     
    for handler in HANDLERS:
        # If we have handler for this exact topic - we call his function
        if event_sig == handler.get_event_signature():
            # If handler contains heavy requests and async - await it
            if inspect.iscoroutinefunction(handler.handle_event):
                await handler.handle_event(event)
            else:
                handler.handle_event(event)
            return repr(handler)
    
    return None

def main():
    # exit by Ctrl+C
    signal.signal(signal.SIGINT, lambda signal,frame: { print("Interrupt by SIGINT"), sys.exit(0)})
    # Connect node
    global w3
    load_dotenv(find_dotenv())
    nodeAddr = os.environ.get("NODE_BASE_ENDPOINT") + os.environ.get("NODE_API_KEY")
    w3 = Web3(Web3.WebsocketProvider(nodeAddr))
    if not w3.isConnected():
        print('Node is not connected')
        exit()
    
    # Parse events
    ARGS = parser.parse_args()
    # Generate all basic event sigs 
    event_signatures.generate_event_signatures(w3)
    
    # VVV...IMPORT NEW HANDLERS HERE...VVV
    # Instance all handlers
    global HANDLERS 
    HANDLERS = [ 
        DepositEventHandler(w3, eth_limit=30, no_hundred_eth=True), 
        WithdrawEventHandler(w3, eth_limit=30, no_hundred_eth=True),
        AAVELiquidationEventHandler(w3, eth_limit=10),
        # IpfsEventHandler(w3)
    ]
    list_of_events = list()

    for handler in HANDLERS:    
        # We also add all signatures from handlers, might use them later 
        event_signatures.add_to_event_sigs(w3, repr(handler), handler.get_event_signature())
        list_of_events.append(handler.get_event_signature())

    print('Listening for: {}'.format(', '.join(map(lambda h: repr(h), HANDLERS))))

    if not ARGS.go_to_past:

        print('Started listening for new events...')
        print("=" * 80)

        event_filter = w3.eth.filter({
            "fromBlock": 'latest',
            "topics": [list_of_events, None]
        })
        poll_interval = 15
        loop = asyncio.get_event_loop()
        try:
            loop.run_until_complete(
                asyncio.gather(
                    log_loop(event_filter, poll_interval)
                )
            )
        finally: loop.close()
        
        exit()
    # TODO Implement async for various time intervals aswell
    # ~ 6400 blocks/day
    start_block = 14051788 - 6400 * 100
    end_block = w3.eth.block_number
    # start_block = 14051788
    # end_block = 14053787

    step_size = 2000
    current_start_block = start_block

    # Some statistics
    total_chunks = math.ceil((end_block - start_block) / step_size)
    current_chunk = 0
    print("Running from {} to {}, chunk length: {} blocks, total: {} block chunks"
            .format(start_block, end_block, step_size, total_chunks))
    print("=" * 80)
    total_filtered = 0

    while (current_start_block <= end_block):
        current_end_block = current_start_block + step_size - 1
        if current_end_block > end_block:
            current_end_block = end_block
        
        event_filter = w3.eth.filter({
            # Proxy
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

        loop = asyncio.get_event_loop()
        # try:
        loop.run_until_complete(
            asyncio.gather(
                log_all(event_filter)
            )
        )

        # finally: loop.close()
        
        # print("Processing blocks from {} to {}".format(current_start_block, current_end_block))
        
        current_start_block = current_end_block + step_size
        current_chunk = current_chunk + 1

if __name__ == '__main__':
    main()





