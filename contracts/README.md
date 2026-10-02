# Authenticity Validator for Academia

A local demonstration that combines candidate registration, document extraction, basic authenticity signals, text-based identity matching, optional QR decoding, Ganache identity lookup, configurable eligibility rules, and a persistent verification history.

Automated checks are limited indicators. They do not prove a person's real-world identity or detect every forged document. Original files stay off-chain; only candidate identity metadata is registered in the contract.

## Start on Windows

1. Install and start Ganache. Use its default RPC URL `http://127.0.0.1:7545`, or set your actual RPC URL in the environment file.
2. Open Remix at `https://remix.ethereum.org/`. Create a file named `DigitalIdentity.sol`, paste the contents of `DigitalIdentity.sol` from this project, and compile with Solidity `0.8.19` or newer in the `0.8.x` line.
3. In Remix, open **Deploy & Run Transactions**, choose **Injected Provider** only if you have configured a browser wallet for Ganache; otherwise select **Custom - External HTTP Provider** and enter your Ganache RPC URL. Select the Ganache account that will own the contract and deploy `DigitalIdentity`.
4. Copy the new deployed contract address. A Ganache reset creates a new chain state: the old address and its data no longer exist, so deploy again after a reset.
5. In `contracts/backend`, copy `.env.example` to `.env`. Put the new deployment address on `CONTRACT_ADDRESS=`, and set `CHAIN_ID=` to the chain ID reported by Ganache. Ganache commonly uses `1337` or `5777`; use the value shown by the running instance. Set `BLOCKCHAIN_SENDER=` to a currently listed Ganache account if you do not want the backend to use the first unlocked account automatically. No private key is needed or stored.
6. Install dependencies from a PowerShell terminal:

   ```powershell
   cd .\contracts\backend
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

   Optional OCR and QR features need their native tools too. For OCR, install the Tesseract executable and ensure `tesseract.exe` is on `PATH`; install packages with `pip install PyMuPDF Pillow pytesseract`. For QR decoding, install `opencv-python-headless`. If optional components are missing, the API reports the unavailable check and verification remains `REVIEW` rather than passing silently.
7. Start FastAPI from `contracts/backend`:

   ```powershell
   uvicorn main:app --reload
   ```

8. Open the application at `http://127.0.0.1:8000/` and the API explorer at `http://127.0.0.1:8000/docs`.

`uvicorn app:app --reload` is also supported. SQLite data is stored in `contracts/backend/app.db`; uploads are stored under `contracts/backend/uploads/` with generated filenames.

## Configure the Remix ABI

The project includes `contracts/backend/contract_abi.json` matching the current contract. If you change the Solidity interface, copy the ABI from Remix into that file (JSON array only), or set `CONTRACT_ABI_PATH` to another ABI file. `python compile.py` from `contracts/backend` compiles with `solc 0.8.19` when `py-solc-x` and the compiler are installed; it refreshes both the full compiler output and ABI file. `python deploy.py` can deploy to a running local Ganache instance using its first unlocked account and writes the resulting address and ABI to `deployment.json` and `contract_abi.json`.

## Demo walkthrough

1. Open **Candidate registration**, choose **Fill demo candidate**, confirm the wallet is a current Ganache account, then register. Without a deployed/configured contract, the candidate is saved locally with a clearly reported pending blockchain state.
2. Open **Documents & verify**, choose `CAND001`, upload a PDF/JPG/PNG and review the extraction fields. Use an academic document containing the candidate name, candidate ID, degree, branch, institution, CGPA, and passing year for the best extraction demonstration.
3. Set or keep the eligibility rules, then select **Run checks** on the uploaded file. Review each independent result and its limitations in **Verification result**.
4. Show **Verification history** for persisted attempts, **Recruiter desk** for search/filtering, and **Candidate details** for the profile and uploaded documents.

## API routes

- `GET /health` and `GET /blockchain/status`
- `POST /register`; `GET /identity/{wallet_address}`
- `POST /upload-document`; `POST /verify`
- `GET /candidates`; `GET /candidates/{candidate_id}`
- `GET /verification-history`; `GET /eligibility/{candidate_id}`
- `GET /docs`
