#!/usr/bin/env python3
"""View detailed audit trail of processed emails."""

import sqlite3
import json
import sys
from datetime import datetime

def format_json(text):
    """Pretty print JSON string."""
    if not text:
        return "(empty)"
    try:
        return json.dumps(json.loads(text), indent=2)
    except:
        return text

def view_email_audit(email_id=None):
    """View audit trail for one or all emails."""
    conn = sqlite3.connect("wallet.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if email_id:
        cursor.execute("""
            SELECT * FROM processed_emails WHERE email_id = ?
        """, (email_id,))
        rows = [cursor.fetchone()]
    else:
        cursor.execute("""
            SELECT * FROM processed_emails ORDER BY created_at DESC
        """)
        rows = cursor.fetchall()

    if not rows or rows[0] is None:
        print(f"❌ No email found: {email_id}")
        return

    for row in rows:
        print(f"\n{'='*80}")
        print(f"📧 EMAIL ID: {row['email_id']}")
        print(f"{'='*80}")

        print(f"\n📌 METADATA")
        print(f"  Subject: {row['subject']}")
        print(f"  From: {row['sender']}")
        print(f"  Received: {row['received_date']}")
        print(f"  Status: {row['status']}")
        print(f"  Retries: {row['retry_count']}")

        print(f"\n📧 EMAIL BODY")
        body = row['email_body']
        if body:
            lines = body.split('\n')
            preview = '\n  '.join(lines[:5])
            if len(lines) > 5:
                preview += f"\n  ... ({len(lines)-5} more lines)"
            print(f"  {preview}")
        else:
            print("  (not saved)")

        print(f"\n🤖 LLM PROCESSING")
        print(f"  Prompt sent:\n{row['llm_prompt'][:200] if row['llm_prompt'] else '(none)'}...")
        print(f"\n  LLM Output:\n{format_json(row['llm_output'])}")
        print(f"\n  LLM Reasoning:\n{format_json(row['llm_reasoning'])}")

        print(f"\n✅ VALIDATION")
        if row['validation_errors']:
            print(f"  ❌ Errors: {row['validation_errors']}")
        else:
            print(f"  ✓ Passed validation")

        print(f"\n📝 DECISION TRAIL")
        print(f"  {row['decision_notes']}")
        if row['error_message']:
            print(f"  Error: {row['error_message']}")

        print(f"\n🎯 RESULT")
        if row['wallet_record_id']:
            print(f"  ✓ Created Wallet record: {row['wallet_record_id']}")
        else:
            print(f"  Not posted to Wallet (Phase {1 if 'api_success' in str(row['status']) else 2})")

        print(f"\n⏱️  TIMELINE")
        print(f"  Created: {row['created_at']}")
        print(f"  Updated: {row['updated_at']}")

def main():
    if len(sys.argv) > 1:
        view_email_audit(sys.argv[1])
    else:
        print("📊 EMAIL PROCESSING AUDIT TRAIL\n")

        conn = sqlite3.connect("wallet.db")
        cursor = conn.cursor()

        # Summary stats
        cursor.execute("""
            SELECT status, COUNT(*) as count FROM processed_emails GROUP BY status
        """)
        print("Summary by Status:")
        for status, count in cursor.fetchall():
            print(f"  {status}: {count}")

        # Recent emails
        print("\n\nRecent Emails:")
        cursor.execute("""
            SELECT email_id, status, subject, decision_notes
            FROM processed_emails
            ORDER BY created_at DESC
            LIMIT 10
        """)

        for email_id, status, subject, notes in cursor.fetchall():
            status_emoji = "✓" if status == "api_success" else "✗" if "error" in status else "⚠"
            print(f"\n  {status_emoji} {email_id} [{status}]")
            print(f"     Subject: {subject[:60]}")
            if notes:
                print(f"     Decision: {notes[:80]}")

        print("\n\nUsage: python audit.py <email_id> (to view full details)")

if __name__ == "__main__":
    main()
