from time import time
import requests
from consts import token_decimals, providerConsts, stablecoins
from collections import defaultdict
import json
import math
# TODO datetime for debug, remove later
from datetime import datetime
from bitstring import ConstBitStream

# for generating raw transaction
from eth_account._utils.legacy_transactions import Transaction, encode_transaction
from hexbytes import HexBytes

ADDR_LEN = 40
UINT256_LEN = 32
# consts for compound's data
LIQ_LIQ = 26
LIQ_BOR = ADDR_LEN + 24 + LIQ_LIQ
LIQ_REPAY = ADDR_LEN + 32 + LIQ_BOR
LIQ_CTOKEN = UINT256_LEN + 24 + LIQ_REPAY
LIQ_SEIZED =  ADDR_LEN + 32 + LIQ_CTOKEN

# consts for aave's data

AAVE_LIQ_REPAY = 34
AAVE_LIQ_SEIZED = UINT256_LEN + 32 + AAVE_LIQ_REPAY
AAVE_LIQ_LIQ =  24 + UINT256_LEN + AAVE_LIQ_SEIZED

# TODO there's two types of getters for ~same thing, rename it properly or something

def get_liqAddr(data, w3):
    return w3.toChecksumAddress(data[LIQ_LIQ:LIQ_LIQ + ADDR_LEN])


def get_borAddr(data, w3):
    return w3.toChecksumAddress(data[LIQ_BOR:LIQ_BOR + ADDR_LEN])

def get_repay_amount(data):
    raw = int(data[LIQ_REPAY:LIQ_REPAY + UINT256_LEN], base = 16)
    return raw

def get_cTokenAddr(data, w3):
    return w3.toChecksumAddress(data[LIQ_CTOKEN:LIQ_CTOKEN + ADDR_LEN])

def get_seized_amount(data):
    # From hex to dec
    raw = int(data[LIQ_SEIZED:LIQ_SEIZED + UINT256_LEN], base = 16)
    return raw

# awkward aave functions
def aave_get_repay_amount(data):
    raw = int(data[AAVE_LIQ_REPAY:AAVE_LIQ_REPAY + UINT256_LEN], base = 16)
    return raw

def aave_get_seized_amount(data):
    raw = int(data[AAVE_LIQ_SEIZED:AAVE_LIQ_SEIZED + UINT256_LEN], base = 16)
    return raw

def aave_get_liqAddr(data, w3):
    return w3.toChecksumAddress(data[AAVE_LIQ_LIQ:AAVE_LIQ_LIQ + ADDR_LEN])

def aave_get_atoken_bool(data):
    return data[-1] == "1"


def get_default_tx_info(event):
    data = {}
    data['blockNumber'] = event['blockNumber']
    data['index'] = event['transactionIndex']
    data['txhash'] = event.transactionHash.hex()
    return data

def get_data_from_aave_liquidation(liq_event, w3):
    result = get_default_tx_info(liq_event)
    data = liq_event.data

    result['collateral_amount'] = int(data[AAVE_LIQ_SEIZED:AAVE_LIQ_SEIZED + UINT256_LEN], base = 16)
    result['collateral_addr'] = w3.toChecksumAddress(liq_event.topics[1].hex()[-40:])
    
    result['debt_amount'] = int(data[AAVE_LIQ_REPAY:AAVE_LIQ_REPAY + UINT256_LEN], base = 16)
    result['debt_addr'] = w3.toChecksumAddress(liq_event.topics[2].hex()[-40:])
    
    result['liquidator'] = w3.toChecksumAddress(data[AAVE_LIQ_LIQ:AAVE_LIQ_LIQ + ADDR_LEN])
    result['borrower'] = w3.toChecksumAddress(liq_event.topics[3].hex()[-40:])

    result['receive_a'] = data[-1] == "1"
    return result

# TODO fill it up
def get_data_from_transfer_event(transfer_event, w3):
    result = get_default_tx_info(transfer_event)
    result['amount'] = int(transfer_event.data, base = 16)
    result['token'] = w3.toChecksumAddress(transfer_event.address)
    result['from'] = w3.toChecksumAddress('0x' + transfer_event.topics[1].hex()[-40:])    
    result['to'] = w3.toChecksumAddress('0x' + transfer_event.topics[2].hex()[-40:])    
    
    return result 

def get_flashbots_txs_for_block(block_num):
    flashbots_txs = {}
    try:
        response = requests.get("https://blocks.flashbots.net/v1/blocks?block_number={}".format(block_num))
        data = response.json()
        if not data.get('blocks'):
            return {}
        for block in data['blocks']:
            for tx in block['transactions']:
                flashbots_txs[tx['transaction_hash']] = True
    except:
        return {}
    return flashbots_txs

def parse_aave_reserve_data(w3, conf):
    # parse result of call:
    # conf = aave_lending_pool_v2_contract.functions.getReserveData(token_addr).call()
    # returns:
    # struct ReserveConfigurationMap {
    #   //bit 0-15: LTV
    #   //bit 16-31: Liq. threshold
    #   //bit 32-47: Liq. bonus
    #   //bit 48-55: Decimals
    #   //bit 56: Reserve is active
    #   //bit 57: reserve is frozen
    #   //bit 58: borrowing is enabled
    #   //bit 59: stable rate borrowing enabled
    #   //bit 60-63: reserved
    #   //bit 64-79: reserve factor
    #   uint256 data;
    # }

    conf_bits = ConstBitStream(bytes=w3.toBytes(conf[0][0]))
    conf_bits.bitpos += 32
    liq_bonus_clean = int(conf_bits.read('uint:16'))
    # TODO add more values (not needed now)
    return { 'liq_bonus': liq_bonus_clean }
