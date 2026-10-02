const API = "";
const pageTitles = {
  dashboard: ["Overview", "ACADEMIC CREDENTIALS"],
  register: ["Candidate registration", "CANDIDATE ONBOARDING"],
  documents: ["Documents & verification", "DOCUMENT REVIEW"],
  results: ["Verification result", "ASSESSMENT"],
  history: ["Verification history", "AUDIT TRAIL"],
  recruiter: ["Recruiter desk", "RECRUITER / ADMIN"],
  details: ["Candidate details", "CANDIDATE PROFILE"],
};
let candidates = [];
let blockchain = null;
let latestUpload = null;
let latestResult = null;

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
const short = value => value ? `${value.slice(0, 9)}…${value.slice(-5)}` : "Not configured";
const dateText = value => value ? new Date(value).toLocaleString() : "--";
const statusClass = value => String(value || "pending").toLowerCase().replace(/[^a-z_]/g, "_");
const badge = value => `<span class="badge ${statusClass(value)}">${esc(value || "PENDING")}</span>`;

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API}${path}`, options);
  } catch {
    throw new Error("Cannot reach the API. Start FastAPI and reload this page.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || data.message || `Request failed (${response.status}).`);
  return data;
}

function toast(message, kind = "") {
  const item = document.createElement("div");
  item.className = `toast ${kind}`;
  item.textContent = message;
  $("#toastRegion").append(item);
  setTimeout(() => item.remove(), 5000);
}

function navigate(page) {
  if (!pageTitles[page]) return;
  $$(".page").forEach(view => view.classList.toggle("active", view.id === `${page}-page`));
  $$(".nav-link").forEach(link => link.classList.toggle("active", link.dataset.page === page));
  $("#pageTitle").textContent = pageTitles[page][0];
  $("#pageEyebrow").textContent = pageTitles[page][1];
  history.replaceState(null, "", `#${page}`);
  if (page === "recruiter") loadCandidates();
  if (page === "history") loadHistory();
}

async function loadBlockchain() {
  try {
    blockchain = await request("/blockchain/status");
    const online = blockchain.connected && blockchain.contract_deployed;
    $("#networkDot").className = `status-dot ${online ? "online" : "offline"}`;
    $("#networkLabel").textContent = blockchain.connected ? (blockchain.contract_deployed ? "Contract deployed" : "Ganache connected") : "Ganache offline";
    $("#networkMessage").textContent = blockchain.message;
    $("#sideChain").textContent = blockchain.chain_id ?? "--";
    $("#sideBlock").textContent = blockchain.latest_block ?? "--";
    $("#contractState").textContent = blockchain.contract_deployed ? "DEPLOYED" : (blockchain.connected ? "NOT DEPLOYED" : "DISCONNECTED");
    $("#contractState").className = `status-pill ${online ? "online" : "offline"}`;
    $("#rpcValue").textContent = blockchain.rpc_url || "--";
    $("#chainValue").textContent = blockchain.chain_id ?? "--";
    $("#blockValue").textContent = blockchain.latest_block ?? "--";
    $("#contractValue").textContent = short(blockchain.contract_address);
    if (!$("#regWallet").value && blockchain.active_account) $("#regWallet").value = blockchain.active_account;
  } catch (error) {
    $("#networkLabel").textContent = "API unavailable";
    $("#networkMessage").textContent = error.message;
    $("#networkDot").className = "status-dot offline";
  }
}

async function loadCandidates() {
  try {
    candidates = await request("/candidates");
    populateCandidateSelects();
    renderCandidates(candidates);
    renderMetrics(candidates);
  } catch (error) {
    toast(error.message, "error");
  }
}

function populateCandidateSelects() {
  const selects = [$("#uploadCandidate"), $("#historyCandidate")];
  for (const select of selects) {
    if (!select) continue;
    const current = select.value;
    const allLabel = select.id === "historyCandidate" ? "All candidates" : "Select a candidate";
    select.innerHTML = `<option value="">${allLabel}</option>` + candidates.map(c => `<option value="${esc(c.candidate_id)}">${esc(c.name)} · ${esc(c.candidate_id)}</option>`).join("");
    if (candidates.some(c => c.candidate_id === current)) select.value = current;
  }
}

function renderMetrics(rows) {
  const verified = rows.filter(c => c.final_status === "VERIFIED").length;
  const review = rows.filter(c => !c.final_status || c.final_status === "REVIEW").length;
  const eligible = rows.filter(c => c.eligibility_status === "ELIGIBLE").length;
  $("#metricCandidates").textContent = rows.length;
  $("#metricVerified").textContent = verified;
  $("#metricReview").textContent = review;
  $("#metricEligible").textContent = eligible;
}

