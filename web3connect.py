import os
from dotenv import load_dotenv, find_dotenv
from web3 import Web3
from eth_account.account import Account                                                                                       
from web3.middleware import construct_sign_and_send_raw_middleware, geth_poa_middleware

class Web3Connect(object):
    
    def __init__(self):
        # load RPC_URL from .env file
        load_dotenv(find_dotenv())
        if os.environ.get("NODE_BASE_ENDPOINT") is None:
            raise(Exception("Web3 Node connection error: NODE_BASE_ENDPOINT var is not set in .env"))
        if os.environ.get("NODE_API_KEY") is None:
            raise(Exception("Web3 Node connection error: NODE_API_KEY var is not set in .env"))
        rpc_url = os.environ.get("NODE_BASE_ENDPOINT") + os.environ.get("NODE_API_KEY")
        # w3.geth.txpool.content() function is returning huge amount of data, so we increase max size
        self._w3 = Web3(Web3.WebsocketProvider(rpc_url, websocket_timeout=360, websocket_kwargs={"max_size": 650000000}))
        if not self._w3.isConnected():
            raise(Exception("Web3 node connection error"))
 
    def web3(self):
        return self._w3

class AvalancheWeb3Connect(object):
    
    def __init__(self):
        # load RPC_URL from .env file
        load_dotenv(find_dotenv())
        if os.environ.get("AVALANCHE_NODE_BASE_ENDPOINT") is None:
            raise(Exception("Web3 Node connection error: AVALANCHE_NODE_BASE_ENDPOINT var is not set in .env"))
        if os.environ.get("AVALANCHE_NODE_API_KEY") is None:
            raise(Exception("Web3 Node connection error: AVALANCHE_NODE_API_KEY var is not set in .env"))
        rpc_url = os.environ.get("AVALANCHE_NODE_BASE_ENDPOINT") + os.environ.get("AVALANCHE_NODE_API_KEY")
        # w3.geth.txpool.content() function is returning huge amount of data, so we increase max size
        self._w3 = Web3(Web3.WebsocketProvider(rpc_url, websocket_timeout=360, websocket_kwargs={"max_size": 650000000}))
        self._w3.middleware_onion.inject(geth_poa_middleware, layer=0)

        if not self._w3.isConnected():
            raise(Exception("Web3 node connection error"))
 
    def web3(self):
        return self._w3
