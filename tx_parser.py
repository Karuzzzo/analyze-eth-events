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

def get_amount_from_transfer_event(transfer_event):
    return int(transfer_event.data, base = 16)

def get_sender_from_transfer_event(transfer_event, w3):
    address = '0x' + transfer_event.topics[1].hex()[-40:]
    return w3.toChecksumAddress(address)

def get_receiver_from_transfer_event(transfer_event, w3):
    address = '0x' + transfer_event.topics[2].hex()[-40:]
    return w3.toChecksumAddress(address)

def get_token_from_transfer_event(transfer_event, w3):
    return w3.toChecksumAddress(transfer_event.address)

def to_raw_transaction(tx):
    v, r, s = (
        tx["v"],
        int(tx["r"].hex(), base=16),
        int(tx["s"].hex(), base=16),
    )

    return encode_transaction(
        Transaction(
            v=v,
            r=r,
            s=s,
            data=HexBytes(tx["input"]),
            gas=tx['gas'],
            gasPrice=tx["gasPrice"],
            nonce=tx["nonce"],
            to=HexBytes(tx["to"]) if "to" in tx else None,
            value=tx["value"] if "value" in tx else None,
            ),
            (v, r, s),
    )

def unify_decoded_tx(_tx):
    unified_tx = dict()
    unified_tx['nonce'] = _tx['nonce']
    unified_tx['gasPrice'] = _tx['gasprice']
    unified_tx['gas'] = _tx['startgas']
    unified_tx['to'] = _tx['to']
    unified_tx['value'] = _tx['value']
    # TODO input and data both used, not sure what to keep..
    unified_tx['input'] = _tx['data']
    unified_tx['data'] = _tx['data']
    unified_tx['sender'] = _tx['sender']
    unified_tx['hash'] = _tx['hash']

    unified_tx['v'] = _tx['v']
    unified_tx['r'] = HexBytes(_tx['r'])
    unified_tx['s'] = HexBytes(_tx['s'])
    return unified_tx

def to_float(rawAmount, decimals):
    return rawAmount / (10 ** decimals)

def token_to_float(rawAmount, symbol):
    if is_compound_token(symbol):
        return to_float(rawAmount, token_decimals[symbol])
    return rawAmount

def get_exchange_rate(cash, totalBorrows, totalReserves, totalSupply):
    return (cash + totalBorrows - totalReserves) / totalSupply

def convert_to_underlying(cToken, amount, exchangeRate):
    if is_compound_token(cToken):
        cTokenDecimals = token_decimals[cToken]
        underlyingDecimals = token_decimals[cToken[1:]]
        oneCTokenInUnderlying = exchangeRate / (1 * 10 ** (18 + underlyingDecimals - cTokenDecimals))

        return amount * oneCTokenInUnderlying
    # If token is unknown - we keep it as is
    return amount

def is_compound_token(cToken):
    return cToken in token_decimals

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

def calculate_profit(seized, repayed):
    if (seized != 0 and repayed != 0):
        return seized - repayed
    return 0

def same_currency(tokenCurrency, PricePair):
    return tokenCurrency + ' / USD' == PricePair or tokenCurrency + ' / ETH' == PricePair

global chainlink_abi
chainlink_abi = json.load(open("consts/Chainlink/ABI_chainlink.json"))
global feed_abi
feed_abi = json.load(open("consts/Chainlink/ABI_price_feed.json"))

price_providers = {}

# TODO merge get_eth and get_usd
def get_eth_price(w3, symbol, blockTimestamp, amount, floatOutput = True):
    if symbol == 'WETH' or symbol =='ETH':
        return wrapped_return(amount * (10**18), 18, floatOutput)
    if symbol == 'WBTC':
        symbol = 'BTC'
    # Chainlink name sUSD in lowercase for USD, and uppercase (SUSD) for ETH, see:
    # https://data.chain.link/ethereum/mainnet/stablecoins/susd-usd
    # https://data.chain.link/ethereum/mainnet/stablecoins/susd-eth
    if symbol == 'sUSD':
        symbol = 'SUSD'

    if symbol == 'USDP':
        symbol = 'PAX'

    # pricePairUsd = symbol + ' / USD'
    pricePairEth = symbol + ' / ETH'

    if amount == 0:
        return wrapped_return(0, 0, floatOutput)

    cache = try_get_cached_data(symbol, blockTimestamp, returnUsd=False)
    if cache != None:
        return wrapped_return(cache['price'] * amount, price_providers[pricePairEth]['decimals'], floatOutput)

    tsKey = get_ts_key(blockTimestamp)

    provider = price_providers.get(pricePairEth)
    if provider == None:
        resultEth = providerConsts.get(pricePairEth)
        if resultEth != None:
            (decimals, addrEth) = resultEth
            provider = create_price_provider(w3, pricePairEth, decimals, addrEth)
        else:
            print('[ERROR], Token {} have no pair with ETH'.format(symbol))
            return (None, None)

    latestPrice = find_price_by_time(w3, provider, blockTimestamp)
    if latestPrice is None:
        return (None, None)

    cache_data(pricePairEth, tsKey, latestPrice)
    return wrapped_return(latestPrice * amount, provider['decimals'], floatOutput)

