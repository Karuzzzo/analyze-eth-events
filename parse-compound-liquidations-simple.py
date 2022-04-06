import signal
import sys

from eth_typing.evm import BlockNumber
from web3 import Web3
import time
import json
import tx_parser
from datetime import datetime
import os
from dotenv import load_dotenv, find_dotenv
import math

# Approx. block number of moving Compound to Chainlink oracle
# BLOCK_NUMBER = 12859160

tokens_cache = {}

AGGR = {}

def get_cached_market_info(addr):
    if tokens_cache.get(addr) is None:
        try:
            cToken = w3.eth.contract(address = addr, abi = ctoken_abi)
            cTokenSymbol = cToken.functions.symbol().call()
            cTokenDecimals = cToken.functions.decimals().call()

            cComptrollerAddr = w3.toChecksumAddress(cToken.functions.comptroller().call())
            cComptroller = w3.eth.contract(address = cComptrollerAddr, abi = comptroller_abi)

            if (addr == "0x4Ddc2D193948926D02f9B1fE9e1daa0718270ED5"):
                cUnderlyingSymbol = "ETH"
                cUnderlyingDecimals = 18
            else:
                underlyingAddr = cToken.functions.underlying().call()
                cUnderlying = w3.eth.contract(address = underlyingAddr, abi = usdc_abi)
                cUnderlyingSymbol = cUnderlying.functions.symbol().call()
                cUnderlyingDecimals =  cUnderlying.functions.decimals().call()

            tokens_cache[addr] = {
                'comptroller': cComptrollerAddr,
                'ctoken': addr,
                'cdecimals': cTokenDecimals,
                'csymbol': cTokenSymbol,
                'usymbol': cUnderlyingSymbol,
                'udecimals': cUnderlyingDecimals,
            }
        except Exception as e:
            print("[ERROR] get token infor from addr {}: {}".format(addr, e))
            return None

    return tokens_cache[addr]

COMPOUND_MARKETS = {'0x6C8c6b02E7b2BE14d4fA6022Dfd6d75921D90E4E': True, '0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643': True, '0x4Ddc2D193948926D02f9B1fE9e1daa0718270ED5': True, '0x158079Ee67Fce2f58472A96584A73C7Ab9AC95c1': True, '0x39AA39c021dfbaE8faC545936693aC917d5E7563': True, '0xf650C3d88D12dB855b8bf7D11Be6C55A4e07dCC9': True, '0xC11b1268C1A384e55C48c2391d8d480264A3A7F4': True, '0xB3319f5D18Bc0D84dD1b4825Dcde5d5f7266d407': True, '0xF5DCe57282A584D2746FaF1593d3121Fcac444dC': True, '0x35A18000230DA775CAc24873d00Ff85BccdeD550': True, '0x70e36f6BF80a52b3B46b3aF8e106CC0ed743E8e4': True, '0xccF4429DB6322D5C611ee964527D42E5d685DD6a': True, '0x12392F67bdf24faE0AF363c24aC620a2f67DAd86': True, '0xFAce851a4921ce59e912d19329929CE6da6EB0c7': True, '0x95b4eF2869eBD94BEb4eEE400a99824BF5DC325b': True, '0x4B0181102A0112A2ef11AbEE5563bb4a3176c9d7': True, '0xe65cdB6479BaC1e22340E4E755fAE7E509EcD06c': True, '0x80a2AE356fc9ef4305676f7a3E2Ed04e12C33946': True}
FORK_MARKETS = {'0x1066AB47a342152C564AF62D179aA4B659a11F7d': True, '0x806323188117b73315fC9EB3FAa3a48A8D080376': True, '0xa3fd14e33fFEE094c8359B0984e2080146317206': True, '0x4eB7440E6b9341505f86096EFB4019EAb287f611': True, '0x9de558FCE4F289b305E38ABe2169b75C626c114e': True, '0xda396c927e3e6BEf77A98f372CE431b49EdEc43D': True, '0xF148cDEc066b94410d403aC5fe1bb17EC75c5851': True, '0xA2f8bE58F39069D5F69F609B6Ab9aB865a8AcA53': True}