function renderCandidates(rows) {
  const body = $("#candidateBody");
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="8" class="empty-cell">No matching candidates found.</td></tr>';
    return;
  }
  body.innerHTML = rows.map(c => `<tr>
    <td><strong>${esc(c.name)}</strong><br><span class="muted">${esc(c.email)}</span></td>
    <td class="mono">${esc(c.candidate_id)}</td><td>${esc(c.institution)}</td><td>${esc(c.course)} · ${esc(c.branch)}</td>
    <td>${Number(c.cgpa).toFixed(2)}</td><td>${badge(c.final_status || "PENDING")}</td><td>${badge(c.eligibility_status || "PENDING")}</td>
    <td><button class="text-button" data-candidate="${esc(c.candidate_id)}">Open →</button></td>
  </tr>`).join("");
  $$('button[data-candidate]', body).forEach(button => button.addEventListener("click", () => openCandidate(button.dataset.candidate)));
}

async function loadDashboard() {
  await Promise.all([loadBlockchain(), loadCandidates()]);
  try {
    const historyRows = await request("/verification-history");
    const body = $("#recentBody");
    body.innerHTML = historyRows.length ? historyRows.slice(0, 5).map(row => `<tr><td><strong>${esc(row.name)}</strong><br><span class="muted">${esc(row.candidate_id)}</span></td><td>${esc(row.filename)}</td><td>${dateText(row.verification_date)}</td><td>${badge(row.final_status)}</td><td><button class="text-button" data-result="${row.id}">Details →</button></td></tr>`).join("") : '<tr><td colspan="5" class="empty-cell">No verification attempts yet.</td></tr>';
    $$('button[data-result]', body).forEach(button => button.addEventListener("click", () => showHistoryResult(Number(button.dataset.result))));
  } catch (error) {
    toast(error.message, "error");
  }
}

$("#demoCandidate").addEventListener("click", () => {
  $("#regName").value = "Rahul Sharma";
  $("#regCandidateId").value = "CAND001";
  $("#regEmail").value = "rahul.sharma@example.edu";
  $("#regInstitution").value = "National Institute of Technology";
  $("#regCourse").value = "B.Tech";
  $("#regBranch").value = "Computer Engineering";
  $("#regYear").value = "2025";
  $("#regCgpa").value = "8.2";
  if (blockchain?.active_account) $("#regWallet").value = blockchain.active_account;
});

$("#registerForm").addEventListener("submit", async event => {
  event.preventDefault();
  const button = $("#registerButton");
  button.disabled = true;
  const fields = Object.fromEntries(new FormData(event.currentTarget).entries());
  fields.passing_year = Number(fields.passing_year);
  fields.cgpa = Number(fields.cgpa);
  try {
    const result = await request("/register", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(fields) });
    const chain = result.blockchain;
    $("#registrationResult").classList.remove("hidden");
    $("#registrationResult").innerHTML = `<strong>${esc(result.message)}</strong><br>Candidate ${esc(result.candidate.candidate_id)} was saved locally. Blockchain: ${esc(chain.status)}. ${esc(chain.message)}${chain.transaction_hash ? `<br>Transaction: <span class="mono">${esc(chain.transaction_hash)}</span>` : ""}`;
    toast(result.message, chain.status === "REGISTERED" ? "success" : "");
    await loadDashboard();
    await loadCandidates();
    $("#uploadCandidate").value = result.candidate.candidate_id;
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.disabled = false;
  }
});

