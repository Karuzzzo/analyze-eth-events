import json

# We call it once, somewhere in main 
def generate_event_signatures(w3):
    # aave_liquidation_event = w3.keccak(text="LiquidationCall(address,address,address,uint256,uint256,address,bool)").hex()
    # Tornado funds depositing
    # tornado_deposit_event = w3.keccak(text="Deposit(bytes32,uint32,uint256)").hex()
    # Tornado funds withdrawal
    # tornado_withdrawal_event = w3.keccak(text="Withdrawal(address,bytes32,address,uint256)").hex()
    # ERC20 Transfer event
    transfer_event = w3.keccak(text="Transfer(address,address,uint256)").hex()
    # New price in Chainlink event
    chainlink_transmit_price_event = w3.keccak(text="AnswerUpdated(int256,uint256,uint256)").hex()

    all_sigs = {
        'transfer': transfer_event,
        'transmit': chainlink_transmit_price_event,
    }

    with open("consts/all_event_signatures.json", 'w') as json_file:
        json.dump(all_sigs, json_file, 
                        indent=4,  
                        separators=(',',': '))

# Add new event signature
def add_to_event_sigs(w3, event_name, event_signature):
    event_sigs = get_event_signatures()
    event_sigs[event_name] = event_signature

    with open("consts/all_event_signatures.json", 'w') as json_file:
        json.dump(event_sigs, json_file, 
                        indent=4,  
                        separators=(',',': '))

def get_event_signatures():
    return json.load(open("consts/all_event_signatures.json"))