# Deploying Swift Alliance to Streamlit Cloud (streamlit.app)

This README contains step-by-step, copy-paste instructions to deploy the Swift Alliance Streamlit app to Streamlit Cloud, plus the exact secrets payloads to paste into the Streamlit Cloud Secrets UI. Follow the steps carefully to make the app work on streamlit.app.

---

## Before you begin — repo checklist

Ensure your Git repository has the following structure at the repository root (exact names matter):

- swift_alliance_streamlit.py          ← Streamlit entry (updated to use st.secrets)
- run_streamlit_wrapper.py            ← Optional wrapper (recommended)
- swift_alliance/                     ← package directory (must be tracked)
  - __init__.py
  - bank.py
  - messages.py
  - validator.py
  - config_manager.py
- assets/
  - swift_logo.svg (or swift_logo.png)   ← *Replace with official logo only if you have rights*
  - schemas/
    - pain.001.minimal.xsd (or your official pain.001.xsd)
- requirements.txt
- .streamlit/
  - config.toml
- tests/
  - test_pain001_validation.py
- .github/workflows/ci.yml (optional)

Important notes:
- Commit the XSD (assets/schemas/your-pain001.xsd) you will validate against — Streamlit Cloud filesystem is ephemeral and will only have what you committed.
- Do NOT commit secrets or private credentials. Use Streamlit Cloud Secrets for credentials.

---

## Minimal required files to commit

If you want the absolute minimum to deploy and validate:
- swift_alliance_streamlit.py
- run_streamlit_wrapper.py (recommended)
- swift_alliance/ (package and submodules)
- assets/schemas/pain.001.minimal.xsd
- requirements.txt
- .streamlit/config.toml

---

## Push to GitHub (quick commands)

From your project root:

```bash
git add .
git commit -m "Prepare Streamlit deployment"
git push origin main
```

Replace `main` with your branch name if different.

---

## Streamlit Cloud — create the app

1. Open https://share.streamlit.io/ and sign in.
2. Click "New app".
3. Select your GitHub repo, the branch, and set the main file path to:
   - `run_streamlit_wrapper.py` (recommended)  
   or
   - `swift_alliance_streamlit.py`
4. Click "Deploy".

Why `run_streamlit_wrapper.py`?  
It ensures the repository root is on Python's import path (sys.path) and prints diagnostics to the server logs. This avoids ModuleNotFoundError issues on some deployment environments.

---

## Add secrets in Streamlit Cloud (do NOT commit these)

Go to your deployed app → "Settings" → "Secrets" and paste the secrets blocks shown below. Replace example values with your real credentials.

- SMTP secrets (for sending email):
```toml
[SMTP]
host = "smtp.example.com:587"
user = "notify@example.com"
pass = "YOUR_SMTP_PASSWORD"
```

- SFTP secrets (for secure file upload, optional):
```toml
[SFTP]
host = "sftp.example.com"
port = "22"
user = "sftpuser"
pass = "YOUR_SFTP_PASSWORD"
```

Notes:
- Use `host:port` format for SMTP `host`.
- Values are available in the app as `st.secrets["SMTP"]["host"]`, etc.

---

## Recommended `.streamlit/config.toml`

Place this file at `.streamlit/config.toml` in the repo:

```toml
[server]
headless = true
enableCORS = false
port = 8501

[theme]
primaryColor = "#0D47A1"
backgroundColor = "#FFFFFF"
```

This is optional but recommended for Cloud deployments.

---

## Recommended `requirements.txt` (cloud-focused)

Streamlit Cloud installations are faster when unnecessary desktop packages are removed. Use a cloud-focused requirements set:

```
streamlit>=1.18
xmlschema>=2.0.0
lxml>=4.9
paramiko>=2.11   # only if you will SFTP from Cloud
pytest>=7.0
```

If you also want the desktop PyQt GUI locally, install PyQt5 in your local environment separately — do not include it in Cloud requirements unless needed.

---

## After deploy — first checks

1. Open the app URL provided by Streamlit Cloud.
2. If the app fails to start, open the app logs:
   - In Streamlit Cloud UI click the app → "Manage app" → "Logs".
   - If you used `run_streamlit_wrapper.py`, look for printed diagnostics:
     - "Base dir added to sys.path: …"
     - Directory listing (files printed)
     - Import tracebacks (full stack trace)
3. Check that `swift_alliance/` exists in the logged directory listing and the Python import path includes the repo root.

---

## How the app finds your schema & logo

- Prefer committing the schema to `assets/schemas/` (so validation works automatically).
- The UI can also accept uploads and store them under `assets/` persistently (persisted to repo folder at runtime). Note: Streamlit Cloud storage is ephemeral across redeploys — commit permanent files to the repo if you need them always present.

---

## Sending via SMTP / SFTP (secrets-aware)

- If SMTP/SFTP secrets are configured in Streamlit Cloud, the app will show "Send using secrets" buttons to send without entering credentials in the UI.
- If not configured, the app will let you enter credentials interactively, but do not commit them.

---

## Troubleshooting common issues

- ModuleNotFoundError: swift_alliance
  - Ensure `swift_alliance/` is committed with `__init__.py`.
  - Use `run_streamlit_wrapper.py` as the main file in Streamlit Cloud.
  - Check case-sensitive filenames (Linux).

- Validation errors (XML fails XSD):
  - Confirm the XSD file you used matches the pain.001 version your partner expects.
  - Use the minimal XSD for CI; replace with the official XSD (commit it) for production.

- SMTP / SFTP send fails:
  - Verify secrets in Streamlit Cloud are correct.
  - Check logs for exceptions (authentication, network, port).
  - For SFTP ensure `paramiko` is present in requirements if you plan to use it on Cloud.

---

## Quick local test before deploying

Run locally to validate imports and behavior:

```bash
# create virtual environment (optional)
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt

# Run the app with wrapper (recommended)
streamlit run run_streamlit_wrapper.py
```

If you see the Streamlit UI and no ModuleNotFoundError, deployment should work similarly.

---

## Legal / trademark note about the SWIFT logo

Do NOT commit or use the official SWIFT logo unless you have explicit rights to use it. The app expects a file named `assets/swift_logo.png` or `assets/swift_logo.svg`. I included a placeholder in the repo examples — replace it only when you have legal permission.

---

If you want, I can now:
- Produce a ready-to-paste README root-level file (I can output `README.md`) containing these instructions.
- Produce a sample `.streamlit/` folder or a Git patch that adds/updates the files in your repo.

Which of those would you like next?