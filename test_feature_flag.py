#!/usr/bin/env python3
"""Test whether FEATURE_PRODUCER_ENGINE flag is being loaded."""
import os
import sys

# Set the flag BEFORE importing config
os.environ['FEATURE_PRODUCER_ENGINE'] = 'true'

from app.config import settings

print(f"ENV var FEATURE_PRODUCER_ENGINE: {os.getenv('FEATURE_PRODUCER_ENGINE')}")
print(f"settings.feature_producer_engine: {settings.feature_producer_engine}")
print(f"Type: {type(settings.feature_producer_engine)}")

if settings.feature_producer_engine:
    print("\n✅ FEATURE FLAG IS ENABLED - ProducerEngine should be invoked")
    sys.exit(0)
else:
    print("\n❌ FEATURE FLAG IS DISABLED - ProducerEngine will NOT be invoked")
    sys.exit(1)
