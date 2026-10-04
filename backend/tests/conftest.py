import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# Existing regression tests intentionally exercise the offline compatibility
# mode. Production defaults to Gemini-only generic Text-to-SQL.
os.environ["ALLOW_DETERMINISTIC_FALLBACK"] = "true"
