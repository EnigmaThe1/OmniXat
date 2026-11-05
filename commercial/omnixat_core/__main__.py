"""Offline, read-only catalogue for development; no credentials required."""
import json
from .rules import catalogue

if __name__ == "__main__":
    print(json.dumps(catalogue(), indent=2))