def handle_cdp_liq_event(event):
    blockNumber = event.blockNumber
    txIndex = event.transactionIndex

    tx = w3.eth.get_transaction(event['transactionHash'].hex())
    block = w3.eth.get_block(blockNumber)
    timestamp = block['timestamp']
    block_timestamp = datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
    txHash = event.transactionHash.hex()
    gas = get_tx_gas_price(txHash)

    cTokenAddr = w3.toChecksumAddress(event.address)
    cTokenSeizedAddr = tx_parser.get_cTokenAddr(event.data, w3)
    # liqAddr = tx_parser.get_liqAddr(event.data, w3)
    # borAddr = tx_parser.get_borAddr(event.data, w3)

    if COMPOUND_MARKETS.get(cTokenAddr) is None:
        # print("Market {} is not a Compound market".format(cTokenAddr))
        return

    mkt_repay = get_cached_market_info(cTokenAddr)
    mkt_seize = get_cached_market_info(cTokenSeizedAddr)
    if mkt_repay is None:
        print("[ERROR] getting repay cToken market: {}".format(cTokenAddr))
        return
    if mkt_seize is None:
        print("[ERROR] getting sezie cToken market: {}".format(cTokenSeizedAddr))
        return

    cToken = w3.eth.contract(address = mkt_repay['ctoken'], abi = ctoken_abi)
    cComptroller = w3.eth.contract(address = mkt_repay['comptroller'], abi = comptroller_abi)

    seizedCTokens = tx_parser.get_seized_amount(event.data)

    cSeizedToken = w3.eth.contract(address = cTokenSeizedAddr, abi = ctoken_abi)
    # seized on other market
    seizedCTokens = tx_parser.get_seized_amount(event.data)

    repayedUnderlying = tx_parser.get_repay_amount(event.data)
    feeETH = get_tx_gas_price(event.transactionHash)

    # TODO - current-stored check
    exchangeRateCurrent = cSeizedToken.functions.exchangeRateCurrent().call()
    exchangeRateStored = cSeizedToken.functions.exchangeRateStored().call()
    underlyingsInOneSeizedCToken = exchangeRateCurrent / 10 ** 18
    seizedInUnderlying = seizedCTokens * underlyingsInOneSeizedCToken
    
    seizedAmountDecimal = seizedInUnderlying / 10 ** mkt_seize['udecimals']
    repayAmountDecimal = repayedUnderlying / 10 ** mkt_repay['udecimals']

    seizedAmountUsd = tx_parser.get_usd_price(w3, mkt_seize['usymbol'], timestamp, seizedAmountDecimal)
    repayAmountUsd = tx_parser.get_usd_price(w3, mkt_repay['usymbol'], timestamp, repayAmountDecimal)
    if seizedAmountUsd < 0.01:
        print("[ERROR] cannot get USD price for seized {}, skip liquidation".format(mkt_seize['usymbol']))
        return
    if repayAmountUsd < 0.01:
        print("[ERROR] cannot get USD price for repayed {}, skip liquidation".format(mkt_repay['usymbol']))
        return

    feeUsd = tx_parser.get_usd_price(w3, 'ETH', timestamp, gas)

    profitUsd = seizedAmountUsd - repayAmountUsd

    global AGGR
    save_to_json(
        timestamp, mkt_seize, mkt_repay, 
        seizedInUnderlying, seizedAmountUsd, 
        repayedUnderlying, repayAmountUsd)

    # calc only in seized underlying
    print("\nSeize from {}(.{}) to {} (.{}) txhash: {} block: {}"
          "\nSeized {:.3f} {} ({:.3f} {}), repayed {:.3f} {}"
          "\nLiquidation profit: {:.2f} USD, (gas: {:.2f} ETH / {:.2f} USD)"
          "\n--------------".format(
          mkt_repay['csymbol'], mkt_repay['cdecimals'],
          mkt_seize['csymbol'], mkt_seize['cdecimals'],
          txHash, blockNumber,
          seizedInUnderlying / 10 ** mkt_seize['udecimals'], mkt_seize['usymbol'],
          seizedCTokens / 10 ** mkt_seize['cdecimals'], mkt_seize['csymbol'],
          repayedUnderlying / 10 ** mkt_repay['udecimals'], mkt_repay['usymbol'],
          profitUsd, feeETH, feeUsd)
          )
    # print(event)
    # exit(0)

def get_tx_gas_price(txHash):
    gasPrice = w3.eth.getTransaction(txHash).gasPrice
    gasUsed = w3.eth.getTransactionReceipt(txHash).gasUsed
    # return "{}*{:.0f} Gwei".format(gasUsed, gasPrice / 10**9)
    fee = tx_parser.to_float(gasPrice * gasUsed, 18)
    return fee

