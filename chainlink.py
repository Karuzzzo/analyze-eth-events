import consts
import web3
import re
import json
from web3connect import Web3Connect
import time
import logging
import os
from hexbytes import HexBytes 
import event_signatures 

# from eth_account._utils.legacy_transactions import Transaction, encode_transaction
# from hexbytes import HexBytes

global CHAINLINK_FEED_ABI
CHAINLINK_FEED_ABI = json.load(open("consts/Chainlink/ABI_Chainlink_OffchainAggregator.json"))

# LOADING FEEDS DATA FROM JSON FILE
# file can be rebuilt by "chainlink_renew_and_store_feeds_info_in_json()" function
FEED_TO_PAIR_JSON_FILE = "consts/chainlink_feed_info_by_addr.json"

global FEEDS_DATA_BY_ADDR
FEEDS_DATA_BY_ADDR = json.load(open(FEED_TO_PAIR_JSON_FILE))

def get_feeds_data_by_addr():
    return FEEDS_DATA_BY_ADDR

def get_asset_info(token_addr, market_symbol='ETH'):
    asset_info = None
    for feed in FEEDS_DATA_BY_ADDR:
        pair_name = FEEDS_DATA_BY_ADDR[feed]['pair_name']
        if pair_name[-3:] != market_symbol and pair_name != 'ETH / USD':
            continue 
        _token_address = list(FEEDS_DATA_BY_ADDR[feed]['linked_tokens'].keys())[0]
        
        if _token_address == token_addr:
            asset_info = FEEDS_DATA_BY_ADDR[feed]['linked_tokens'][_token_address]
            asset_info['price_feed'] = feed
        
    if asset_info == None:
        print('[ERROR] Unable to find price feeds for {}'
            .format(token_addr))
        return None
        
    return asset_info

def is_chainlink_tx(tx):
    # there can be transactions without "to" - it's a contract creation txs
    if tx.get('to') is None:
        return False
    if FEEDS_DATA_BY_ADDR.get(tx['to']):
        return True
    return False

# thrash helper func
def get_symbol_by_addr(token_addr):
    if token_addr == '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2':
        return "WETH"
    for _, v in FEEDS_DATA_BY_ADDR.items():
        for taddr, t in v['linked_tokens'].items():
            if taddr == token_addr:
                return t['symbol']
    return "HzT"

def get_last_answer_in_feed(w3, asset_info, tx_block_number, tx_index):
    default_result = {
            'answer': 0,
            'blockNumber': 0,
            'txhash': 0,
            'index': 0,
            'same_block_as_transaction': False
        }    

    if asset_info['symbol'] == 'WETH':
        return default_result

    event_signature_list = event_signatures.get_event_signatures()
    print(asset_info)
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
            "topics": [event_signature_list['transmit']],
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

def extract_price_info_from_chainlink_mempool_tx(w3, tx):
    feed_data = FEEDS_DATA_BY_ADDR.get(tx['to'])
    if feed_data is None:
        return None

    contract = w3.eth.contract(address=tx['to'], abi=CHAINLINK_FEED_ABI)
    (rawReportContext, rawObservers, observations) = (None, None, None)
    try:
        decoded = contract.decode_function_input(HexBytes(tx['data']))
        report = decoded[1]['_report']
        (rawReportContext, rawObservers, observations) = \
            w3.codec.decode_abi(['bytes32', 'bytes32', 'int192[]'], report)
    except KeyError:
        # we haven't found "_report" key in decoded transaction
        # it happens, when it's the transaction in the feed, but not doing "transmit"
        # example: 0xd57492b8d138cf637db02dd7136a39b1511ea1ae0f69e0de6dfa9f92ceca807c
        # simply skip such a transaction
        
        print("KeyError, '_report' was not found in tx {}, skip".format(tx['hash'].hex()))
        return None
    except Exception as e:
        print("[ERROR] {} exception decoding tx {} : {}".format(type(e).__name__, tx['hash'].hex(), e))
        return None

    # result is median value in pre-sorted list
    result = {}
    result['price'] = observations[int(len(observations) / 2)]
    result['pair_name'] = feed_data['pair_name']
    result['pair_decimals'] = int(feed_data['pair_decimals'])
    result['linked_tokens'] = feed_data['linked_tokens'] # empty dict if no tokens linked
    return result


