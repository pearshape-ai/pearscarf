#!/usr/bin/env python3
"""Standalone entry point for extraction prompt testing.

Usage:
    python scripts/test_extraction.py                      # all relevant emails
    python scripts/test_extraction.py email_042             # single record
    python scripts/test_extraction.py email_001 email_005   # multiple records
"""

import sys

from dotenv import load_dotenv

load_dotenv()

from pearscaff.extract_test import run_extraction

record_ids = sys.argv[1:] if len(sys.argv) > 1 else None
run_extraction(record_ids)