$("#documentFile").addEventListener("change", event => {
  const file = event.target.files[0];
  $("#fileName").textContent = file ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB` : "Choose a file to upload";
});

$("#uploadForm").addEventListener("submit", async event => {
  event.preventDefault();
  const file = $("#documentFile").files[0];
  const candidateId = $("#uploadCandidate").value;
  if (!file || !candidateId) return toast("Select a candidate and a document first.", "error");
  if (file.size > 10 * 1024 * 1024) return toast("Document exceeds the 10 MB limit.", "error");
  const form = new FormData();
  form.append("candidate_id", candidateId);
  form.append("document_type", $("#documentType").value);
  form.append("file", file);
  try {
    latestUpload = await request("/upload-document", { method: "POST", body: form });
    $("#uploadStatus").textContent = `${latestUpload.filename} · ${latestUpload.status}`;
    const fields = latestUpload.extracted_fields;
    const labels = [["name", "Name"], ["candidate_id", "Candidate ID"], ["degree", "Degree"], ["branch", "Branch"], ["institution", "Institution"], ["cgpa", "CGPA"], ["passing_year", "Passing year"]];
    $("#extractedFields").innerHTML = labels.map(([key, label]) => `<div><dt>${label}</dt><dd>${esc(fields[key] || "Not detected")}</dd></div>`).join("");
    $("#processingFindings").textContent = latestUpload.processing_findings.length ? latestUpload.processing_findings.join(" ") : `SHA-256: ${latestUpload.sha256}. Text extraction completed where available.`;
    toast("Document uploaded. Review the extracted fields before verification.", "success");
    await loadDocuments(candidateId);
  } catch (error) {
    toast(error.message, "error");
  }
});

async function loadDocuments(candidateId = $("#uploadCandidate").value) {
  if (!candidateId) {
    $("#documentsBody").innerHTML = '<tr><td colspan="5" class="empty-cell">Select a candidate to view documents.</td></tr>';
    return;
  }
  try {
    const rows = await request(`/documents/${encodeURIComponent(candidateId)}`);
    $("#documentsBody").innerHTML = rows.length ? rows.map(doc => `<tr><td><strong>${esc(doc.filename)}</strong><br><span class="muted mono">${esc(short(doc.sha256))}</span></td><td>${esc(doc.document_type)}</td><td>${dateText(doc.upload_date)}</td><td>${badge(doc.status)}</td><td><button class="button button-green" data-verify="${doc.id}" data-candidate-id="${esc(candidateId)}">Run checks</button></td></tr>`).join("") : '<tr><td colspan="5" class="empty-cell">No documents uploaded for this candidate.</td></tr>';
    $$('button[data-verify]', $("#documentsBody")).forEach(button => button.addEventListener("click", () => verifyDocument(button.dataset.candidateId, Number(button.dataset.verify), button)));
  } catch (error) {
    toast(error.message, "error");
  }
}

async function verifyDocument(candidateId, documentId, button) {
  button.disabled = true;
  const payload = {
    candidate_id: candidateId,
    document_id: documentId,
    required_cgpa: Number($("#ruleCgpa").value || 7.5),
    required_branch: $("#ruleBranch").value.trim(),
    required_degree: $("#ruleDegree").value.trim(),
    required_year: Number($("#ruleYear").value || 2024),
  };
  try {
    latestResult = await request("/verify", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    renderResult(latestResult);
    navigate("results");
    await loadDashboard();
    await loadCandidates();
    toast(`Verification finished: ${latestResult.final_status}.`, latestResult.final_status === "VERIFIED" ? "success" : "");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

function renderResult(result) {
  const checks = [
    ["OCR extraction", result.ocr.text_available ? "PASS" : "REVIEW", Object.entries(result.ocr.fields).map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`).join(" · ")],
    ["Identity matching", result.identity.status, `${result.identity.comparisons.map(item => `${item.field}: ${item.status}`).join(" · ")}. ${result.identity.limitation}`],
    ["Document authenticity", result.authenticity.status, `${result.authenticity.findings.join(" ")} ${result.authenticity.limitation}`],
    ["QR verification", result.qr.status, result.qr.detected ? result.qr.decoded_value : result.qr.decoded_value],
    ["Blockchain identity", result.blockchain.status, result.blockchain.message],
    ["Eligibility", result.eligibility.status, result.eligibility.checks.map(check => `${check.passed ? "PASS" : "FAIL"} ${check.rule} (actual: ${check.actual})`).join(" · ")],
  ];
  const html = `<div class="form-heading"><div><p class="eyebrow">${esc(result.candidate.candidate_id)} · ${esc(dateText(result.verification_date))}</p><h3>${esc(result.candidate.name)} · ${esc(result.document.filename)}</h3></div>${badge(result.final_status)}</div><div class="result-grid">${checks.map(([name, state, detail]) => `<article class="result-check"><strong>${esc(name)} ${badge(state)}</strong><span>${esc(detail || "No additional details.")}</span></article>`).join("")}</div><p class="notice">A PASS indicates that this prototype's configured checks passed. It does not prove real-world identity or guarantee that a document is genuine.</p>`;
  $("#verificationResult").innerHTML = html;
}

