from solcx import compile_standard, install_solc
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

print("Installing Solidity compiler...")
install_solc("0.8.19")

contract_path = BASE_DIR.parent / "DigitalIdentity.sol"

with open(contract_path, "r") as file:
    source_code = file.read()

compiled_sol = compile_standard(
    {
        "language": "Solidity",
        "sources": {
            "DigitalIdentity.sol": {
                "content": source_code
            }
        },
        "settings": {
            "evmVersion": "paris",
            "outputSelection": {
                "*": {
                    "*": [
                        "abi",
                        "evm.bytecode"
                    ]
                }
            }
        }
    },
    solc_version="0.8.19"
)

compiled_path = BASE_DIR / "compiled_contract.json"
with compiled_path.open("w", encoding="utf-8") as file:
    json.dump(compiled_sol, file, indent=4)

contract_data = compiled_sol["contracts"]["DigitalIdentity.sol"]["DigitalIdentity"]
abi_path = BASE_DIR / "contract_abi.json"
with abi_path.open("w", encoding="utf-8") as file:
    json.dump(contract_data["abi"], file, indent=2)

print("Contract compiled successfully!")
print(f"Created: {compiled_path}")
print(f"Created: {abi_path}")