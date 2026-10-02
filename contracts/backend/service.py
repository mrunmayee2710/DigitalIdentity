from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from web3 import Web3

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
load_dotenv(BASE_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'app.db'}")
if DATABASE_URL.startswith("sqlite:///./"):
    DB_PATH = BASE_DIR / DATABASE_URL.removeprefix("sqlite:///./")
elif DATABASE_URL.startswith("sqlite:///"):
    DB_PATH = Path(DATABASE_URL.removeprefix("sqlite:///"))
else:
    raise RuntimeError("This demo currently supports SQLite DATABASE_URL values only.")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads"))).resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_TYPES = {".pdf", ".jpg", ".jpeg", ".png"}
RPC_URL = os.getenv("BLOCKCHAIN_RPC_URL", "http://127.0.0.1:7545")
EXPECTED_CHAIN_ID = os.getenv("CHAIN_ID", "").strip()
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS", "").strip()
BLOCKCHAIN_SENDER = os.getenv("BLOCKCHAIN_SENDER", "").strip()
ABI_PATH = Path(os.getenv("CONTRACT_ABI_PATH", str(BASE_DIR / "contract_abi.json")))

# The ABI is kept beside the app and must match the Solidity contract deployed in Remix.
CONTRACT_ABI: list[dict[str, Any]] = []
try:
    CONTRACT_ABI = json.loads(ABI_PATH.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    pass

web3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 2}))
app = FastAPI(title="Authenticity Validator for Academia", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@contextmanager
def get_db():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with get_db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                institution TEXT NOT NULL,
                course TEXT NOT NULL,
                branch TEXT NOT NULL,
                passing_year INTEGER NOT NULL,
                cgpa REAL NOT NULL,
                wallet_address TEXT NOT NULL,
                registration_status TEXT NOT NULL DEFAULT 'PENDING',
                blockchain_tx TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                stored_name TEXT NOT NULL UNIQUE,
                document_type TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                extracted_text TEXT NOT NULL DEFAULT '',
                extracted_fields TEXT NOT NULL DEFAULT '{}',
                upload_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'UPLOADED'
            );
            CREATE TABLE IF NOT EXISTS verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id) ON DELETE CASCADE,
                document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                identity_status TEXT NOT NULL,
                authenticity_status TEXT NOT NULL,
                qr_status TEXT NOT NULL,
                blockchain_status TEXT NOT NULL,
                eligibility_status TEXT NOT NULL,
                final_status TEXT NOT NULL,
                results_json TEXT NOT NULL,
                verification_date TEXT NOT NULL
            );
            """
        )


init_db()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_contract() -> Any | None:
    if not CONTRACT_ADDRESS or not CONTRACT_ABI or not web3.is_connected():
        return None
    try:
        address = Web3.to_checksum_address(CONTRACT_ADDRESS)
        if not web3.eth.get_code(address):
            return None
        return web3.eth.contract(address=address, abi=CONTRACT_ABI)
    except Exception:
        return None


def blockchain_status() -> dict[str, Any]:
    try:
        connected = web3.is_connected()
        actual_chain = web3.eth.chain_id if connected else None
        contract_code = b""
        valid_address = False
        if CONTRACT_ADDRESS:
            try:
                checked = Web3.to_checksum_address(CONTRACT_ADDRESS)
                valid_address = True
                if connected:
                    contract_code = web3.eth.get_code(checked)
            except Exception:
                valid_address = False
        deployed = bool(contract_code)
        configured_chain = int(EXPECTED_CHAIN_ID) if EXPECTED_CHAIN_ID.isdigit() else None
        message = "Connected" if connected else "Ganache connection failed. Start Ganache and check BLOCKCHAIN_RPC_URL."
        if connected and configured_chain and actual_chain != configured_chain:
            message = f"Connected to chain {actual_chain}, but CHAIN_ID is configured as {configured_chain}."
        elif connected and not CONTRACT_ADDRESS:
            message = "Ganache is connected, but CONTRACT_ADDRESS is not configured."
        elif connected and CONTRACT_ADDRESS and not valid_address:
            message = "CONTRACT_ADDRESS is not a valid Ethereum address."
        elif connected and CONTRACT_ADDRESS and not deployed:
            message = "Smart contract is not deployed on the configured Ganache network. Deploy the contract and update CONTRACT_ADDRESS."
        accounts = list(web3.eth.accounts) if connected else []
        return {
            "connected": connected,
            "blockchain": connected,
            "rpc_url": RPC_URL,
            "chain_id": actual_chain,
            "expected_chain_id": configured_chain,
            "latest_block": web3.eth.block_number if connected else None,
            "contract_address": CONTRACT_ADDRESS or None,
            "contract_deployed": deployed,
            "active_account": (BLOCKCHAIN_SENDER or (accounts[0] if accounts else None)),
            "accounts": accounts,
            "message": message,
        }
    except Exception as exc:
        return {
            "connected": False,
            "blockchain": False,
            "rpc_url": RPC_URL,
            "chain_id": None,
            "latest_block": None,
            "contract_address": CONTRACT_ADDRESS or None,
            "contract_deployed": False,
            "active_account": None,
            "accounts": [],
            "message": f"Blockchain status unavailable: {exc}",
        }


class CandidateRegistration(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    candidate_id: str = Field(min_length=2, max_length=64)
    email: str = Field(min_length=5, max_length=254)
    institution: str = Field(min_length=2, max_length=200)
    course: str = Field(min_length=2, max_length=100)
    branch: str = Field(min_length=2, max_length=120)
    passing_year: int = Field(ge=1950, le=2100)
    cgpa: float = Field(ge=0, le=10)
    wallet_address: str = Field(min_length=42, max_length=42)


class VerifyRequest(BaseModel):
    candidate_id: str
    document_id: int
    required_cgpa: float = Field(default=7.5, ge=0, le=10)
    required_branch: str = "Computer Engineering"
    required_degree: str = "B.Tech"
    required_year: int = Field(default=2024, ge=1950, le=2100)


def candidate_dict(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["record_id"] = result.pop("id")
    return result


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def extract_fields(text: str) -> dict[str, str]:
    patterns = {
        "name": r"(?:name|student name|candidate)\s*[:\-]\s*([A-Za-z][A-Za-z .'-]{2,80})",
        "candidate_id": r"(?:candidate\s*id|roll\s*(?:no|number)|registration\s*(?:no|number)|reg\s*no)\s*[:#\-]?\s*([A-Za-z0-9\-/]{3,40})",
        "degree": r"\b(B\.?\s*Tech|Bachelor of Technology|B\.?E\.?|Bachelor of Engineering|M\.?\s*Tech)\b",
        "branch": r"(?:branch|speciali[sz]ation|department)\s*[:\-]\s*([A-Za-z &-]{3,80})",
        "institution": r"(?:institution|university|college)\s*[:\-]\s*([A-Za-z0-9 &.,'-]{3,100})",
        "cgpa": r"(?:cgpa|cpi|grade point average)\s*[:\-]?\s*(\d{1,2}(?:\.\d{1,2})?)",
        "passing_year": r"(?:passing year|year of passing|graduation year)\s*[:\-]?\s*(20\d{2})",
    }
    result = {key: "Not detected" for key in patterns}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result[key] = re.sub(r"\s+", " ", match.group(1)).strip(" .,:;-" )
    return result


def read_document(path: Path, extension: str) -> tuple[str, dict[str, Any]]:
    text = ""
    findings: list[str] = []
    metadata: dict[str, Any] = {}
    if extension == ".pdf":
        try:
            import fitz

            with fitz.open(path) as pdf:
                text = "\n".join(page.get_text() for page in pdf)
                metadata = pdf.metadata or {}
                if metadata.get("modDate"):
                    findings.append("PDF contains a modification timestamp; review it against the issuing institution's record.")
        except ImportError:
            try:
                from pypdf import PdfReader

                reader = PdfReader(str(path))
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
                metadata = {str(key): str(value) for key, value in (reader.metadata or {}).items()}
            except ImportError:
                findings.append("PDF text extraction is unavailable; install PyMuPDF or pypdf.")
            except Exception:
                findings.append("PDF text could not be extracted.")
        except Exception:
            findings.append("PDF structure or text could not be read.")
    else:
        try:
            from PIL import Image
            from pytesseract import image_to_string

            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                text = image_to_string(image)
                metadata = {"format": image.format, "size": image.size, "mode": image.mode}
        except ImportError:
            findings.append("Image OCR is unavailable; install Pillow and pytesseract with the Tesseract executable.")
        except Exception:
            findings.append("Image OCR could not read this file; check image quality and Tesseract installation.")
    fields = extract_fields(text)
    missing_fields = [key for key in ("name", "candidate_id", "degree", "institution", "cgpa", "passing_year") if fields[key] == "Not detected"]
    if missing_fields:
        findings.append("Expected academic fields were not detected: " + ", ".join(missing_fields) + ".")
    if not text.strip():
        findings.append("No document text was extracted. Upload a legible scan or searchable PDF for field matching.")
    return text, {"fields": fields, "metadata": metadata, "findings": findings}


def decode_qr(path: Path) -> tuple[str, str]:
    try:
        import cv2

        image = cv2.imread(str(path))
        if image is None:
            return "NOT_AVAILABLE", "QR decoder could not read this document image."
        value, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
        return ("DETECTED", value) if value else ("NOT_AVAILABLE", "No QR code was detected.")
    except ImportError:
        return "NOT_AVAILABLE", "QR decoding is unavailable; install opencv-python-headless."
    except Exception:
        return "NOT_AVAILABLE", "QR decoding could not process this document."


def assess_identity(candidate: dict[str, Any], extracted: dict[str, str]) -> tuple[str, list[dict[str, str]]]:
    comparisons: list[dict[str, str]] = []
    for key, registered in (("name", candidate["name"]), ("candidate_id", candidate["candidate_id"])):
        found = extracted.get(key, "Not detected")
        state = "NOT_DETECTED" if found == "Not detected" else ("PASS" if normalized(found) == normalized(str(registered)) else "FAILED")
        comparisons.append({"field": key, "registered": str(registered), "document": found, "status": state})
    states = [item["status"] for item in comparisons]
    if "FAILED" in states:
        return "FAILED", comparisons
    if all(state == "PASS" for state in states):
        return "PASS", comparisons
    return "REVIEW", comparisons


def assess_authenticity(text: str, extension: str, metadata: dict[str, Any], findings: list[str]) -> tuple[str, list[str]]:
    issues = list(findings)
    if len(text.strip()) < 40:
        issues.append("Very little readable text is available for document review.")
    if re.search(r"\b(sample|specimen|not valid|fake|dummy|template)\b", text, re.IGNORECASE):
        issues.append("Document contains a sample, specimen, or template marker.")
    if extension == ".pdf" and not metadata and text.strip():
        issues.append("PDF metadata is unavailable; file provenance cannot be assessed.")
    if any("could not" in item.lower() or "unavailable" in item.lower() or "modification timestamp" in item.lower() for item in issues):
        return "REVIEW", issues
    if any("sample" in item.lower() or "template marker" in item.lower() for item in issues):
        return "FAILED", issues
    return ("PASS", ["Basic structure and readable-text checks completed; this is not proof against sophisticated forgery."]) if text.strip() and not issues else ("REVIEW", issues)


def assess_blockchain(wallet_address: str) -> dict[str, Any]:
    status = blockchain_status()
    result = {"status": "UNAVAILABLE", "message": status["message"], "identity_found": False, "identity": None}
    contract = get_contract()
    if not status["connected"] or not status["contract_deployed"] or contract is None:
        return result
    try:
        address = Web3.to_checksum_address(wallet_address)
        value = contract.functions.getIdentity(address).call()
        exists = bool(value[0])
        details = {"name": value[1], "candidate_id": value[2], "institution": value[3], "registered_at": value[4], "verified": value[5]}
        result.update(status="FOUND" if exists else "NOT_FOUND", identity_found=exists, identity=details, message="On-chain identity found." if exists else "No on-chain identity is registered for this wallet.")
    except Exception as exc:
        result.update(status="ERROR", message=f"Contract identity lookup failed: {exc}")
    return result


@app.get("/")
def home() -> FileResponse:
    return FileResponse(PROJECT_DIR / "frontend" / "index.html")


@app.get("/health")
def health() -> dict[str, Any]:
    state = blockchain_status()
    return {"status": "ok", **state}


@app.get("/blockchain/status")
def get_blockchain_status() -> dict[str, Any]:
    return blockchain_status()


@app.get("/contract")
def contract_info() -> dict[str, Any]:
    return blockchain_status()


@app.get("/stats")
def get_stats() -> dict[str, Any]:
    state = blockchain_status()
    with get_db() as connection:
        counts = connection.execute(
            "SELECT COUNT(*) candidates, SUM(CASE WHEN registration_status='REGISTERED' THEN 1 ELSE 0 END) registered FROM candidates"
        ).fetchone()
        verification = connection.execute("SELECT final_status, COUNT(*) count FROM verifications GROUP BY final_status").fetchall()
    return {**state, "total_candidates": counts["candidates"], "registered_candidates": counts["registered"] or 0, "verification_counts": {row["final_status"]: row["count"] for row in verification}}


@app.post("/register")
def register_candidate(payload: CandidateRegistration) -> dict[str, Any]:
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", payload.email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    try:
        wallet = Web3.to_checksum_address(payload.wallet_address)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Enter a valid 42-character Ethereum wallet address.") from exc
    now = utc_now()
    try:
        with get_db() as connection:
            connection.execute(
                "INSERT INTO candidates(candidate_id,name,email,institution,course,branch,passing_year,cgpa,wallet_address,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (payload.candidate_id.strip(), payload.name.strip(), payload.email.strip(), payload.institution.strip(), payload.course.strip(), payload.branch.strip(), payload.passing_year, payload.cgpa, wallet, now),
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Candidate ID or email is already registered.") from exc
    chain_result = {"status": "UNAVAILABLE", "message": blockchain_status()["message"], "transaction_hash": None}
    contract = get_contract()
    if contract is not None:
        try:
            sender = Web3.to_checksum_address(BLOCKCHAIN_SENDER) if BLOCKCHAIN_SENDER else web3.eth.accounts[0]
            tx_hash = contract.functions.registerIdentity(wallet, payload.name.strip(), payload.candidate_id.strip(), payload.institution.strip()).transact({"from": sender})
            receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            chain_result = {"status": "REGISTERED", "message": "Identity registered on-chain.", "transaction_hash": receipt.transactionHash.hex()}
            with get_db() as connection:
                connection.execute("UPDATE candidates SET registration_status='REGISTERED', blockchain_tx=? WHERE candidate_id=?", (chain_result["transaction_hash"], payload.candidate_id.strip()))
        except Exception as exc:
            chain_result = {"status": "PENDING", "message": f"Candidate saved locally; blockchain registration failed: {exc}", "transaction_hash": None}
    with get_db() as connection:
        row = connection.execute("SELECT * FROM candidates WHERE candidate_id=?", (payload.candidate_id.strip(),)).fetchone()
    return {"message": "Registration Successful" if chain_result["status"] == "REGISTERED" else "Candidate saved; blockchain registration is pending.", "candidate": candidate_dict(row), "blockchain": chain_result}


@app.get("/identity/{wallet_address}")
def get_identity(wallet_address: str) -> dict[str, Any]:
    try:
        wallet = Web3.to_checksum_address(wallet_address)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid Ethereum wallet address format.") from exc
    state = blockchain_status()
    contract = get_contract()
    if not state["connected"]:
        raise HTTPException(status_code=503, detail=state["message"])
    if not state["contract_deployed"] or contract is None:
        raise HTTPException(status_code=503, detail=state["message"])
    try:
        result = contract.functions.getIdentity(wallet).call()
        exists = bool(result[0])
        identity = {"name": result[1], "candidate_id": result[2], "institution": result[3], "registered_at": result[4], "verified": result[5]} if exists else None
        if not exists:
            raise HTTPException(status_code=404, detail="No identity is registered for this wallet address on the configured contract.")
        return {"address": wallet, "exists": True, "identity": identity}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not read identity from the configured contract: {exc}") from exc


@app.get("/candidates")
def get_candidates(search: str = "", status: str = "", eligibility: str = "") -> list[dict[str, Any]]:
    query = "SELECT c.*, (SELECT v.final_status FROM verifications v WHERE v.candidate_id=c.candidate_id ORDER BY v.id DESC LIMIT 1) final_status, (SELECT v.eligibility_status FROM verifications v WHERE v.candidate_id=c.candidate_id ORDER BY v.id DESC LIMIT 1) eligibility_status FROM candidates c WHERE 1=1"
    params: list[Any] = []
    if search.strip():
        query += " AND (c.name LIKE ? OR c.candidate_id LIKE ? OR c.institution LIKE ?)"
        wildcard = f"%{search.strip()}%"
        params.extend([wildcard, wildcard, wildcard])
    if status == "PENDING":
        query += " AND NOT EXISTS (SELECT 1 FROM verifications v WHERE v.candidate_id=c.candidate_id)"
    elif status in {"VERIFIED", "FAILED"}:
        query += " AND (SELECT v.final_status FROM verifications v WHERE v.candidate_id=c.candidate_id ORDER BY v.id DESC LIMIT 1)=?"
        params.append(status)
    if eligibility in {"ELIGIBLE", "NOT_ELIGIBLE"}:
        query += " AND (SELECT v.eligibility_status FROM verifications v WHERE v.candidate_id=c.candidate_id ORDER BY v.id DESC LIMIT 1)=?"
        params.append(eligibility)
    query += " ORDER BY c.created_at DESC"
    with get_db() as connection:
        return [candidate_dict(row) for row in connection.execute(query, params).fetchall()]


@app.get("/candidates/{candidate_id}")
def get_candidate(candidate_id: str) -> dict[str, Any]:
    with get_db() as connection:
        row = connection.execute("SELECT * FROM candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Candidate was not found.")
        candidate = candidate_dict(row)
        candidate["documents"] = [dict(document) for document in connection.execute("SELECT id, filename, document_type, sha256, upload_date, status FROM documents WHERE candidate_id=? ORDER BY id DESC", (candidate_id,)).fetchall()]
        verification = connection.execute("SELECT results_json FROM verifications WHERE candidate_id=? ORDER BY id DESC LIMIT 1", (candidate_id,)).fetchone()
        candidate["latest_verification"] = json.loads(verification["results_json"]) if verification else None
        if candidate["latest_verification"]:
            candidate["final_status"] = candidate["latest_verification"]["final_status"]
            candidate["eligibility_status"] = candidate["latest_verification"]["eligibility"]["status"]
        else:
            candidate["final_status"] = None
            candidate["eligibility_status"] = None
        return candidate


@app.post("/upload-document")
async def upload_document(candidate_id: str = Form(...), document_type: str = Form("Academic credential"), file: UploadFile = File(...)) -> dict[str, Any]:
    with get_db() as connection:
        if connection.execute("SELECT 1 FROM candidates WHERE candidate_id=?", (candidate_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Register this candidate before uploading a document.")
    original = Path(file.filename or "document").name
    extension = Path(original).suffix.lower()
    if extension not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Upload a PDF, JPG, JPEG, or PNG file.")
    data = await file.read(MAX_FILE_SIZE + 1)
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded document is empty.")
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Document exceeds the 10 MB upload limit.")
    stored_name = f"{uuid.uuid4().hex}{extension}"
    path = UPLOAD_DIR / stored_name
    path.write_bytes(data)
    text, analysis = read_document(path, extension)
    digest = hashlib.sha256(data).hexdigest()
    now = utc_now()
    try:
        with get_db() as connection:
            cursor = connection.execute("INSERT INTO documents(candidate_id,filename,stored_name,document_type,sha256,extracted_text,extracted_fields,upload_date) VALUES(?,?,?,?,?,?,?,?)", (candidate_id, original, stored_name, document_type.strip() or "Academic credential", digest, text, json.dumps(analysis), now))
            document_id = cursor.lastrowid
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {"message": "Document uploaded and processed.", "document_id": document_id, "candidate_id": candidate_id, "filename": original, "document_type": document_type, "sha256": digest, "upload_date": now, "extracted_fields": analysis["fields"], "processing_findings": analysis["findings"], "status": "UPLOADED"}


@app.get("/documents/{candidate_id}")
def get_documents(candidate_id: str) -> list[dict[str, Any]]:
    with get_db() as connection:
        return [dict(row) for row in connection.execute("SELECT id, candidate_id, filename, document_type, sha256, upload_date, status FROM documents WHERE candidate_id=? ORDER BY id DESC", (candidate_id,)).fetchall()]


@app.post("/verify")
def verify_document(payload: VerifyRequest) -> dict[str, Any]:
    with get_db() as connection:
        candidate_row = connection.execute("SELECT * FROM candidates WHERE candidate_id=?", (payload.candidate_id,)).fetchone()
        document_row = connection.execute("SELECT * FROM documents WHERE id=? AND candidate_id=?", (payload.document_id, payload.candidate_id)).fetchone()
    if candidate_row is None:
        raise HTTPException(status_code=404, detail="Candidate was not found.")
    if document_row is None:
        raise HTTPException(status_code=404, detail="Document was not found for this candidate.")
    candidate = candidate_dict(candidate_row)
    document = dict(document_row)
    analysis = json.loads(document["extracted_fields"])
    fields = analysis.get("fields", {})
    identity_status, comparisons = assess_identity(candidate, fields)
    authenticity_status, authenticity_findings = assess_authenticity(document["extracted_text"], Path(document["filename"]).suffix.lower(), analysis.get("metadata", {}), analysis.get("findings", []))
    qr_status, qr_value = decode_qr(UPLOAD_DIR / document["stored_name"])
    if qr_status == "DETECTED":
        qr_status = "PASS" if normalized(candidate["candidate_id"]) in normalized(qr_value) or normalized(candidate["name"]) in normalized(qr_value) else "FAILED"
    chain = assess_blockchain(candidate["wallet_address"])
    if chain["status"] == "FOUND":
        chain_identity = chain.get("identity") or {}
        if normalized(chain_identity.get("candidate_id", "")) != normalized(candidate["candidate_id"]):
            chain.update(status="MISMATCH", message="The on-chain candidate ID does not match this candidate.")
    eligibility_checks = [
        {"rule": f"CGPA >= {payload.required_cgpa:.1f}", "passed": candidate["cgpa"] >= payload.required_cgpa, "actual": candidate["cgpa"]},
        {"rule": f"Branch matches {payload.required_branch}", "passed": normalized(payload.required_branch) in normalized(candidate["branch"]), "actual": candidate["branch"]},
        {"rule": f"Degree matches {payload.required_degree}", "passed": normalized(payload.required_degree) in normalized(candidate["course"]), "actual": candidate["course"]},
        {"rule": f"Passing year >= {payload.required_year}", "passed": candidate["passing_year"] >= payload.required_year, "actual": candidate["passing_year"]},
    ]
    eligibility_status = "ELIGIBLE" if all(item["passed"] for item in eligibility_checks) else "NOT_ELIGIBLE"
    critical_pass = identity_status == "PASS" and authenticity_status == "PASS" and chain["status"] == "FOUND" and eligibility_status == "ELIGIBLE"
    critical_fail = identity_status == "FAILED" or authenticity_status == "FAILED" or chain["status"] in {"MISMATCH", "NOT_FOUND"}
    technical_checks_pass = identity_status == "PASS" and authenticity_status == "PASS" and chain["status"] == "FOUND"
    final_status = "VERIFIED" if critical_pass else ("FAILED" if critical_fail else ("NOT_ELIGIBLE" if technical_checks_pass else "REVIEW"))
    result = {
        "candidate": {"candidate_id": candidate["candidate_id"], "name": candidate["name"], "institution": candidate["institution"], "wallet_address": candidate["wallet_address"]},
        "document": {"document_id": document["id"], "filename": document["filename"], "document_type": document["document_type"], "sha256": document["sha256"]},
        "ocr": {"fields": fields, "text_available": bool(document["extracted_text"].strip())},
        "identity": {"status": identity_status, "comparisons": comparisons, "limitation": "This compares registered and extracted text only; it does not prove real-world identity."},
        "authenticity": {"status": authenticity_status, "findings": authenticity_findings, "limitation": "Basic automated checks cannot detect every forged document."},
        "qr": {"status": qr_status, "detected": qr_status in {"PASS", "FAILED"}, "decoded_value": qr_value},
        "blockchain": chain,
        "eligibility": {"status": eligibility_status, "checks": eligibility_checks},
        "final_status": final_status,
        "verification_date": utc_now(),
    }
    with get_db() as connection:
        cursor = connection.execute("INSERT INTO verifications(candidate_id,document_id,identity_status,authenticity_status,qr_status,blockchain_status,eligibility_status,final_status,results_json,verification_date) VALUES(?,?,?,?,?,?,?,?,?,?)", (candidate["candidate_id"], document["id"], identity_status, authenticity_status, qr_status, chain["status"], eligibility_status, final_status, json.dumps(result), result["verification_date"]))
        verification_id = cursor.lastrowid
        connection.execute("UPDATE documents SET status=? WHERE id=?", (final_status, document["id"]))
    result["verification_id"] = verification_id
    return result


@app.get("/verification-history")
def verification_history(candidate_id: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT v.*, c.name, d.filename FROM verifications v JOIN candidates c ON c.candidate_id=v.candidate_id JOIN documents d ON d.id=v.document_id"
    params: tuple[Any, ...] = ()
    if candidate_id:
        query += " WHERE v.candidate_id=?"
        params = (candidate_id,)
    query += " ORDER BY v.verification_date DESC"
    with get_db() as connection:
        rows = connection.execute(query, params).fetchall()
    return [{**dict(row), "results": json.loads(row["results_json"])} for row in rows]


@app.get("/eligibility/{candidate_id}")
def get_eligibility(candidate_id: str, required_cgpa: float = 7.5, required_branch: str = "Computer Engineering", required_degree: str = "B.Tech", required_year: int = 2024) -> dict[str, Any]:
    with get_db() as connection:
        row = connection.execute("SELECT * FROM candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Candidate was not found.")
    candidate = candidate_dict(row)
    checks = [
        {"rule": f"CGPA >= {required_cgpa:.1f}", "passed": candidate["cgpa"] >= required_cgpa, "actual": candidate["cgpa"]},
        {"rule": f"Branch matches {required_branch}", "passed": normalized(required_branch) in normalized(candidate["branch"]), "actual": candidate["branch"]},
        {"rule": f"Degree matches {required_degree}", "passed": normalized(required_degree) in normalized(candidate["course"]), "actual": candidate["course"]},
        {"rule": f"Passing year >= {required_year}", "passed": candidate["passing_year"] >= required_year, "actual": candidate["passing_year"]},
    ]
    return {"candidate_id": candidate_id, "status": "ELIGIBLE" if all(item["passed"] for item in checks) else "NOT_ELIGIBLE", "checks": checks}


@app.post("/verify/{wallet_address}")
def legacy_verify_identity(wallet_address: str) -> dict[str, Any]:
    try:
        identity = get_identity(wallet_address)
        contract = get_contract()
        sender = Web3.to_checksum_address(BLOCKCHAIN_SENDER) if BLOCKCHAIN_SENDER else web3.eth.accounts[0]
        tx_hash = contract.functions.verifyIdentity(Web3.to_checksum_address(wallet_address)).transact({"from": sender})
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
        return {"message": "Identity verified successfully.", "transaction_hash": receipt.transactionHash.hex(), "identity": identity}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Blockchain verification failed: {exc}") from exc


app.mount("/static", StaticFiles(directory=PROJECT_DIR / "frontend"), name="static")
