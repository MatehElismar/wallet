# Wallet Email-to-Record Automation System

Automatically read incoming emails (bank alerts, receipts, invoices, payment confirmations) and write structured financial records into **Wallet** by BudgetBakers via their REST API, powered by Claude/GPT/Gemini/Ollama LLM for intelligent categorization.

**No vendor lock-in.** Works with any email provider (Gmail, Outlook, Yahoo, ProtonMail, etc.) and any LLM (OpenAI, Anthropic, Google Gemini, Ollama).

## 🏗️ Architecture

```
Email Clients (Gmail API, IMAP) ← Any provider
  ↓
Email Parser (HTML → Text extraction)
  ↓
LLM Orchestrator (Claude, GPT-4, Gemini, Llama) → Extract transaction details
  ↓
Validator (Field validation, account/category resolution)
  ↓
Wallet API Client (REST API) → POST /records
  ↓
State Store (SQLite) → Track processed emails, cache IDs
  ↓
Dead Letter Queue (JSONL) → Log failed items for manual review
```

## 🚀 Quick Start

### 1. Prerequisites

- **Python 3.11+** with conda
- **Wallet API Token** (Premium plan) — [get here](https://web.budgetbakers.com/settings/apiTokens) (for Phase 3+)
- **One LLM provider** (choose one):
  - **OpenAI** (GPT-4o) — [get API key](https://platform.openai.com/api-keys)
  - **Anthropic** (Claude) — [get API key](https://console.anthropic.com/api-keys)
  - **Google Gemini** — [get API key](https://aistudio.google.com/apikey) (free tier available)
  - **Ollama** (local, free) — [install](https://ollama.ai)

### 2. Setup (5 minutes)

```bash
# Clone/navigate to project
cd /Users/mateh/projects/wallet

# Create conda environment
conda create -n wallet python=3.11
conda activate wallet
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your LLM API key (optional for Phase 1)
```

### 3. Run Phase 1 (No API Keys Needed)

```bash
python main.py --phase 1
```

Output:
```
✓ Fetched 2 mock emails
✓ Processed through LLM (mock responses)
✓ Validated records
✓ Would post 2 records to Wallet API
```

---

## 📖 Documentation Guide

### For Different Use Cases

| I want to... | Read this |
|---|---|
| **Pick an LLM (GPT, Claude, Gemini, Ollama)** | [PROVIDERS.md](PROVIDERS.md) |
| **Use Gmail API (OAuth)** | [GMAIL_SETUP.md](GMAIL_SETUP.md) |
| **Use any email provider (IMAP)** | [EMAIL_PROVIDERS.md](EMAIL_PROVIDERS.md) |
| **Monitor multiple emails** | [MULTI_ACCOUNT.md](MULTI_ACCOUNT.md) |
| **Full API reference** | [Wallet API docs](https://rest.budgetbakers.com/wallet/reference) |

---

## 🧠 Choose Your LLM Provider

### OpenAI (Recommended for Cost/Speed)

```bash
export LLM_PROVIDER=openai
export OPENAI_API_KEY=sk-...
python main.py --phase 2
```

**Cost:** ~$0.50/month for 100 emails  
**Speed:** Fast (1-2s per email)  
**Quality:** Excellent

[Full setup → PROVIDERS.md](PROVIDERS.md)

### Anthropic (Best Accuracy)

```bash
export LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
python main.py --phase 2
```

**Cost:** ~$0.75/month for 100 emails  
**Speed:** Medium (2-5s per email)  
**Quality:** Excellent (best accuracy)

[Full setup → PROVIDERS.md](PROVIDERS.md)

### Google Gemini (Fast + Free Tier)

```bash
export LLM_PROVIDER=gemini
export GEMINI_API_KEY=AIzaSy...
python main.py --phase 2
```

**Cost:** Free tier (1.5M tokens/day) or pay-as-you-go  
**Speed:** Very fast (1s per email)  
**Quality:** Good

[Full setup → PROVIDERS.md](PROVIDERS.md)

### Ollama (Local, Private, Free)

```bash
# First: ollama pull mistral
export LLM_PROVIDER=ollama
export OLLAMA_BASE_URL=http://localhost:11434
export OLLAMA_MODEL=mistral
python main.py --phase 2
```

**Cost:** Free (electricity only)  
**Speed:** Slow on CPU, fast on GPU  
**Quality:** Good-excellent (depends on model)  
**Privacy:** Complete (no API calls)

[Full setup → PROVIDERS.md](PROVIDERS.md)

---

## 📧 Choose Your Email Provider

### IMAP (Works with ANY Provider)

**Supports:** Gmail, Outlook, Yahoo, ProtonMail, Apple iCloud, Zoho, corporate email, self-hosted

```bash
export EMAIL_PROVIDER=imap
export IMAP_HOST=imap.gmail.com        # (or any provider)
export IMAP_EMAIL=your_email@gmail.com
export IMAP_PASSWORD=your_app_password
python main.py --phase 2
```

[Provider-specific setup → EMAIL_PROVIDERS.md](EMAIL_PROVIDERS.md)

### Gmail API (Gmail only, OAuth)

**Faster and more structured than IMAP**

```bash
export EMAIL_PROVIDER=gmail
# Follow GMAIL_SETUP.md for OAuth setup
python main.py --phase 2
```

[Step-by-step guide → GMAIL_SETUP.md](GMAIL_SETUP.md)

### Multiple Email Accounts

Monitor personal + work emails, or multiple providers, simultaneously:

```bash
# Configure email_accounts.json
python main.py --phase 2 --multi-account

# View configured accounts
python main.py --show-accounts
```

[Complete setup → MULTI_ACCOUNT.md](MULTI_ACCOUNT.md)

---

## 🔄 Implementation Phases

### **Phase 1 — Local Skeleton** ✅
- No API keys needed
- Mock emails, mock LLM responses
- Validates all logic offline
- **Test:** `python main.py --phase 1`

### **Phase 2 — LLM Calibration** (Next)
- Pick an LLM provider (OpenAI, Anthropic, Gemini, Ollama)
- Set LLM API key
- Run against real LLM
- Tune categorization rules
- **Test:** `python main.py --phase 2`

### **Phase 3 — Wallet API Integration**
- Get Wallet Premium + API token
- Bootstrap: fetch real accounts/categories
- Post actual records to Wallet
- **Test:** `python main.py --phase 3`

### **Phase 4 — Production Hardening**
- Set up cron/scheduler
- Alerting for dead-letter queue
- Monitor 20K record limit
- **Run:** `python main.py --phase 4` + cron

---

## 🎯 Key Features

### **Intelligent Categorization**
Claude/GPT/Gemini automatically learns from email content:
- **Merchants** → "Food & Drinks", "Transport", "Shopping"
- **Amounts** → extracts currency and sign
- **Dates** → parses email timestamps
- **Accounts** → matches configured accounts
- **Custom rules** → easily tunable per LLM

### **Error Handling**

| Error | Action |
|-------|--------|
| LLM timeout | Retry 2x, then dead-letter |
| Rate limit (429) | Backoff, respect Retry-After |
| Server error (5xx) | Exponential backoff, 3 retries |
| Client error (4xx) | Log for manual review |
| Network timeout | Retry 2x, then dead-letter |

### **Deduplication**
Email UIDs stored in SQLite → prevents duplicate submissions on pipeline re-runs

### **State Tracking**
```
pending → llm_processing → api_pending → api_success
            ↓                     ↓
         llm_error      validation_error / api_client_error / api_server_error
```

### **Dead Letter Queue**
Failed emails logged as JSONL for manual review + pattern analysis

### **No Vendor Lock-In**
- **Email:** IMAP works with any provider, easy to switch
- **LLM:** Change provider via env var, no code changes
- **Wallet:** Standard REST API, can integrate with other systems

---

## 📋 Configuration

### .env File (Minimal Setup)

Copy and edit:
```bash
cp .env.example .env
```

**Only needs:**
```bash
# LLM (pick one)
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...

# Wallet (Phase 3+)
WALLET_API_TOKEN=your_token_here
```

Email is configured in `email_accounts.json` (see below), not in `.env`.

**Note:** Individual IMAP env vars (IMAP_HOST, IMAP_EMAIL, etc.) are optional and mainly for backwards compatibility. Use `email_accounts.json` instead.

### email_accounts.json (Multi-Account)

Copy from example and customize:
```bash
cp email_accounts.example.json email_accounts.json
# Edit email_accounts.json with your accounts
```

Example structure:
```json
{
  "accounts": [
    {
      "name": "Personal Gmail",
      "provider": "imap",
      "enabled": true,
      "host": "imap.gmail.com",
      "port": 993,
      "email": "personal@gmail.com",
      "password": "app_password",
      "category_prefix": "Personal"
    },
    {
      "name": "Work Outlook",
      "provider": "imap",
      "enabled": true,
      "host": "imap-mail.outlook.com",
      "port": 993,
      "email": "work@company.com",
      "password": "work_password",
      "category_prefix": "Work"
    }
  ]
}
```

**Note:** `email_accounts.json` is git-ignored (not committed). Use `email_accounts.example.json` as reference.

[Full documentation → MULTI_ACCOUNT.md](MULTI_ACCOUNT.md)

---

## 🎮 Commands

### Single-Account Mode (Default)

```bash
# Phase 1: Offline testing (no API keys)
python main.py --phase 1

# Phase 2: With LLM API key
python main.py --phase 2

# Phase 3: With Wallet API token
python main.py --phase 3

# Bootstrap only (fetch accounts/categories)
python main.py --phase 1 --bootstrap
```

### Multi-Account Mode

```bash
# Run with multiple email accounts
python main.py --phase 2 --multi-account

# View configured accounts
python main.py --show-accounts

# Show accounts as JSON
python main.py --show-accounts | jq
```

---

## 📊 Project Structure

```
wallet/
├── main.py                    # Entry point; orchestrates pipeline
├── config.py                  # Loads env vars; phase validation
├── email_client.py            # Gmail API & IMAP email fetchers
├── email_parser.py            # HTML→text; metadata extraction
├── llm_client.py              # Claude/GPT/Gemini/Ollama wrapper (multi-provider)
├── multi_account.py           # Multi-account orchestration
├── validator.py               # Post-LLM field validation
├── wallet_client.py           # Wallet REST API client
├── state_store.py             # SQLite tracking (emails, caches)
├── dead_letter.py             # JSONL for failed records
├── email_accounts.json        # Multi-account config (example)
├── .env.example               # Environment variable template
├── requirements.txt           # Python dependencies
├── README.md                  # This file
├── PROVIDERS.md               # LLM provider setup guide
├── GMAIL_SETUP.md             # Gmail API OAuth setup
├── EMAIL_PROVIDERS.md         # Email provider guide (IMAP, etc)
├── MULTI_ACCOUNT.md           # Multi-account setup guide
├── tests/
│   ├── test_email_parser.py
│   ├── test_validator.py
│   └── test_wallet_client.py
└── logs/
    └── wallet.log             # Operational logs
```

---

## 🧪 Testing

### Run All Tests

```bash
conda run -n wallet python -c "
import sys; sys.path.insert(0, '.')

# Email parser tests
from email_parser import EmailParser, EmailMetadata
from datetime import datetime
parser = EmailParser()
html = '<html><body><p>Hello <b>World</b></p></body></html>'
text = parser.extract_text_from_html(html)
assert 'Hello' in text and 'World' in text
print('✓ Email parser tests passed')

# Validator tests
from validator import RecordValidator
from datetime import timedelta
account_map = {'Checking': '123e4567'}
category_map = {'Food & Drinks': '456e7890'}
validator = RecordValidator(account_map, category_map)
record = {
    'amount': -45.99,
    'recordDate': (datetime.utcnow() - timedelta(hours=1)).isoformat() + 'Z',
    'paymentType': 'debit_card',
    'counterParty': 'Starbucks',
    'note': 'Coffee',
    'accountName': 'Checking',
    'categoryName': 'Food & Drinks',
    'skipReason': None,
}
is_valid, error = validator.validate_record(record)
assert is_valid, error
print('✓ Validator tests passed')
"
```

### Manual Testing

```bash
# Test Phase 1 (offline)
python main.py --phase 1

# Test with your LLM provider
python main.py --phase 2

# Test multi-account
python main.py --show-accounts
python main.py --phase 2 --multi-account
```

---

## 🔐 Security

### Best Practices

- **API tokens:** Store in `.env` (never in code)
- **Email passwords:** Use app-specific passwords, not regular passwords
- **Credentials:** Both files in `.gitignore` (auto-excluded from git)
- **Token security:** Auto-refreshed, stored securely
- **Email PII:** Masked in INFO logs, full detail in DEBUG logs only
- **LLM injection:** Email content wrapped in clear delimiters

### Secrets Management

```bash
# Option 1: .env file (easiest for single machine)
echo "OPENAI_API_KEY=sk-..." >> .env

# Option 2: Environment variables (production)
export OPENAI_API_KEY=sk-...
python main.py --phase 2

# Option 3: Secrets manager (large deployments)
# Use AWS Secrets Manager, HashiCorp Vault, etc
```

---

## 📈 API Constraints Handled

| Constraint | Implementation |
|-----------|---|
| 300 req/hr rate limit | Cache accounts/categories; refresh every 30 min |
| 20 records per batch | Group emails; post in multiple calls if needed |
| Max 20,000 records per user | Track count; alert at 18,000 |
| Bank-synced accounts read-only | LLM targets manual accounts only |
| Partial success (207) | Iterate per-record; log each result |
| Max field lengths (255 chars) | Truncate note/counterParty before posting |
| recordDate constraints | Reject >24h future or >10 years past |
| OAuth token expiry | Auto-refresh when expired |

---

## 🤝 Contributing

### Adding a New LLM Provider

1. Create class in `llm_client.py` extending `LLMProvider`
2. Implement `extract()` method
3. Add to `create_llm_client()` factory
4. Add to `PROVIDERS.md`

### Adding a New Email Provider API

1. Create class in `email_client.py` extending `EmailClient`
2. Implement `fetch_new_emails()` and `mark_as_processed()`
3. Add to `create_email_client()` factory
4. Add to `EMAIL_PROVIDERS.md`

---

## 📞 Support & Troubleshooting

### Common Issues

**"LLM API key not configured"**
- Set `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, or `OLLAMA_BASE_URL`
- Check `.env` file has correct value

**"Email credentials invalid"**
- For IMAP: Check app-specific password (not regular password)
- For Gmail API: Follow GMAIL_SETUP.md for OAuth setup

**"Wallet API returns 409"**
- Initial sync in progress; wait 5 minutes and retry

**"Rate limited (429)"**
- Respect Retry-After header; system auto-backoffs

### Debug Mode

```bash
export LOG_LEVEL=DEBUG
python main.py --phase 2
```

### Check Configured Accounts

```bash
python main.py --show-accounts
```

### Check Pipeline Stats

Logs show:
- Emails fetched per account
- Records validated
- Records posted
- Dead letter queue items

---

## 📚 Learn More

- **[PROVIDERS.md](PROVIDERS.md)** — Compare LLM providers, pricing, setup
- **[GMAIL_SETUP.md](GMAIL_SETUP.md)** — Step-by-step Gmail OAuth
- **[EMAIL_PROVIDERS.md](EMAIL_PROVIDERS.md)** — IMAP setup for all providers
- **[MULTI_ACCOUNT.md](MULTI_ACCOUNT.md)** — Monitor multiple emails
- **[Wallet API](https://rest.budgetbakers.com/wallet/reference)** — Official API docs

---

## 📈 Roadmap

### Phase 4 Features (Upcoming)
- [ ] Scheduled runs (cron/systemd timer)
- [ ] Alerting (email/Slack for dead-letter queue)
- [ ] Web UI for manual review
- [ ] Batch API support (reduce costs)
- [ ] Transfer pair detection (skip transfers)
- [ ] Receipt image OCR (extract from attachments)

### Provider APIs (Planned)
- [ ] Outlook/Microsoft Graph
- [ ] Yahoo Mail API
- [ ] ProtonMail API

---

## 📄 License & Credits

**Implementation Date:** May 30, 2026  
**Current Phase:** 1 (Local Skeleton) ✅  
**Status:** Ready for Phase 2 (LLM Calibration)

Built with:
- Python 3.11+
- Anthropic Claude / OpenAI GPT / Google Gemini / Ollama LLMs
- IMAP & Gmail API for email
- Wallet REST API
- SQLite for state

---

## 🎯 Next Steps

**Pick an LLM provider:**
1. [PROVIDERS.md](PROVIDERS.md) — Compare options
2. Get API key (OpenAI, Anthropic, or Gemini) or install Ollama
3. Set `LLM_PROVIDER` and API key in `.env`

**Pick an email provider:**
1. [EMAIL_PROVIDERS.md](EMAIL_PROVIDERS.md) — IMAP setup for any provider
2. Or [GMAIL_SETUP.md](GMAIL_SETUP.md) — Gmail OAuth (optional)
3. Set `EMAIL_PROVIDER` and credentials in `.env`

**Run Phase 2:**
```bash
python main.py --phase 2
```

**Then Phase 3 when ready (with Wallet API token):**
```bash
python main.py --phase 3
```

**Questions?** Check the relevant docs above or review logs with `LOG_LEVEL=DEBUG`.

---

Last updated: 2026-05-30  
Author: Mateh Elismar  
Email: matematicoelismar@gmail.com