# By default, receives decimal amount. If not - pass optional bool
def get_usd_price(w3, symbol, blockTimestamp, amount, floatOutput = True, network="ethereum"):
    # Consider filtering by leading 'W' ?
    if symbol == 'WETH':
        symbol = 'ETH'
    if symbol == 'WBTC':
        symbol = 'BTC'

    pricePairUsd = symbol + ' / USD'
    pricePairEth = symbol + ' / ETH'

    cache = try_get_cached_data(symbol, blockTimestamp)
    if cache != None:
        return wrapped_return(cache['price'] * amount, price_providers[pricePairUsd]['decimals'], floatOutput)

    tsKey = get_ts_key(blockTimestamp)

    convertThroughEth = False

    provider = price_providers.get(pricePairUsd)
    if provider == None:
        resultUsd = providerConsts[network].get(pricePairUsd)
        resultEth = providerConsts[network].get(pricePairEth)

        if resultUsd != None:
            (decimals, addrUsd) = resultUsd
            provider = create_price_provider(w3, pricePairUsd, decimals, addrUsd)
        # no usd price for token, create provider for eth
        elif resultEth != None:
            convertThroughEth = True
            (decimals, addrEth) = resultEth
            provider = create_price_provider(w3, pricePairEth, decimals, addrEth)
        else:
            print('ERROR, UNKNOWN TOKEN: {}', symbol)
            return (None, None)

    latestPrice = find_price_by_time(w3, provider, blockTimestamp)
    if latestPrice is None:
        return (None, None)

    if convertThroughEth:
        cache_data(pricePairEth, tsKey, latestPrice)
        etherPrice = get_usd_price(w3, 'ETH', blockTimestamp, 1)
        return wrapped_return(etherPrice * latestPrice * amount, provider['decimals'], floatOutput)

    cache_data(pricePairUsd, tsKey, latestPrice)

    return wrapped_return(latestPrice * amount, provider['decimals'], floatOutput)

# return decimal value if floatOutput=True else tuple of value and decimals
def wrapped_return(value, decimals, floatOutput):
    if floatOutput:
        return (to_float(value, decimals), decimals)
    return (value, decimals)

def try_get_cached_data(symbol, blockTimestamp, returnUsd=True):
    tsKey = get_ts_key(blockTimestamp)
    providerUsd = price_providers.get(symbol + ' / USD')
    providerEth = price_providers.get(symbol + ' / ETH')
    if (returnUsd == False and providerEth == None) or (returnUsd == True and providerUsd == None):
        return None

    if returnUsd:
        return get_cache_by_tskey(symbol + ' / USD', tsKey)
    return get_cache_by_tskey(symbol + ' / ETH', tsKey)

def get_current_timestamp(w3):
    latestBlock = w3.eth.get_block('latest')
    return latestBlock['timestamp']

def find_price_by_time(w3, provider, blockTimestamp):
    aggregator = w3.eth.contract(address = provider['address'], abi = chainlink_abi)

    if blockTimestamp == get_current_timestamp(w3):
        return aggregator.functions.latestAnswer().call()

    # lower boundary
    previousRound = 0
    # upper boundary
    try:
        roundId = aggregator.functions.latestRound().call()
    except:
        print("ERROR. unable to request latest round data. addr: {}", provider['address'])
        return None
    # Binary search for now
    delta = 123
    while delta >= 1:
        delta = (roundId - previousRound) // 2
        middleRoundId = roundId - delta
        try:
            (_roundId, answer, _startedAt, updatedAt, _answeredInRound) = aggregator.functions.getRoundData(middleRoundId).call()
            if blockTimestamp > updatedAt:
                previousRound = middleRoundId
            else:
                roundId = middleRoundId
        except:
            print("ERROR. unable to request round data: {}, tx: {}".format(middleRoundId, provider['address']))
            return None
    return answer

# Takes data from consts, fills up double dict price_providers
# TODO add error handling, so we never override existing provider
def create_price_provider(w3, pricePair, decimals, addr):
    feed = w3.eth.contract(address = addr, abi = feed_abi)
    try:
        aggregatorAddr = feed.functions.aggregator().call()
    except:
        print("ERROR. unable to request aggregator address {}".format(addr))
    price_providers[pricePair] = {
            'address': aggregatorAddr,
            'decimals': int(decimals),
    }
    price_providers[pricePair]['cache'] = {}

    return price_providers[pricePair]

def cache_data(pricePair, tsKey, latestPrice):
    price_providers[pricePair]['cache'][tsKey] = {
        'price': latestPrice
    }

def get_cache_by_tskey(PricePair, tsKey):
    provider = price_providers.get(PricePair)
    if provider == None: return None
    return provider['cache'].get(tsKey)

# increase hours => faster parser => less accurate results. TODO try different values
def get_ts_key(timestamp):
    return timestamp - timestamp % 60

# consider implementing precision, based on liquidityExpected / liquidityCalculated
def calculate_liquidation_prices(borrowMarkets, totalBorrowed, totalCollateral, ignoreWETH=False):
    liquidation_prices = dict()
    for market in borrowMarkets:
        # ETH / ETH is 1, and this calculation will break everything
        if ignoreWETH and market['tokenAddr'] == '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2':
            continue
        deltaCollateral = totalCollateral - market['tokenCollateralUsd']
        deltaBorrowed = totalBorrowed - market['tokenBorrowedUsd']
        liquidationPriceInt = int((deltaCollateral - deltaBorrowed) / (market['tokenBorrowedAmount'] - market['tokenCollateralAmount']))
        liquidationPriceFloat = (deltaCollateral - deltaBorrowed) / (market['tokenBorrowedAmount'] - market['tokenCollateralAmount'])
        if liquidationPriceInt > 0:
            liquidation_prices[market['tokenAddr']] = {
                'liqPriceInt': liquidationPriceInt,
                'liqPriceFloat': liquidationPriceFloat,
                'currentPrice': market['TokenPrice']
            }

    return liquidation_prices

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
