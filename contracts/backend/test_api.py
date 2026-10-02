import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TEMP_DIR = tempfile.TemporaryDirectory(prefix="academia-validator-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(TEMP_DIR.name, 'test.db')}"
os.environ["UPLOAD_DIR"] = str(Path(TEMP_DIR.name, "uploads"))
os.environ["BLOCKCHAIN_RPC_URL"] = "http://127.0.0.1:1"
os.environ["CONTRACT_ADDRESS"] = ""
os.environ["CHAIN_ID"] = ""

from fastapi.testclient import TestClient

import service


class CredentialApiTests(unittest.TestCase):
    def setUp(self):
        with service.get_db() as connection:
            connection.execute("DELETE FROM verifications")
            connection.execute("DELETE FROM documents")
            connection.execute("DELETE FROM candidates")
        self.offline = {
            "connected": False,
            "blockchain": False,
            "rpc_url": "http://127.0.0.1:1",
            "chain_id": None,
            "expected_chain_id": None,
            "latest_block": None,
            "contract_address": None,
            "contract_deployed": False,
            "active_account": None,
            "accounts": [],
            "message": "Ganache connection failed. Start Ganache and check BLOCKCHAIN_RPC_URL.",
        }
        self.status_patch = patch.object(service, "blockchain_status", return_value=self.offline)
        self.connected_patch = patch.object(service.web3, "is_connected", return_value=False)
        self.status_patch.start()
        self.connected_patch.start()
        self.client = TestClient(service.app)

    def tearDown(self):
        self.connected_patch.stop()
        self.status_patch.stop()

    def test_registration_eligibility_and_identity_errors(self):
        response = self.client.post("/register", json={
            "name": "Rahul Sharma",
            "candidate_id": "CAND001",
            "email": "rahul@example.edu",
            "institution": "National Institute of Technology",
            "course": "B.Tech",
            "branch": "Computer Engineering",
            "passing_year": 2025,
            "cgpa": 8.2,
            "wallet_address": "0x1111111111111111111111111111111111111111",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["blockchain"]["status"], "UNAVAILABLE")
        self.assertEqual(self.client.get("/eligibility/CAND001").json()["status"], "ELIGIBLE")
        self.assertEqual(self.client.get("/identity/not-an-address").status_code, 400)
        self.assertEqual(self.client.get("/identity/0x1111111111111111111111111111111111111111").status_code, 503)

    def test_upload_verify_and_history_remain_transparent_offline(self):
        registration = self.client.post("/register", json={
            "name": "Rahul Sharma",
            "candidate_id": "CAND001",
            "email": "rahul2@example.edu",
            "institution": "National Institute of Technology",
            "course": "B.Tech",
            "branch": "Computer Engineering",
            "passing_year": 2025,
            "cgpa": 8.2,
            "wallet_address": "0x2222222222222222222222222222222222222222",
        })
        self.assertEqual(registration.status_code, 200, registration.text)
        upload = self.client.post("/upload-document", data={"candidate_id": "CAND001", "document_type": "Transcript"}, files={"file": ("marksheet.pdf", b"%PDF-1.4 demo scan", "application/pdf")})
        self.assertEqual(upload.status_code, 200, upload.text)
        self.assertTrue(upload.json()["document_id"])
        result = self.client.post("/verify", json={"candidate_id": "CAND001", "document_id": upload.json()["document_id"]})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["final_status"], "REVIEW")
        self.assertEqual(result.json()["blockchain"]["status"], "UNAVAILABLE")
        self.assertEqual(result.json()["qr"]["status"], "NOT_AVAILABLE")
        self.assertEqual(len(self.client.get("/verification-history").json()), 1)
        self.assertEqual(self.client.get("/candidates/CAND001").json()["latest_verification"]["final_status"], "REVIEW")

    def test_health_and_app_are_served(self):
        self.assertEqual(self.client.get("/health").json()["status"], "ok")
        self.assertIn("BLOCKCHAIN_RPC_URL", self.client.get("/health").json()["message"])
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/static/script.js").status_code, 200)


if __name__ == "__main__":
    unittest.main()