async function loadHistory() {
  try {
    const candidateId = $("#historyCandidate").value;
    const rows = await request(`/verification-history${candidateId ? `?candidate_id=${encodeURIComponent(candidateId)}` : ""}`);
    const body = $("#historyBody");
    body.innerHTML = rows.length ? rows.map(row => `<tr><td><strong>${esc(row.name)}</strong><br><span class="muted">${esc(row.candidate_id)}</span></td><td>${esc(row.filename)}</td><td>${dateText(row.verification_date)}</td><td>${badge(row.identity_status)}</td><td>${badge(row.authenticity_status)}</td><td>${badge(row.qr_status)}</td><td>${badge(row.blockchain_status)}</td><td>${badge(row.eligibility_status)}</td><td><button class="text-button" data-history-result="${row.id}">${esc(row.final_status)} →</button></td></tr>`).join("") : '<tr><td colspan="9" class="empty-cell">No verification attempts recorded.</td></tr>';
    $$('button[data-history-result]', body).forEach(button => button.addEventListener("click", () => showHistoryResult(Number(button.dataset.historyResult))));
  } catch (error) {
    toast(error.message, "error");
  }
}

async function showHistoryResult(id) {
  try {
    const rows = await request("/verification-history");
    const row = rows.find(item => item.id === id);
    if (!row) throw new Error("Verification history entry was not found.");
    latestResult = row.results;
    renderResult(latestResult);
    navigate("results");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function openCandidate(candidateId) {
  try {
    const candidate = await request(`/candidates/${encodeURIComponent(candidateId)}`);
    const profile = [["Full name", candidate.name], ["Candidate ID", candidate.candidate_id], ["Email", candidate.email], ["Institution", candidate.institution], ["Course", candidate.course], ["Branch", candidate.branch], ["Passing year", candidate.passing_year], ["CGPA", Number(candidate.cgpa).toFixed(2)], ["Wallet", candidate.wallet_address], ["Registration", candidate.registration_status], ["Blockchain transaction", candidate.blockchain_tx || "Not registered on-chain"]];
    const docs = candidate.documents.length ? candidate.documents.map(doc => `<tr><td>${esc(doc.filename)}</td><td>${esc(doc.document_type)}</td><td>${dateText(doc.upload_date)}</td><td>${badge(doc.status)}</td></tr>`).join("") : '<tr><td colspan="4" class="empty-cell">No documents yet.</td></tr>';
    $("#candidateDetails").innerHTML = `<div class="form-heading"><strong>${esc(candidate.name)}</strong>${badge(candidate.final_status || "PENDING")}</div><div class="profile-grid">${profile.map(([label, value]) => `<div class="profile-item"><small>${esc(label)}</small><strong>${esc(value)}</strong></div>`).join("")}</div><div class="section-heading"><div><p class="eyebrow">DOCUMENTS</p><h3>Candidate uploads</h3></div><button class="button button-green" id="detailUpload">Upload a document</button></div><div class="table-wrap"><table><thead><tr><th>File</th><th>Type</th><th>Date</th><th>Status</th></tr></thead><tbody>${docs}</tbody></table></div>`;
    $("#detailUpload").addEventListener("click", () => { $("#uploadCandidate").value = candidateId; loadDocuments(candidateId); navigate("documents"); });
    navigate("details");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function searchCandidates() {
  const query = new URLSearchParams();
  if ($("#candidateSearch").value.trim()) query.set("search", $("#candidateSearch").value.trim());
  if ($("#candidateStatus").value) query.set("status", $("#candidateStatus").value);
  if ($("#eligibilityFilter").value) query.set("eligibility", $("#eligibilityFilter").value);
  try {
    const rows = await request(`/candidates?${query}`);
    renderCandidates(rows);
  } catch (error) {
    toast(error.message, "error");
  }
}

$$(".nav-link").forEach(link => link.addEventListener("click", event => {
  event.preventDefault();
  navigate(link.dataset.page);
}));
$$("[data-go]").forEach(button => button.addEventListener("click", () => navigate(button.dataset.go)));
$("#uploadCandidate").addEventListener("change", event => loadDocuments(event.target.value));
$("#refreshDocuments").addEventListener("click", () => loadDocuments());
$("#refreshHistory").addEventListener("click", loadHistory);
$("#historyCandidate").addEventListener("change", loadHistory);
$("#searchCandidates").addEventListener("click", searchCandidates);
$("#candidateSearch").addEventListener("keydown", event => { if (event.key === "Enter") searchCandidates(); });
$("#quickSearch").addEventListener("keydown", event => {
  if (event.key !== "Enter") return;
  $("#candidateSearch").value = event.currentTarget.value;
  navigate("recruiter");
  searchCandidates();
});

document.addEventListener("DOMContentLoaded", async () => {
  $("#footerYear").textContent = new Date().getFullYear();
  await loadDashboard();
  populateCandidateSelects();
  const page = location.hash.slice(1);
  navigate(pageTitles[page] ? page : "dashboard");
  loadHistory();
  setInterval(loadBlockchain, 30000);
});