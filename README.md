# Wallet Email-to-Record Automation System

An automated pipeline that reads incoming emails (bank alerts, receipts, invoices, payment confirmations) and writes structured financial records into **Wallet** by BudgetBakers via their REST API, powered by Claude LLM for intelligent categorization.

## Architecture

```
Email Client (IMAP/Gmail) 
  ↓
Email Parser (HTML → Text)
  ↓
LLM Orchestrator (Claude API) → Extracts: amount, date, category, account, etc.
  ↓
Validator (Field validation, account/category resolution)
  ↓
Wallet API Client (REST API) → POST /records
  ↓
State Store (SQLite) → Track processed emails, cache IDs
  ↓
Dead Letter Queue (JSONL) → Log failed items for manual review
```

## Quick Start

### Prerequisites

- **Python 3.11+** with conda
- **Wallet API Token** (requires Premium plan) — get from [web.budgetbakers.com/settings/apiTokens](https://web.budgetbakers.com/settings/apiTokens)
- **One of these LLM providers:**
  - **OpenAI** (GPT-4o, etc) — `OPENAI_API_KEY` from [platform.openai.com](https://platform.openai.com)
  - **Anthropic** (Claude) — `ANTHROPIC_API_KEY` from [console.anthropic.com](https://console.anthropic.com)
  - **Google Gemini** — `GEMINI_API_KEY` from [aistudio.google.com](https://aistudio.google.com)
  - **Ollama** (local) — self-hosted at `http://localhost:11434`
- **Email Setup** — IMAP works with ANY provider (Gmail, Outlook, Yahoo, ProtonMail, etc.)

### Setup

1. **Clone/navigate to the project**
   ```bash
   cd /Users/mateh/projects/wallet
   ```

2. **Create conda environment**
   ```bash
   conda create -n wallet python=3.11
   conda activate wallet
   pip install -r requirements.txt
   ```

3. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials:
   ```

   **Choose your LLM provider:**

   **Option A: OpenAI (Default)**
   ```bash
   LLM_PROVIDER=openai
   OPENAI_API_KEY=sk-...
   ```

   **Option B: Anthropic (Claude)**
   ```bash
   LLM_PROVIDER=anthropic
   ANTHROPIC_API_KEY=sk-ant-...
   ```

   **Option C: Google Gemini**
   ```bash
   LLM_PROVIDER=gemini
   GEMINI_API_KEY=AIzaSy...
   ```

   **Option D: Ollama (Local, Self-Hosted)**
   ```bash
   LLM_PROVIDER=ollama
   OLLAMA_BASE_URL=http://localhost:11434
   OLLAMA_MODEL=llama2  # or mistral, neural-chat, etc
   ```

   **Always set (for Phase 3+):**
   ```bash
   WALLET_API_TOKEN=your_token_here
   EMAIL_PROVIDER=imap or gmail
   ```

4. **Run Phase 1 (Local Testing)**
   ```bash
   python main.py --phase 1
   ```

## Implementation Phases

### **Phase 1 — Local Skeleton** ✅ Complete
- [x] Project structure with virtual environment
- [x] Email fetcher (IMAP support, mock for Gmail)
- [x] HTML-to-text parser
- [x] LLM prompt template with mock responses
- [x] Mock Wallet API client (logs without posting)
- [x] SQLite state store for tracking
- [x] Main orchestrator
- [x] Unit tests for email parser and validator

**Status:** Pipeline runs end-to-end; mock records logged to console.

**Test it:**
```bash
python main.py --phase 1
```

---

### **Phase 2 — LLM Calibration** (Next)
**What's needed:**
- [ ] Pick an LLM provider and set its API key
- [ ] Run 20-30 real emails through the LLM
- [ ] Tune prompt heuristics based on misclassifications
- [ ] Validate all 8 post-LLM validation steps

**Commands (pick one):**

**OpenAI:**
```bash
export LLM_PROVIDER=openai
export OPENAI_API_KEY=sk-...
python main.py --phase 2
```

**Anthropic:**
```bash
export LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
python main.py --phase 2
```

**Gemini:**
```bash
export LLM_PROVIDER=gemini
export GEMINI_API_KEY=AIzaSy...
python main.py --phase 2
```

**Ollama (local):**
```bash
export LLM_PROVIDER=ollama
export OLLAMA_BASE_URL=http://localhost:11434
export OLLAMA_MODEL=llama2
python main.py --phase 2
```

---

### **Phase 3 — Wallet API Integration**
**What's needed:**
- [ ] Obtain Wallet API token (Premium plan)
- [ ] Bootstrap: GET /accounts and GET /categories
- [ ] Update LLM system prompt with real account/category names
- [ ] Run dry-run mode (validate without posting)
- [ ] Post small batch (3-5 records) and verify in Wallet app
- [ ] Implement 207 partial-success handling and retry logic

**Commands:**
```bash
export WALLET_API_TOKEN=your_token_here
python main.py --phase 3
```

---

### **Phase 4 — Production Hardening**
**What's needed:**
- [ ] Set up cron job or systemd timer
- [ ] Implement alerting for dead-letter queue
- [ ] Add X-Last-Data-Change-Rev monitoring
- [ ] Monitor record count approaching 20,000 limit
- [ ] Document account/category mapping

---

## File Structure

```
wallet/
├── main.py                  # Entry point; orchestrates pipeline
├── config.py                # Loads env vars; phase validation
├── email_client.py          # IMAP/Gmail email fetcher
├── email_parser.py          # HTML→text; metadata extraction
├── llm_client.py            # Claude API wrapper
├── validator.py             # Post-LLM field validation
├── wallet_client.py         # Wallet REST API client
├── state_store.py           # SQLite tracking (emails, ID cache)
├── dead_letter.py           # JSONL for failed records
├── .env.example             # Environment variable template
├── requirements.txt         # Python dependencies
├── tests/
│   ├── test_email_parser.py
│   ├── test_validator.py
│   └── test_wallet_client.py
└── README.md                # This file
```

## Email Provider Configuration

**No vendor lock-in.** IMAP works with ANY email provider.

### Quick Setup (IMAP)

IMAP is the universal standard — works with Gmail, Outlook, Yahoo, ProtonMail, Apple iCloud, Zoho, corporate email, self-hosted, etc.

```bash
# Pick your provider
export EMAIL_PROVIDER=imap
export IMAP_HOST=imap.gmail.com        # (or imap-mail.outlook.com, imap.mail.yahoo.com, etc)
export IMAP_EMAIL=your_email@gmail.com
export IMAP_PASSWORD=your_app_password # (app-specific password, not your regular password)
```

**Supported IMAP providers:**
- Gmail: `imap.gmail.com`
- Outlook: `imap-mail.outlook.com`
- Yahoo: `imap.mail.yahoo.com`
- ProtonMail: `imap.protonmail.com`
- Apple iCloud: `imap.mail.me.com`
- Zoho: `imap.zoho.com`
- Any corporate/self-hosted email

See **[EMAIL_PROVIDERS.md](EMAIL_PROVIDERS.md)** for detailed setup by provider.

### Gmail API (Optional, Optimized)

For Gmail users who want faster API access with OAuth:

```bash
export EMAIL_PROVIDER=gmail
# Follow GMAIL_SETUP.md for OAuth setup
```

**Note:** Gmail API is faster but requires Google Cloud setup. IMAP works fine and is simpler.

---

## LLM Provider Configuration

### OpenAI (Default)
Best balance of cost and quality. Supports GPT-4o, GPT-4 Turbo, etc.

```bash
export LLM_PROVIDER=openai
export OPENAI_API_KEY=sk-...
export OPENAI_MODEL=gpt-4o  # optional; defaults to gpt-4o
```

Get API key: https://platform.openai.com/api-keys

### Anthropic (Claude)
Best accuracy. Supports Claude Sonnet, Opus, etc.

```bash
export LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
export ANTHROPIC_MODEL=claude-sonnet-4-20250514  # optional
```

Get API key: https://console.anthropic.com/api-keys

### Google Gemini
Fast and capable. Supports Gemini 2.0, etc.

```bash
export LLM_PROVIDER=gemini
export GEMINI_API_KEY=AIzaSy...
export GEMINI_MODEL=gemini-2.0-flash  # optional
```

Get API key: https://aistudio.google.com/apikey

### Ollama (Local, Self-Hosted)
Run models locally. No API keys needed. Best for privacy.

```bash
# First, install & run Ollama
# https://ollama.ai

# Pull a model
ollama pull llama2  # or mistral, neural-chat, etc

# Then configure
export LLM_PROVIDER=ollama
export OLLAMA_BASE_URL=http://localhost:11434
export OLLAMA_MODEL=llama2
```

Run Ollama: https://ollama.ai

---

## Key Features

### **Intelligent Categorization**
Claude LLM automatically categorizes transactions based on merchant/context:
- Starbucks, grocery stores → "Food & Drinks"
- Netflix, Spotify, SaaS → "Entertainment" / "Subscriptions"
- Uber, parking, fuel → "Transport"
- Doctor, pharmacy → "Health"
- And more...

### **Error Handling & Retry Logic**
- **LLM timeouts:** Retry 2x, then dead-letter
- **Wallet 429 (rate limit):** Respect Retry-After header
- **Wallet 5xx:** Exponential backoff (2s → 8s → 32s)
- **Wallet 4xx:** Log for manual review (no auto-retry)

### **Deduplication**
Email UIDs stored in SQLite prevent duplicate submissions on pipeline re-runs.

### **Dead Letter Queue**
Failed emails logged as JSONL for manual review:
```jsonl
{"timestamp": "2025-05-30T09:58:29.317Z", "email_id": "...", "reason": "Validation error: ..."}
```

### **State Tracking**
```
pending → llm_processing → api_pending → api_success
                              ↓
                        validation_error / llm_error / api_client_error
```

## API Constraints Handled

| Constraint | Implementation |
|------------|-----------------|
| 300 req/hr rate limit | Cache accounts/categories; refresh every 30 min |
| 20 records per batch | Group emails; post in multiple calls if needed |
| Max 20,000 records | Track count; alert at 18,000 |
| Bank-synced accounts read-only | LLM targets manual accounts only |
| Partial success (207) | Iterate per-record; log each result |
| Max field lengths (255 chars) | Truncate note and counterParty before posting |
| recordDate constraints | Reject >24h future or >10 years past |

## Testing

**Run all tests:**
```bash
conda run -n wallet python tests/test_email_parser.py
conda run -n wallet python tests/test_validator.py
```

**Or inline:**
```bash
conda run -n wallet python -c "from email_parser import EmailParser; ..."
```

## Next Steps

1. **Phase 2:** Set `ANTHROPIC_API_KEY` and calibrate LLM on real emails
2. **Phase 3:** Add `WALLET_API_TOKEN` and test against live Wallet API
3. **Phase 4:** Set up cron job for unattended runs

## Troubleshooting

**"Initial sync in progress (409)"**
- Wallet API returns 409 on first-time accounts. Wait 5 minutes before retrying.

**"Rate limited (429)"**
- Check Retry-After header in response. Wait that duration.

**No emails found**
- Check IMAP credentials in `.env`
- Verify you have unread emails in inbox
- In Phase 1, uses mock emails automatically

**LLM extraction fails**
- Ensure `ANTHROPIC_API_KEY` is set
- Check email text is valid (not truncated HTML)
- Review LLM output in dead letter queue

## API Reference

- **Wallet API docs:** https://rest.budgetbakers.com/wallet/reference
- **Claude API:** https://docs.anthropic.com/

## Security Notes

- **API tokens:** Stored in `.env` (never in code)
- **Email PII:** Masked in INFO logs; full detail in DEBUG logs only
- **LLM prompt injection:** Email content wrapped in clear delimiters
- **Duplicate records:** Checked before every POST

---

**Last updated:** 2026-05-30  
**Phase:** 1 (Local Skeleton) ✅  
**Next:** Phase 2 (LLM Calibration)
