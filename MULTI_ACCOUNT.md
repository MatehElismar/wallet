# Multi-Account Email Support

Monitor multiple email accounts simultaneously with one pipeline. Perfect for:
- **Personal + Work emails** — different accounts, same Wallet
- **Family emails** — monitor multiple family members' transactions
- **Multiple providers** — Gmail + Outlook + Yahoo in one system
- **Email aliases** — multiple addresses for same provider

---

## Quick Start

### 1. Configure Accounts

Copy the example and customize:
```bash
cp email_accounts.example.json email_accounts.json
# Edit email_accounts.json with your accounts
```

Edit your new `email_accounts.json`:

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
      "password": "personal_app_password",
      "category_prefix": "Personal"
    },
    {
      "name": "Work Email",
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

### 2. Enable Multi-Account Mode

```bash
python main.py --phase 2 --multi-account
```

### 3. View Configured Accounts

```bash
python main.py --show-accounts
```

Output:
```json
[
  {
    "name": "Personal Gmail",
    "provider": "imap",
    "enabled": true,
    "email": "personal@gmail.com",
    ...
  },
  ...
]
```

---

## Configuration File Format

### email_accounts.json Structure

```json
{
  "accounts": [
    {
      "name": "Account Display Name",
      "provider": "imap" or "gmail",
      "enabled": true or false,
      
      // For IMAP provider:
      "host": "imap.example.com",
      "port": 993,
      "email": "user@example.com",
      "password": "app_password_or_token",
      
      // For Gmail API provider:
      "credentials_file": "credentials.json",
      "token_file": "token.json",
      
      // Optional: Prefix categories with account name
      "category_prefix": "Work"  // Categories become "Work:Food & Drinks", etc
    }
  ]
}
```

### Field Descriptions

| Field | Required | Example | Notes |
|-------|----------|---------|-------|
| `name` | Yes | "Personal Gmail" | Display name for logs |
| `provider` | Yes | "imap" or "gmail" | Which provider type |
| `enabled` | Yes | true or false | Enable/disable without removing |
| `host` | For IMAP | "imap.gmail.com" | IMAP server address |
| `port` | For IMAP | 993 | IMAP port (usually 993) |
| `email` | For IMAP | "user@domain.com" | Email address |
| `password` | For IMAP | "app_password" | App-specific password |
| `credentials_file` | For Gmail API | "credentials.json" | OAuth credentials file |
| `token_file` | For Gmail API | "token.json" | OAuth token file |
| `category_prefix` | Optional | "Work" | Prefix for transaction categories |

---

## Examples

### Two Gmail Accounts (IMAP)

```json
{
  "accounts": [
    {
      "name": "Personal Gmail",
      "provider": "imap",
      "enabled": true,
      "host": "imap.gmail.com",
      "port": 993,
      "email": "alice@gmail.com",
      "password": "${PERSONAL_PASSWORD}",
      "category_prefix": "Personal"
    },
    {
      "name": "Secondary Gmail",
      "provider": "imap",
      "enabled": true,
      "host": "imap.gmail.com",
      "port": 993,
      "email": "alice.secondary@gmail.com",
      "password": "${SECONDARY_PASSWORD}",
      "category_prefix": "Secondary"
    }
  ]
}
```

### Mixed Providers

```json
{
  "accounts": [
    {
      "name": "Personal Gmail",
      "provider": "imap",
      "enabled": true,
      "host": "imap.gmail.com",
      "port": 993,
      "email": "alice@gmail.com",
      "password": "${GMAIL_PASSWORD}",
      "category_prefix": "Gmail"
    },
    {
      "name": "Work Outlook",
      "provider": "imap",
      "enabled": true,
      "host": "imap-mail.outlook.com",
      "port": 993,
      "email": "alice@company.com",
      "password": "${OUTLOOK_PASSWORD}",
      "category_prefix": "Work"
    },
    {
      "name": "Family ProtonMail",
      "provider": "imap",
      "enabled": false,
      "host": "imap.protonmail.com",
      "port": 993,
      "email": "family@protonmail.com",
      "password": "${PROTONMAIL_PASSWORD}",
      "category_prefix": "Family"
    }
  ]
}
```

### Gmail API (OAuth)

```json
{
  "accounts": [
    {
      "name": "Gmail API Account",
      "provider": "gmail",
      "enabled": true,
      "credentials_file": "credentials.json",
      "token_file": "token_gmail.json",
      "category_prefix": "Gmail"
    }
  ]
}
```

---

## Environment Variables in Passwords

You can use `${VAR_NAME}` syntax for sensitive credentials:

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
      "password": "${PERSONAL_GMAIL_PASSWORD}",
      "category_prefix": "Personal"
    }
  ]
}
```

Then set environment variables:
```bash
export PERSONAL_GMAIL_PASSWORD=your_app_password
export WORK_EMAIL_PASSWORD=your_work_password
python main.py --phase 2 --multi-account
```

This keeps secrets out of the config file.

---

## Running Multi-Account

### Single Run

```bash
python main.py --phase 2 --multi-account
```

This fetches emails from all **enabled** accounts and processes them together.

### With Cron (Multiple Times Per Day)

```bash
# Every 15 minutes
*/15 * * * * cd /Users/mateh/projects/wallet && /opt/miniconda3/envs/wallet/bin/python main.py --phase 2 --multi-account >> logs/wallet.log 2>&1
```

### With APScheduler

The system can run multi-account on a schedule (Phase 4).

---

## Workflow

When you run with `--multi-account`:

1. **Load Configuration** — read `email_accounts.json`
2. **Initialize Clients** — create email client for each enabled account
3. **Fetch Emails** — fetch new emails from all accounts in parallel
4. **Process Together** — send all emails to LLM, validate, batch to Wallet
5. **Track by Account** — logs show which account each email came from

Example output:
```
INFO - Personal Gmail: Fetched 5 emails
INFO - Work Email: Fetched 3 emails
INFO - Processing 8 emails from multiple accounts
INFO - [PHASE 2] Would post 7 records (1 skipped)
```

---

## Category Prefixes

Optional: Prefix transaction categories with account name.

Without prefix:
```
Coffee → "Food & Drinks"
Fuel → "Transport"
```

With prefix (`"category_prefix": "Work"`):
```
Coffee → "Work:Food & Drinks"
Fuel → "Work:Transport"
```

This helps you see at a glance which account a transaction came from in your Wallet.

---

## Enable/Disable Accounts

Change `"enabled"` in `email_accounts.json` — no code changes needed.

```json
{
  "name": "Vacation Account",
  "enabled": false,  // Disabled — won't be fetched
  ...
}
```

Then re-run with `--multi-account`.

---

## Switching Between Modes

### Single-Account Mode (Default)

```bash
# Uses EMAIL_PROVIDER from .env or environment
python main.py --phase 2
```

### Multi-Account Mode

```bash
# Uses email_accounts.json
python main.py --phase 2 --multi-account
```

Can switch anytime without code changes.

---

## Troubleshooting

### "Failed to initialize Personal Gmail: Invalid credentials"

- Check email address matches what you configured
- For IMAP: Check app-specific password (not regular password)
- For Gmail: Use app password from myaccount.google.com/apppasswords

### "No new emails from any account"

- All accounts may be up-to-date
- Check with `python main.py --show-accounts` that accounts are enabled
- Verify `.env` is set correctly (if using env vars)

### "Missing required field in account"

- `email_accounts.json` must have `name`, `provider`, `enabled`
- For IMAP: also needs `host`, `port`, `email`, `password`
- For Gmail API: needs `credentials_file`, `token_file`

### One account fails, others skip

- System continues if one account fails (graceful degradation)
- Check logs for which account errored
- Fix the account, re-run with `--multi-account`

---

## Security Notes

- **Don't commit `email_accounts.json` to git** — add to `.gitignore`
- **Use app-specific passwords**, not regular passwords
- **Use environment variables** for sensitive credentials (see example above)
- Credentials file (`.env`, `credentials.json`) should be mode 600
- Tokens (`token.json`) are auto-generated and sensitive

---

## Limits & Performance

- **Suggested max accounts:** 5-10 per pipeline
- **Email fetch:** Parallel (all accounts fetched concurrently)
- **Processing:** Sequential (emails processed one-by-one)
- **Rate limiting:** Respects Wallet API limits (300 req/hr)

For 10+ accounts, consider running multiple pipelines (one per group of accounts).

---

## Example: Family Shared Wallet

Monitor 3 family members' email accounts with one Wallet:

```json
{
  "accounts": [
    {
      "name": "Alice's Email",
      "provider": "imap",
      "enabled": true,
      "host": "imap.gmail.com",
      "port": 993,
      "email": "alice@gmail.com",
      "password": "${ALICE_PASSWORD}",
      "category_prefix": "Alice"
    },
    {
      "name": "Bob's Email",
      "provider": "imap",
      "enabled": true,
      "host": "imap.gmail.com",
      "port": 993,
      "email": "bob@gmail.com",
      "password": "${BOB_PASSWORD}",
      "category_prefix": "Bob"
    },
    {
      "name": "Carol's Email",
      "provider": "imap",
      "enabled": true,
      "host": "imap-mail.outlook.com",
      "port": 993,
      "email": "carol@outlook.com",
      "password": "${CAROL_PASSWORD}",
      "category_prefix": "Carol"
    }
  ]
}
```

Run once per day:
```bash
python main.py --phase 2 --multi-account
```

All transactions appear in the shared Wallet with account prefixes so you know who spent what.

---

## Next Steps

1. **Edit `email_accounts.json`** — add your accounts
2. **Test with `--show-accounts`** — verify configuration
3. **Run once** — `python main.py --phase 2 --multi-account`
4. **Review results** — check Wallet app
5. **Set up cron** — for unattended daily runs

See README.md for full setup guide.
