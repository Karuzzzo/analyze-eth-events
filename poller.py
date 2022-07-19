from web3connect import Web3Connect
from web3 import Web3
from web3.eth import AsyncEth
from dotenv import load_dotenv, find_dotenv
import os
import signal
import time 
import asyncio 

async def main():
    # exit by Ctrl+C
    signal.signal(signal.SIGINT, lambda signal,frame: { print("Interrupt by SIGINT"), sys.exit(0)})
    # Connect node
    global w3
    global current_block_number
    load_dotenv(find_dotenv())
    nodeAddr = os.environ.get("NODE_ENDPOINT")
    # w3 = Web3(Web3.WebsocketProvider(nodeAddr))
    w3 = Web3(Web3.AsyncHTTPProvider("NODE_ENDPOINT"), modules={'eth': (AsyncEth,)}, middlewares=[])

    if not await w3.isConnected():
        print('Node is not connected')
        exit()

    current_block_number = w3.eth.blockNumber
    # while True:
    #     print(time.clock_gettime_ns(0))

    # Make async loop
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    loop.close()
async def request_coinbase_and_measure_time():

    return w3.eth.coinbase

if __name__ == '__main__':
    asyncio.run(main())