def extract_price_info_from_chainlink_tx(w3, tx):
    feed_data = FEEDS_DATA_BY_ADDR.get(tx['to'])
    if feed_data is None:
        return None

    contract = w3.eth.contract(address=tx['to'], abi=CHAINLINK_FEED_ABI)
    (rawReportContext, rawObservers, observations) = (None, None, None)
    try:
        decoded = contract.decode_function_input(tx.input)
        report = decoded[1]['_report']
        (rawReportContext, rawObservers, observations) = \
            w3.codec.decode_abi(['bytes32', 'bytes32', 'int192[]'], report);
    except KeyError:
        # we haven't found "_report" key in decoded transaction
        # it happens, when it's the transaction in the feed, but not doing "transmit"
        # example: 0xd57492b8d138cf637db02dd7136a39b1511ea1ae0f69e0de6dfa9f92ceca807c
        # simply skip such a transaction
        
        # log.info("KeyError, '_report' was not found in tx {}, skip".format(tx['hash'].hex()))
        return None
    except Exception as e:
        print("[ERROR] {} exception decoding tx {} : {}".format(type(e).__name__, tx['hash'].hex(), e))
        return None

    # result is median value in pre-sorted list
    result = {}
    result['price'] = observations[int(len(observations) / 2)]
    result['pair_name'] = feed_data['pair_name']
    result['pair_decimals'] = int(feed_data['pair_decimals'])
    result['linked_tokens'] = feed_data['linked_tokens'] # empty dict if no tokens linked
    return result

def get_last_eth_price(w3, token_addr):
    # WETH
    if token_addr == '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2':
        return (10**18, 18)

    aggr_addr = None
    pair_decimals = None
    token_found = False

    for faddr, fdata in FEEDS_DATA_BY_ADDR.items():
        for taddr in fdata.get('linked_tokens').keys():
            if taddr == token_addr:
                aggr_proxy_addr = taddr['price_from']
                pair_decimals = fdata['pair_decimals']
                token_found = True
        if token_found:
            break
                
    if aggr_proxy_addr is None:
        print("[ERROR] no price proxy found for addr {}".format(token_addr))
        return (None, None)

    
    aggregator = w3.eth.contract(address = aggr_proxy_addr, abi = CHAINLINK_FEED_ABI)
    last_price = None
    try:
        last_price = aggregator.functions.latestAnswer().call()
    except Exception as e:
        print("[ERROR] {} error getting price from provider: {}".format(type(e).__name__, e))
    
    if last_price is not None:
        return (last_price, pair_decimals)
    return (None, None)

def get_token_symbol(token_contract):
    token_addr = token_contract.address
    if token_addr == '0x9f8F72aA9304c8B593d555F12eF6589cC3A579A2':
        # .symbol() call returns bytes32 string ".....MKR.."
        token_symbol = "MKR"
    elif token_addr == '0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599':
        # symbol() returns 'WBTC'
        token_symbol = "WBTC"
    elif token_addr == '0x57Ab1ec28D129707052df4dF418D58a2D46d5f51':
        # symbol returns "sUSD" instead of "SUSD"
        token_symbol = "sUSD"
    elif token_addr == '0xD5147bc8e386d91Cc5DBE72099DAC6C9b99276F5':
        # renFIL (ren project wrapped FIL (filecoin)
        token_symbol = "renFIL"
    elif token_addr == '0x8E870D67F660D95d5be530380D0eC0bd388289E1':
        # Paxos Standard (PAX) Token is now rebranded as Pax Dollar (USDP)
        token_symbol = "USDP"
    elif token_addr == '0x056Fd409E1d7A124BD7017459dFEa2F387b6d5Cd':
        # GUSD - AAVE uses ETH / USD pair for it instead of GUSD / ETH
        token_symbol = "GUSD"
        # Bad symbol encoding, same as MKR, and SAI is also dead
    elif token_addr == "0x89d24A6b4CcB1B6fAA2625fE562bDD9a23260359":
        token_symbol = "SAI"
    else:
        token_symbol = str(token_contract.functions.symbol().call())
    
    return token_symbol