def save_to_json(timestamp, mkt_seize, mkt_repay, seizedInUnderlying, seizedAmountUsd, repayedUnderlying, repayAmountUsd):
    week_tss = timestamp - (timestamp % (60 * 60 * 24 * 7)) # week aggregation
    week_ts = datetime.utcfromtimestamp(week_tss).strftime('%Y-%m-%d') + " + 7 days"
    AGGR.setdefault(week_ts, {})
    AGGR[week_ts].setdefault('seized', {})
    AGGR[week_ts].setdefault('repaid', {})
    AGGR[week_ts].setdefault('seized_usd_total', 0)
    AGGR[week_ts].setdefault('repaid_usd_total', 0)

    AGGR[week_ts]['seized'].setdefault(mkt_seize['usymbol'], 0)
    AGGR[week_ts]['seized'][mkt_seize['usymbol']] += (seizedInUnderlying / 10 ** mkt_seize['udecimals'])
    AGGR[week_ts]['seized_usd_total'] += (seizedAmountUsd)

    AGGR[week_ts]['repaid'].setdefault(mkt_repay['usymbol'], 0)
    AGGR[week_ts]['repaid'][mkt_repay['usymbol']] += (repayedUnderlying / 10 ** mkt_repay['udecimals'])
    AGGR[week_ts]['repaid_usd_total'] += (repayAmountUsd)
   
    AGGR[week_ts]['profit_usd'] = AGGR[week_ts]['seized_usd_total'] - AGGR[week_ts]['repaid_usd_total']

def main():
    # exit by Ctrl+C
    signal.signal(signal.SIGINT, lambda signal,frame: { print("Interrupt by SIGINT"), sys.exit(0)})


    global w3
    load_dotenv(find_dotenv())
    infuraAddr = os.environ.get("NODE_BASE_ENDPOINT") + os.environ.get("NODE_API_KEY")
    w3 = Web3(Web3.WebsocketProvider(infuraAddr))
    if not w3.isConnected():
        print('Node is not connected')
        exit()

    global ctoken_abi
    ctoken_abi = json.load(open("consts/Compound/ABI_compound_ctoken.json"))
    global comptroller_abi
    comptroller_abi = json.load(open("consts/Compound/ABI_compound_comptroller.json"))
    global usdc_abi
    usdc_abi = json.load(open("consts/ABI_USDC.json"))

    global AGGR

    # example: https://etherscan.io/tx/0xb790124c466231de88d7f88501f07cba93d8d226e8571de594fa1fb72153efa8#eventlog
    # Borrow (address borrower, uint256 borrowAmount, uint256 accountBorrows, uint256 totalBorrows)
    cdp_liquidation_event_sig = w3.keccak(text="LiquidateBorrow(address,address,uint256,address,uint256)").hex()

    # 13330090  01.10.2021 00:00:00
    # 13527858  31.10.2021 23:59:20
    # start_block = 13340090
    # ~ 6400 blocks/day
    start_block = 12859160
    end_block = 13527858 # start_block + 200 #6400 * 21
    current_start_block = start_block

    OUTFILE_JSON = "compound_liquidations.json"
    while (current_start_block <= end_block):
        current_end_block = current_start_block + 1000
        if current_end_block > end_block:
            current_end_block = end_block

        compound_cdp_liq_event_filter = w3.eth.filter({
            "fromBlock": current_start_block,
            "toBlock": current_end_block,
            "topics": [cdp_liquidation_event_sig]
        })
        failed = True
        ntries = 0
        while((failed or ntries == 0) and ntries < 2):
            # print("Processing blocks from {} to {}".format(current_start_block, current_end_block))
            failed = True
            try:
                for event in compound_cdp_liq_event_filter.get_all_entries():
                    handle_cdp_liq_event(event)

                failed = False
                ntries = 0
            except Exception as e:
                print("ERRR: {}".format(e))
                print("Sleeping 5 sec...")
                time.sleep(5)
                ntries += 1
                failed = True

            if (failed == False):
                break

        if (failed == True):
            print("Skipping blocks from {} to {}, trying next pack".format(current_start_block, current_end_block))

        current_start_block = current_end_block + 1

        # inside the cycle to not lost gathered data if failed
        with open(OUTFILE_JSON, 'w', encoding='utf-8') as f:
            json.dump(AGGR, f, ensure_ascii=False, indent=4)

    print("AGGR data is saved in file '{}'".format(OUTFILE_JSON))

if __name__ == '__main__':
    main()
