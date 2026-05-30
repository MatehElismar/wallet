#!/usr/bin/env python3
"""Tests for email parser."""

import sys
sys.path.insert(0, '..')

from email_parser import EmailParser, EmailMetadata
from datetime import datetime

def test_html_to_text():
    parser = EmailParser()
    html = "<html><body><p>Hello <b>World</b></p></body></html>"
    text = parser.extract_text_from_html(html)
    assert "Hello" in text
    assert "World" in text
    print("✓ HTML to text conversion works")

def test_prepare_for_llm():
    parser = EmailParser()
    metadata = EmailMetadata(
        email_id="test_1",
        subject="Starbucks Receipt",
        sender="receipt@starbucks.com",
        received_date=datetime.utcnow(),
        body="Your purchase of $5.50 at Starbucks"
    )
    prepared = parser.prepare_for_llm(metadata)
    assert "From: receipt@starbucks.com" in prepared
    assert "Subject: Starbucks Receipt" in prepared
    assert "Your purchase of $5.50" in prepared
    print("✓ LLM preparation works")

def test_transaction_heuristic():
    parser = EmailParser()

    # Should be a transaction
    assert parser.is_likely_transaction("Bank Alert", "Withdrawal of $100")

    # Should not be a transaction
    assert not parser.is_likely_transaction("Newsletter", "Check out our latest products")
    assert not parser.is_likely_transaction("Verify Your Email", "Click here to confirm")

    print("✓ Transaction heuristic works")

if __name__ == "__main__":
    test_html_to_text()
    test_prepare_for_llm()
    test_transaction_heuristic()
    print("\nAll email parser tests passed!")
