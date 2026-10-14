"""Isolated HTTP contract tests runnable without the legacy LDAP dependency.

Run with --confcutdir=tests/drf to avoid booting the legacy full application.
"""

import os

os.environ["TESTING"] = "true"
os.environ["PRODUCTION"] = "true"
