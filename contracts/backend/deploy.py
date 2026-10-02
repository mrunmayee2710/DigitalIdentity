import json
import os
from pathlib import Path

from dotenv import load_dotenv
from web3 import Web3

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
rpc_url = os.getenv("BLOCKCHAIN_RPC_URL", "http://127.0.0.1:7545")
web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 5}))

if not web3.is_connected():
    raise SystemExit(f"Could not connect to Ganache at {rpc_url}. Start Ganache and retry.")

compiled_path = BASE_DIR / "compiled_contract.json"
if not compiled_path.exists():
    raise SystemExit("compiled_contract.json is missing. Run `python compile.py` first.")

compiled = json.loads(compiled_path.read_text(encoding="utf-8"))
contract_data = compiled["contracts"]["DigitalIdentity.sol"]["DigitalIdentity"]
abi = contract_data["abi"]
bytecode = contract_data["evm"]["bytecode"]["object"]
accounts = web3.eth.accounts
if not accounts:
    raise SystemExit("Ganache returned no unlocked accounts. Check its wallet configuration.")

sender = os.getenv("BLOCKCHAIN_SENDER", "").strip()
account = Web3.to_checksum_address(sender) if sender else accounts[0]
if account not in [Web3.to_checksum_address(value) for value in accounts]:
    raise SystemExit("BLOCKCHAIN_SENDER is not one of Ganache's unlocked accounts.")

factory = web3.eth.contract(abi=abi, bytecode=bytecode)
tx_hash = factory.constructor().transact({"from": account})
receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
if not receipt.contractAddress:
    raise SystemExit("Deployment transaction completed without a contract address.")

deployment = {"address": receipt.contractAddress, "abi": abi, "chain_id": web3.eth.chain_id, "transaction_hash": receipt.transactionHash.hex()}
(BASE_DIR / "deployment.json").write_text(json.dumps(deployment, indent=2), encoding="utf-8")
(BASE_DIR / "contract_abi.json").write_text(json.dumps(abi, indent=2), encoding="utf-8")
print(f"Connected RPC: {rpc_url}")
print(f"Chain ID: {web3.eth.chain_id}")
print(f"Deployed by: {account}")
print(f"Contract address: {receipt.contractAddress}")
print("Update CONTRACT_ADDRESS in .env with this new address.")