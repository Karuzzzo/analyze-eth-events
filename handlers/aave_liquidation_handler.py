import telegram_bot
import chainlink
import event_signatures
from handlers.handler_interface import handlerInterface
import tx_parser
import requests
import datetime

WETH_ADDRESS = '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'

class AAVELiquidationEventHandler(handlerInterface):
    def __init__(self, w3) -> None:
            event_sig_text = "LiquidationCall(address,address,address,uint256,uint256,address,bool)"
            self.w3 = w3
            self.event_name = 'AAVELiquidation'
            self.event_signature = w3.keccak(text=event_sig_text).hex()
            event_signatures.add_to_event_sigs(w3, self.event_name, event_sig_text)

    def get_name(self):
        return self.event_name
    
    def get_event_signature(self):
        return self.event_signature

    def parse_data_from_liq_event(self, liquidation_event):
        data = {}
        data['blockNumber'] = liquidation_event['blockNumber']
        data['index'] = liquidation_event['transactionIndex']
        data['liquidator'] = tx_parser.aave_get_liqAddr(liquidation_event.data, self.w3)
        data['collateral_amount'] = tx_parser.aave_get_seized_amount(liquidation_event.data)
        data['collateral_addr'] = self.w3.toChecksumAddress(liquidation_event.topics[1].hex()[-40:])
        data['debt_amount'] = tx_parser.aave_get_repay_amount(liquidation_event.data)
        data['debt_addr'] = self.w3.toChecksumAddress(liquidation_event.topics[2].hex()[-40:])
        data['borrower'] = self.w3.toChecksumAddress(liquidation_event.topics[3].hex()[-40:])
        data['txhash'] = liquidation_event.transactionHash.hex()
        return data

    def handle_event(self, liquidation_event):
        # Parse all stuff from event
        receipt = self.w3.eth.getTransactionReceipt(liquidation_event['transactionHash'])
        liquidation_data = self.parse_data_from_liq_event(liquidation_event)
        # Also add gas used from tx receipt
        liquidation_data['txfee'] = int(receipt['effectiveGasPrice'] * receipt['gasUsed'])
        
        collateral_asset_info = None
        debt_asset_info = None
        # Exception for WETH, as he does not have any price providers
        if liquidation_data['collateral_addr'] == WETH_ADDRESS:
            collateral_asset_info = {
                'symbol': 'WETH',
                'decimals': 18
            }

        if liquidation_data['debt_addr'] == WETH_ADDRESS:
            debt_asset_info = {
                'symbol': 'WETH',
                'decimals': 18
            }

        # If it's not WETH, find feed addresses for debt and (or) collateral
        if collateral_asset_info == None:
            collateral_asset_info = chainlink.get_asset_info(liquidation_data['collateral_addr'])
        if debt_asset_info == None:
            debt_asset_info = chainlink.get_asset_info(liquidation_data['debt_addr'])
        # Still didn't find those? Break
        if collateral_asset_info == None or debt_asset_info == None:
            print("[ERROR] Unable to find price provider for collateral({}) or debt {} in liquidation"
                .format(collateral_asset_info, debt_asset_info))
            return None
        
        # Now we check AnswerUpdated events, finding closest to liquidation
        # TODO - it was written for analysis of SINGLE liquidation
        # and is very ineffective and slow (performing price change lookup backward for EACH liquidation)
        collateral_latest = chainlink.get_last_answer_in_feed(
            self.w3,
            collateral_asset_info, 
            liquidation_data['blockNumber'], 
            liquidation_data['index']
        )
        debt_latest = chainlink.get_last_answer_in_feed(
            self.w3,
            debt_asset_info,  
            liquidation_data['blockNumber'], 
            liquidation_data['index']
        )

        # Format output to match the timeline
        print("###################################################################################")
        latest_price_change = debt_latest
        if collateral_latest['blockNumber'] >= debt_latest['blockNumber']:
            latest_price_change_bn = collateral_latest

            self.formatted_print_price_change(debt_latest, debt_asset_info)
            self.formatted_print_price_change(collateral_latest, collateral_asset_info)
        else: 
            self.formatted_print_price_change(collateral_latest, collateral_asset_info)
        self.formatted_print_price_change(debt_latest, debt_asset_info)
    
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
        
        # Place different strings, if we're dealing with flashbots 
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
    

    def get_block_timestamp(self, block_number):
        block = self.w3.eth.get_block(block_number)
        timestamp = block['timestamp']
        return datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

    def formatted_print_price_change(self, asset_latest, asset_info):
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
                    self.get_block_timestamp(asset_latest['blockNumber']), asset_latest['blockNumber'], asset_latest['index'],
                    asset_latest['same_block_as_transaction'],
                    asset_latest['txhash'],
                    asset_info['symbol'], asset_latest['answer'] / (10 ** 18),
                    flashbots_info,
                )   
        )

# Maybe move somewhere? somewhere to math?
def calculate_asset_profit(amount, latest_price, decimals, symbol):
    if symbol == 'WETH':
        return amount / (10 ** decimals)
    # decimals for token and for X / ETH price oracle is always 18
    return (amount * latest_price) / (10 ** (decimals + 18))

# Maybe move somewhere? somewhere to flashbots?
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

