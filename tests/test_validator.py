#!/usr/bin/env python3
"""Tests for record validator."""

import sys
sys.path.insert(0, '..')

from validator import RecordValidator
from datetime import datetime, timedelta

def test_valid_record():
    account_map = {"Checking": "123e4567"}
    category_map = {"Food & Drinks": "456e7890"}
    validator = RecordValidator(account_map, category_map)

    record = {
        "amount": -45.99,
        "recordDate": (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z",
        "paymentType": "debit_card",
        "counterParty": "Starbucks #123",
        "note": "Morning coffee",
        "accountName": "Checking",
        "categoryName": "Food & Drinks",
        "skipReason": None,
    }

    is_valid, error = validator.validate_record(record)
    assert is_valid, error
    print("✓ Valid record passes validation")

def test_skip_reason():
    account_map = {"Checking": "123e4567"}
    category_map = {}
    validator = RecordValidator(account_map, category_map)

    record = {
        "amount": 0,
        "recordDate": datetime.utcnow().isoformat() + "Z",
        "paymentType": "cash",
        "counterParty": "ATM",
        "note": "",
        "accountName": "Checking",
        "categoryName": None,
        "skipReason": "Not a transaction - ATM balance check",
    }

    is_valid, error = validator.validate_record(record)
    assert not is_valid
    assert "Skipped" in error
    print("✓ Skip reason properly rejected")

def test_zero_amount():
    account_map = {"Checking": "123e4567"}
    category_map = {}
    validator = RecordValidator(account_map, category_map)

    record = {
        "amount": 0,
        "recordDate": datetime.utcnow().isoformat() + "Z",
        "paymentType": "cash",
        "counterParty": "Test",
        "note": "",
        "accountName": "Checking",
        "categoryName": None,
        "skipReason": None,
    }

    is_valid, error = validator.validate_record(record)
    assert not is_valid
    assert "zero" in error.lower()
    print("✓ Zero amount rejected")

def test_invalid_date():
    account_map = {"Checking": "123e4567"}
    category_map = {}
    validator = RecordValidator(account_map, category_map)

    record = {
        "amount": -50,
        "recordDate": "invalid-date",
        "paymentType": "cash",
        "counterParty": "Test",
        "note": "",
        "accountName": "Checking",
        "categoryName": None,
        "skipReason": None,
    }

    is_valid, error = validator.validate_record(record)
    assert not is_valid
    print("✓ Invalid date rejected")

def test_account_not_found():
    account_map = {"Checking": "123e4567"}
    category_map = {}
    validator = RecordValidator(account_map, category_map)

    record = {
        "amount": -50,
        "recordDate": datetime.utcnow().isoformat() + "Z",
        "paymentType": "cash",
        "counterParty": "Test",
        "note": "",
        "accountName": "Savings",  # Not in map
        "categoryName": None,
        "skipReason": None,
    }

    is_valid, error = validator.validate_record(record)
    assert not is_valid
    assert "not found" in error.lower()
    print("✓ Invalid account rejected")

if __name__ == "__main__":
    test_valid_record()
    test_skip_reason()
    test_zero_amount()
    test_invalid_date()
    test_account_not_found()
    print("\nAll validator tests passed!")
