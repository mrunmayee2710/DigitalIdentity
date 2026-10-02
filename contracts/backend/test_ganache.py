from web3 import Web3

ganache_url = "http://127.0.0.1:7545"

web3 = Web3(Web3.HTTPProvider(ganache_url))

if web3.is_connected():
    print("Connected to Ganache!")
    print("Chain ID:", web3.eth.chain_id)
    print("Latest Block:", web3.eth.block_number)
else:
    print("Could not connect to Ganache.")