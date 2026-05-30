#!/usr/bin/env python3
"""Analyze LLM interactions to debug structured output and parsing issues."""

import sqlite3
import json
import sys
from collections import defaultdict

def analyze_llm_errors():
    """Analyze all LLM interactions to identify patterns."""
    conn = sqlite3.connect("wallet.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all LLM interactions
    cursor.execute("""
        SELECT * FROM llm_interactions ORDER BY timestamp DESC
    """)
    interactions = [dict(row) for row in cursor.fetchall()]

    if not interactions:
        print("❌ No LLM interactions recorded yet")
        return

    # Summary stats
    total = len(interactions)
    successful = sum(1 for i in interactions if i['success'])
    failed = total - successful

    print(f"\n{'='*80}")
    print(f"📊 LLM INTERACTIONS SUMMARY")
    print(f"{'='*80}")
    print(f"Total interactions: {total}")
    print(f"Successful: {successful} ({100*successful/total:.1f}%)")
    print(f"Failed: {failed} ({100*failed/total:.1f}%)")

    # Provider breakdown
    print(f"\n🔧 BY PROVIDER")
    provider_stats = defaultdict(lambda: {"total": 0, "success": 0, "fail": 0})
    for inter in interactions:
        provider = inter['provider'] or 'unknown'
        provider_stats[provider]["total"] += 1
        if inter['success']:
            provider_stats[provider]["success"] += 1
        else:
            provider_stats[provider]["fail"] += 1

    for provider, stats in sorted(provider_stats.items()):
        success_rate = 100 * stats['success'] / stats['total']
        print(f"  {provider}: {stats['total']} total, {stats['success']} success ({success_rate:.1f}%)")

    # Error patterns
    print(f"\n❌ PARSING ERRORS")
    error_patterns = defaultdict(int)
    for inter in interactions:
        if inter['parsing_error']:
            error = inter['parsing_error']
            # Simplify error for grouping
            if "JSON" in error or "json" in error:
                key = "Invalid JSON format"
            elif "Extra data" in error:
                key = "Extra data after JSON"
            else:
                key = error[:80]
            error_patterns[key] += 1

    if error_patterns:
        for error, count in sorted(error_patterns.items(), key=lambda x: -x[1]):
            print(f"  {count}x: {error}")
    else:
        print("  No parsing errors!")

    # Models used
    print(f"\n🤖 MODELS USED")
    model_stats = defaultdict(lambda: {"total": 0, "success": 0})
    for inter in interactions:
        model = inter['model'] or 'unknown'
        model_stats[model]["total"] += 1
        if inter['success']:
            model_stats[model]["success"] += 1

    for model, stats in sorted(model_stats.items()):
        success_rate = 100 * stats['success'] / stats['total']
        print(f"  {model}: {stats['total']} total, {stats['success']} success ({success_rate:.1f}%)")

    # Recent failures
    print(f"\n🔍 RECENT FAILURES (last 5)")
    failures = [i for i in interactions if not i['success']]
    for inter in failures[:5]:
        print(f"\n  Email: {inter['email_id']}")
        print(f"  Provider: {inter['provider']}")
        print(f"  Error: {inter['parsing_error']}")
        if inter['raw_response']:
            # Show first 200 chars of response
            response_preview = inter['raw_response'][:200]
            response_preview = response_preview.replace('\n', '\\n')
            print(f"  Response: {response_preview}...")

def view_interaction(interaction_id: int):
    """View detailed interaction data."""
    conn = sqlite3.connect("wallet.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM llm_interactions WHERE id = ?
    """, (interaction_id,))
    inter = cursor.fetchone()

    if not inter:
        print(f"❌ Interaction {interaction_id} not found")
        return

    inter = dict(inter)
    print(f"\n{'='*80}")
    print(f"📊 LLM INTERACTION #{inter['id']}")
    print(f"{'='*80}")

    print(f"\nEmail: {inter['email_id']}")
    print(f"Provider: {inter['provider']} / Model: {inter['model']}")
    print(f"Timestamp: {inter['timestamp']}")
    print(f"Status: {'✅ Success' if inter['success'] else '❌ Failed'}")

    if inter['parsing_error']:
        print(f"\n❌ PARSING ERROR")
        print(f"{inter['parsing_error']}")

    print(f"\n📤 RAW RESPONSE FROM LLM")
    print(inter['raw_response'])

    if inter['parsed_output']:
        print(f"\n✅ PARSED OUTPUT")
        try:
            parsed = json.loads(inter['parsed_output'])
            print(json.dumps(parsed, indent=2))
        except:
            print(inter['parsed_output'])

    print(f"\n📝 PROMPTS SENT")
    print(f"System: {inter['system_prompt'][:200]}...")
    print(f"User: {inter['user_prompt'][:200]}...")

def main():
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        view_interaction(int(sys.argv[1]))
    else:
        analyze_llm_errors()

if __name__ == "__main__":
    main()
