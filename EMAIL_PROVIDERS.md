# Email Provider Support — Vendor-Neutral Design

## Current Support

The system supports **any email provider** via IMAP, plus optimized APIs for specific providers.

### IMAP (Universal — Recommended)
Works with **every email provider** that supports IMAP:
- Gmail
- Outlook / Office 365
- Yahoo Mail
- ProtonMail
- Apple iCloud Mail
- Zoho Mail
- Any corporate email (Exchange, etc)
- Any self-hosted email

**Setup:** Just IMAP credentials (email + password/app-password)

### Provider-Specific APIs (Optimized)
- **Gmail API** — native, fast, structured metadata
- **Outlook/Microsoft Graph** — planned
- **Yahoo Mail API** — planned
- **ProtonMail API** — planned

---

## Configuration by Provider

### Gmail

**Option A: Gmail API (Fast, Structured)**
```bash
EMAIL_PROVIDER=gmail
# Follow GMAIL_SETUP.md for OAuth setup
```

**Option B: IMAP (Simple, Works Everywhere)**
```bash
EMAIL_PROVIDER=imap
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_EMAIL=your_email@gmail.com
IMAP_PASSWORD=your_app_password  # Generate at myaccount.google.com/apppasswords
```

### Outlook / Office 365

```bash
EMAIL_PROVIDER=imap
IMAP_HOST=imap-mail.outlook.com
IMAP_PORT=993
IMAP_EMAIL=your_email@outlook.com
IMAP_PASSWORD=your_password
```

### Yahoo Mail

```bash
EMAIL_PROVIDER=imap
IMAP_HOST=imap.mail.yahoo.com
IMAP_PORT=993
IMAP_EMAIL=your_email@yahoo.com
IMAP_PASSWORD=your_app_password  # Generate at myaccount.yahoo.com/account/security
```

### ProtonMail

```bash
EMAIL_PROVIDER=imap
IMAP_HOST=imap.protonmail.com
IMAP_PORT=993
IMAP_EMAIL=your_email@protonmail.com
IMAP_PASSWORD=your_email_password
```

### Apple iCloud Mail

```bash
EMAIL_PROVIDER=imap
IMAP_HOST=imap.mail.me.com
IMAP_PORT=993
IMAP_EMAIL=your_email@icloud.com
IMAP_PASSWORD=your_app_password  # Generate at appleid.apple.com/account/security
```

### Zoho Mail

```bash
EMAIL_PROVIDER=imap
IMAP_HOST=imap.zoho.com
IMAP_PORT=993
IMAP_EMAIL=your_email@zohomail.com
IMAP_PASSWORD=your_password
```

### Corporate Email (Exchange, etc)

```bash
EMAIL_PROVIDER=imap
IMAP_HOST=mail.company.com  # Ask your IT admin
IMAP_PORT=993
IMAP_EMAIL=your_email@company.com
IMAP_PASSWORD=your_password
```

### Self-Hosted Email (Synology, etc)

```bash
EMAIL_PROVIDER=imap
IMAP_HOST=your-domain.com  # Your mail server
IMAP_PORT=993
IMAP_EMAIL=your_email@your-domain.com
IMAP_PASSWORD=your_password
```

---

## IMAP Advantages

✅ **Works everywhere** — IMAP is the universal standard  
✅ **No vendor lock-in** — Switch providers without code changes  
✅ **Simple setup** — Just credentials, no OAuth/APIs  
✅ **Works offline** — Can sync while disconnected  
✅ **Portable** — Same setup works on any system  
✅ **Private** — No app registration needed  
✅ **Free** — No API rate limits or costs  

---

## API Advantages (When Available)

✅ Faster, more efficient  
✅ Structured metadata (read receipts, labels, etc)  
✅ Retry handling built-in  
✅ Better error messages  

But: Requires provider-specific setup, rate limits, cost.

---

## Recommended Approach

**Use IMAP for:**
- Quick setup (no OAuth)
- Switching between providers
- Privacy (no third-party apps)
- Cost control (no API charges)

**Use Provider APIs for:**
- Production systems
- High volume (>1000 emails/day)
- Needing advanced features (labels, categories)

---

## How to Add a New Provider

Current system is extensible. To add support for a new provider:

### Option 1: Use IMAP (No Code Changes)
Just add the IMAP settings to your `.env`:
```bash
EMAIL_PROVIDER=imap
IMAP_HOST=imap.newprovider.com
IMAP_PORT=993
IMAP_EMAIL=user@newprovider.com
IMAP_PASSWORD=password
```

### Option 2: Add Provider-Specific API
Create a new provider class:
```python
class OutlookAPIClient(EmailClient):
    """Microsoft Outlook/Office 365 API"""
    def __init__(self, ...):
        # Use Microsoft Graph API
        pass
    def fetch_new_emails(self):
        # Optimized for Outlook
        pass
```

Then register it in `email_client.py`:
```python
def create_email_client():
    if config.EMAIL_PROVIDER == "outlook":
        return OutlookAPIClient()
    # ...
```

---

## Comparison Matrix

| Provider | IMAP | Native API | Setup Complexity |
|----------|------|-----------|------------------|
| Gmail | ✅ | ✅ | Medium (OAuth) |
| Outlook | ✅ | Planned | Medium |
| Yahoo | ✅ | Planned | Low |
| ProtonMail | ✅ | No | Low |
| Apple iCloud | ✅ | No | Low |
| Zoho | ✅ | No | Low |
| Corporate Email | ✅ | Varies | Varies |
| Self-Hosted | ✅ | N/A | Low |

---

## No Vendor Lock-In

The architecture ensures:
1. **IMAP as foundation** — works with any provider
2. **Pluggable providers** — easy to add new APIs
3. **Configuration-based** — switch providers via `.env`
4. **Standard interfaces** — all providers implement same interface

You can:
- Switch from Gmail to Outlook without code changes
- Run multiple providers in parallel (one pipeline per provider)
- Migrate to self-hosted email without refactoring

---

## Next Steps

1. **Quick start:** Use IMAP (pick your provider above)
2. **Later:** Add provider-specific APIs as needed
3. **Scale:** Run multiple instances for different email accounts

See `.env.example` for all IMAP configuration options.