#  used only manually to store parsed data into FEED_TO_PAIR_JSON_FILE
def generate_chainlink_price_feeds_data_json(w3):
    global FEEDS_DATA_BY_ADDR
    FEEDS_DATA_BY_ADDR = {}

    get_aave_tokens_info(w3)
    get_compound_tokens_info(w3)
    with open(FEED_TO_PAIR_JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(FEEDS_DATA_BY_ADDR, f, ensure_ascii=False, indent=4)


# COMPOUND COMPOUND COMPOUND COMPOUND COMPOUND COMPOUND    
def get_compound_tokens_info(w3):
    COMPOUND_ORACLE_ADDR = '0x046728da7cb8272284238bD3e47909823d63A58D'
    COMPOUND_ORACLE_ABI = json.load(open("consts/Compound/ABI_compound_oracle.json"))
    compound_oracle_contract = w3.eth.contract(address=COMPOUND_ORACLE_ADDR, abi=COMPOUND_ORACLE_ABI)

    COMPOUND_COMPTROLLER_ADDR = '0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B'
    COMPOUND_COMPTROLLER_ABI = json.load(open("consts/Compound/ABI_compound_comptroller.json"))
    
    compound_comptroller_contract = w3.eth.contract(address=COMPOUND_COMPTROLLER_ADDR, abi=COMPOUND_COMPTROLLER_ABI)
    # List of cTokens used in protocol
    compound_all_reserve_tokens = compound_comptroller_contract.functions.getAllMarkets().call()
    ABI_USDC = json.load(open("consts/ABI_USDC.json"))
    ABI_CTOKEN = json.load(open("consts/Compound/ABI_compound_ctoken.json"))
    ABI_VALIDATOR_PROXY = json.load(open("consts/Compound/ABI_validator_proxy.json"))
    ABI_CHAINLINK_AGGREGATOR = json.load(open("consts/Chainlink/ABI_Chainlink_OffchainAggregator.json"))
    stablecoins = [
        # USDC
        "0x39AA39c021dfbaE8faC545936693aC917d5E7563", 
        # USDT
        "0xf650C3d88D12dB855b8bf7D11Be6C55A4e07dCC9", 
        # SAI
        "0xF5DCe57282A584D2746FaF1593d3121Fcac444dC", 
        # TUSD
        "0x12392F67bdf24faE0AF363c24aC620a2f67DAd86",
        # USDP
        "0x041171993284df560249B57358F931D9eB7b925D"
    ]
    for ctoken_addr in compound_all_reserve_tokens:
        # Skip USDC / USD, it's always exactly 1
        if ctoken_addr in stablecoins:
            continue
        
        ctoken_contract = w3.eth.contract(address=ctoken_addr, abi=ABI_CTOKEN)
        
        token_symbol = None
        token_decimals = None
        
        if ctoken_addr == '0x4Ddc2D193948926D02f9B1fE9e1daa0718270ED5':
            # We get underlying token, TODO parse and save ctoken data aswell        
            token_symbol = 'ETH'
            token_decimals = 18
        else:
            token_addr = ctoken_contract.functions.underlying().call()
            token_contract = w3.eth.contract(address=token_addr, abi=ABI_USDC)
            token_symbol = get_token_symbol(token_contract)
            token_decimals = token_contract.functions.decimals().call()
        # Making our way to the chainlink price feeds
        token_config = compound_oracle_contract.functions.getTokenConfigByCToken(ctoken_addr).call()
        (cToken, 
        underlying,
        symbolHash,
        baseUnit,
        priceSource,
        fixedPrice,
        uniswapMarket,
        reporter,
        reporterMultiplier,
        isUniswapReversed) = token_config
        # Reporter is a proxy between Chainlink and Compound oracle (0xDe2Fa230d4C05ec0337D7b4fc10e16f5663044B0)
        proxy_contract = w3.eth.contract(address=reporter, abi=ABI_VALIDATOR_PROXY)
        (feed_addr, hasProposal, proposed) = proxy_contract.functions.getAggregators().call()


        eac_aggr_proxy_contract = w3.eth.contract(address=feed_addr, abi=ABI_CHAINLINK_AGGREGATOR)
                
        # feed_addr = eac_aggr_proxy_contract.functions.aggregator().call()
        feed_decimals = eac_aggr_proxy_contract.functions.decimals().call()
        feed_name = eac_aggr_proxy_contract.functions.description().call()
        feed_transmitters = eac_aggr_proxy_contract.functions.transmitters().call()

        # print("{}, {}".format(token_symbol, token_addr))

            
        print(f"COMPOUND token {token_symbol} {token_addr} with decimals {token_decimals} receives price from "
              f"aggregator or proxy {COMPOUND_ORACLE_ADDR} that proxies latestAnswer() "
              f"from feed {feed_name} at {feed_addr} with decimals {feed_decimals}")
        
        # continue    
        if FEEDS_DATA_BY_ADDR.get(feed_addr) is None:
            FEEDS_DATA_BY_ADDR[feed_addr] = {
                'pair_name': feed_name,
                'pair_decimals': feed_decimals,
                'transmitters': feed_transmitters,
                'linked_tokens': {
                    token_addr: {
                        # It's always one source of prices for Compound
                        'price_from': COMPOUND_ORACLE_ADDR,
                        'symbol': token_symbol,
                        'decimals': token_decimals,
                        'aave': True
                    }
                }
            }
        else:
            FEEDS_DATA_BY_ADDR[feed_addr]['linked_tokens'][token_addr] = {
                'price_from': COMPOUND_ORACLE_ADDR,
                'symbol': token_symbol,
                'decimals': token_decimals,
                'aave': True
            }


# AAVE AAVE AAVE AAVE AAVE AAVE AAVE AAVE AAVE    
def get_aave_tokens_info(w3):
    AAVE_EAC_AGGR_PROXY_ABI = json.load(open("consts/AAVE/ABI_aave_eac_aggregator_proxy.json"))
    # now mark all AAVE tokens
    AAVE_LENDING_POOL_V2_ADDRESS = '0x7d2768dE32b0b80b7a3454c06BdAc94A69DDc7A9'
    AAVE_LENDING_POOL_V2_ABI = json.load(open("consts/AAVE/ABI_aave_lending_pool.json"))
    aave_lending_pool_v2_contract = w3.eth.contract(address=AAVE_LENDING_POOL_V2_ADDRESS, abi=AAVE_LENDING_POOL_V2_ABI)
    aave_all_reserve_tokens = aave_lending_pool_v2_contract.functions.getReservesList().call()

    AAVE_ORACLE_ADDR = '0xA50ba011c48153De246E5192C8f9258A2ba79Ca9'
    AAVE_ORACLE_ABI = json.load(open("consts/AAVE/ABI_aave_oracle.json"))
    aave_oracle_conract = w3.eth.contract(address=AAVE_ORACLE_ADDR, abi=AAVE_ORACLE_ABI)

    ABI_USDC = json.load(open("consts/ABI_USDC.json"))
    for token_addr in aave_all_reserve_tokens:
        
        # token_abi = abi_usdc 
        token_contract = w3.eth.contract(address=token_addr, abi=ABI_USDC)
        
        if token_addr == '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2':
            # WETH / ETH course is hardcoded in get price, no feeds
            continue
        
        token_symbol = get_token_symbol(token_contract)
        token_decimals = token_contract.functions.decimals().call()
 
        asset_source_addr = aave_oracle_conract.functions.getSourceOfAsset(token_addr).call()
        
        # asset_source_addr - contract, gving "latestAnswer()" response to AAVE contracts
        # usually it's the regular EACAggregatorProxy contract, bu not in all cases

        # feed_addr - address, where oracles actually send prices
        feed_addr = None
        eac_aggr_proxy_contract = None
        # GUSD_TOKEN (0x056Fd409E1d7A124BD7017459dFEa2F387b6d5Cd)
        if asset_source_addr == '0xEc6f4Cd64d28Ef32507e2dc399948aAe9Bbedd7e':
            # special proxy form GUSD token, transforming ETH / USD feed price
            proxy_abi = json.load(open(f"consts/addr_to_abi/0xEc6f4Cd64d28Ef32507e2dc399948aAe9Bbedd7e.json"))
            aggr_proxy_contract = w3.eth.contract(address=asset_source_addr, abi=proxy_abi)
            eac_aggr_proxy_addr = aggr_proxy_contract.functions.ETH_USD_CHAINLINK_PROXY().call()
            eac_aggr_proxy_contract = w3.eth.contract(address=eac_aggr_proxy_addr, abi=AAVE_EAC_AGGR_PROXY_ABI)
        
        # xSUSHI TOKEN (0x8798249c2E607446EfB7Ad49eC89dD1865Ff4272)
        elif asset_source_addr == '0x9b26214bEC078E68a394AaEbfbffF406Ce14893F':
            proxy_abi = json.load(open(f"consts/addr_to_abi/0x9b26214bEC078E68a394AaEbfbffF406Ce14893F.json"))
            aggr_proxy_contract = w3.eth.contract(address=asset_source_addr, abi=proxy_abi)
            eac_aggr_proxy_addr = aggr_proxy_contract.functions.SUSHI_ORACLE().call()
            eac_aggr_proxy_contract = w3.eth.contract(address=eac_aggr_proxy_addr, abi=AAVE_EAC_AGGR_PROXY_ABI)
        
        # ENS TOKEN (0xC18360217D8F7Ab5e7c516566761Ea12Ce7F9D72)
        elif asset_source_addr == '0xd4641b75015E6536E8102D98479568D05D7123Db':
            proxy_abi = json.load(open(f"consts/addr_to_abi/0xd4641b75015E6536E8102D98479568D05D7123Db.json"))
            aggr_proxy_contract = w3.eth.contract(address=asset_source_addr, abi=proxy_abi)
            eac_aggr_proxy_addr = aggr_proxy_contract.functions.ENS_USD().call()
            eac_aggr_proxy_contract = w3.eth.contract(address=eac_aggr_proxy_addr, abi=AAVE_EAC_AGGR_PROXY_ABI)

        else:
            eac_aggr_proxy_contract = w3.eth.contract(address=asset_source_addr, abi=AAVE_EAC_AGGR_PROXY_ABI)
        
        feed_addr = eac_aggr_proxy_contract.functions.aggregator().call()
        feed_decimals = eac_aggr_proxy_contract.functions.decimals().call()
        feed_name = eac_aggr_proxy_contract.functions.description().call()

        aggregator_contract = w3.eth.contract(address = feed_addr, abi = CHAINLINK_FEED_ABI)
        feed_transmitters = aggregator_contract.functions.transmitters().call()

        print(f"AAVE token {token_symbol} {token_addr} with decimals {token_decimals} receives price from "
              f"aggregator or proxy {asset_source_addr} that proxies latestAnswer() "
              f"from feed {feed_name} at {feed_addr} with decimals {feed_decimals}")
        
        if FEEDS_DATA_BY_ADDR.get(feed_addr) is None:
            FEEDS_DATA_BY_ADDR[feed_addr] = {
                'pair_name': feed_name,
                'pair_decimals': feed_decimals,
                'transmitters': feed_transmitters,
                'linked_tokens': {
                    token_addr: {
                        'price_from': asset_source_addr,
                        'symbol': token_symbol,
                        'decimals': token_decimals,
                        'aave': True
                    }
                }
            }
        else:
            FEEDS_DATA_BY_ADDR[feed_addr]['linked_tokens'][token_addr] = {
                'price_from': asset_source_addr,
                'symbol': token_symbol,
                'decimals': token_decimals,
                'aave': True
            }
