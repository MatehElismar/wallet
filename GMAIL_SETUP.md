# Gmail API Setup Guide

How to set up Gmail API credentials for the email automation system.

## Overview

The system needs two files:
1. **`credentials.json`** — OAuth 2.0 credentials (you download once)
2. **`token.json`** — Access token (auto-generated after first run)

---

## Step 1: Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Sign in with your Google account
3. Click the project dropdown at the top
4. Click **"NEW PROJECT"**
5. Name it: `Wallet Email Sync` (or whatever you prefer)
6. Click **CREATE**
7. Wait for the project to be created, then select it

---

## Step 2: Enable the Gmail API

1. In the Cloud Console, search for **"Gmail API"** (use the search bar at top)
2. Click on **Gmail API** in the results
3. Click the **ENABLE** button
4. Wait for it to enable

---

## Step 3: Create OAuth 2.0 Credentials

1. In the Cloud Console, go to **APIs & Services** > **Credentials**
2. Click **+ CREATE CREDENTIALS** button (top left)
3. Choose **OAuth client ID**
4. A dialog appears: **"To create an OAuth client ID, you must first set your OAuth consent screen."**
5. Click **Configure Consent Screen**

### Configure Consent Screen

1. Choose **User Type: External** (unless you're in a Google Workspace org)
2. Click **CREATE**
3. Fill in the form:
   - **App name:** `Wallet Email Sync`
   - **User support email:** Your email address
   - **Developer contact:** Your email address
4. Click **SAVE AND CONTINUE**
5. On **Scopes** step:
   - Click **ADD OR REMOVE SCOPES**
   - Search for `gmail.readonly`
   - Check the box for `https://www.googleapis.com/auth/gmail.readonly`
   - Click **UPDATE**
6. Click **SAVE AND CONTINUE**
7. On **Test users** step:
   - Click **ADD USERS**
   - Add your email address (the one you'll use for email checking)
   - Click **ADD**
8. Click **SAVE AND CONTINUE**
9. Review and click **BACK TO DASHBOARD**

---

## Step 4: Create OAuth Client ID

1. Back on **APIs & Services > Credentials**
2. Click **+ CREATE CREDENTIALS** again
3. Choose **OAuth client ID**
4. For **Application type**, select **Desktop application**
5. Name it: `Wallet Email Sync CLI`
6. Click **CREATE**
7. A dialog appears showing your credentials
8. Click **DOWNLOAD JSON** button
9. Save this file as `credentials.json` in the wallet project root

```bash
# It should be at:
/Users/mateh/projects/wallet/credentials.json
```

---

## Step 5: Configure Environment

Add to your `.env` file:

```bash
EMAIL_PROVIDER=gmail
GMAIL_CREDENTIALS_FILE=credentials.json
GMAIL_TOKEN_FILE=token.json
```

---

## Step 6: Generate token.json

The first time you run the pipeline with Gmail, it will:
1. Read `credentials.json`
2. Open a browser to ask for permission
3. You authorize the app
4. Auto-generates `token.json` (keeps it for future runs)

### First-time auth (Phase 1 with Gmail):

```bash
export EMAIL_PROVIDER=gmail
python main.py --phase 1
```

This will:
1. Try to load `token.json` (doesn't exist yet)
2. Open your browser with a Google login screen
3. Ask for permission to access emails (read-only)
4. After you authorize, generates `token.json`
5. Runs the pipeline

---

## Troubleshooting

### "credentials.json not found"
- Make sure you downloaded the JSON file from Google Cloud
- Placed it in the project root: `/Users/mateh/projects/wallet/credentials.json`
- Or set `GMAIL_CREDENTIALS_FILE=path/to/file` in `.env`

### "Invalid client" error
- Make sure you created an **OAuth client ID** (not just API key)
- Make sure the file is actually OAuth 2.0 JSON (check the file content)
- You should see `"client_id"` and `"client_secret"` in the file

### Browser doesn't open for auth
- Copy the URL from the terminal manually and paste in browser
- Or: `python -m webbrowser https://...` to force open

### "gmail.readonly scope not approved"
- Make sure you added the scope during consent screen setup
- You may need to delete token.json and re-authorize

### "Error 403: access_denied"
- Did you add your email to **Test users** during consent setup?
- For External apps, only test users can authorize
- To allow others, you need to move it to Production status (requires review)

---

## Understanding the Files

### credentials.json
```json
{
  "installed": {
    "client_id": "xxx.apps.googleusercontent.com",
    "client_secret": "xxx",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    ...
  }
}
```

**Important:** 
- Never commit this to git
- It's already in `.gitignore`
- It's technically safe to share, but good practice to keep it private

### token.json
```json
{
  "token": "ya29.xxx",
  "refresh_token": "1//xxx",
  "token_uri": "https://oauth2.googleapis.com/token",
  ...
}
```

**Important:**
- **DO NOT COMMIT THIS TO GIT** (contains auth token)
- It's already in `.gitignore`
- This is what the system uses to access emails
- Auto-refreshed when it expires

---

## Security Notes

- Both files allow access to your Gmail inbox
- `credentials.json` is technically public (it's registered with Google)
- `token.json` is sensitive (contains auth token) — keep it private
- The token is read-only (can only read emails, not send/delete)
- Scope: `gmail.readonly` — can only READ emails, not modify them

---

## Testing the Setup

Once you have both files, test:

```bash
export EMAIL_PROVIDER=gmail
python main.py --phase 1
```

You should see:
```
INFO - Connected to Gmail API
INFO - Fetched N new emails
INFO - Processing...
```

If you see mock emails instead, check that `EMAIL_PROVIDER=gmail` is set.

---

## Revoking Access

If you want to revoke the app's access later:

1. Go to [Google Account Security Settings](https://myaccount.google.com/security)
2. Scroll down to **"Your apps with access to Google Account"**
3. Find **Wallet Email Sync**
4. Click it and select **Remove access**

This invalidates `token.json` (you'll need to re-authorize next time).

---

## Alternative: Using IMAP Instead

If you don't want to set up OAuth, you can use IMAP instead:

```bash
EMAIL_PROVIDER=imap
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_EMAIL=your_email@gmail.com
IMAP_PASSWORD=your_app_password  # NOT your regular password
```

For Gmail with IMAP:
1. Enable 2FA on your Google account
2. Create an [App Password](https://myaccount.google.com/apppasswords)
3. Use that password in `IMAP_PASSWORD`

This is simpler but less secure (password in .env file).

---

## Getting Help

If you get stuck:

1. Check the error message in the logs
2. Review the troubleshooting section above
3. Check that Gmail API is **ENABLED** in Cloud Console
4. Check that you added your email as a **Test User**
5. Verify `credentials.json` exists and is valid JSON

---

## Quick Reference

```bash
# 1. Set provider
export EMAIL_PROVIDER=gmail

# 2. First run (generates token.json)
python main.py --phase 1

# 3. Then use normally
python main.py --phase 2
```

Done! The system will fetch your real emails.
