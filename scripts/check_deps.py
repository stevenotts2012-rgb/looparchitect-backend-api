#!/usr/bin/env python3
"""
Guard script to prevent invalid dependency references.

This script scans all dependency files for common typos like:
- 'fast==' (should be 'fastapi==')
- 'star==' (should be 'starlette==')
- Other common package name typos

Exit code:
  0 = All checks passed
  1 = Invalid dependencies found
"""

import sys
import re
from pathlib import Path


# List of invalid package patterns to search for
FORBIDDEN_PATTERNS = [
    (r"^\s*fast==", "fast==", "fastapi=="),  # Typo: fast instead of fastapi
    (r"^\s*fast\s*=", "fast =", "fastapi ="),  # With spaces
    (r"^\s*star==", "star==", "starlette=="),  # Typo: star instead of starlette
    (r"^\s*fast-api==", "fast-api==", "fastapi=="),  # Alternate typo
]

# Dependency files to scan
DEPENDENCY_FILES = [
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-test.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
]


def check_file(file_path: Path) -> list:
    """
    Check a single file for forbidden patterns.
    
    Returns:
        List of (line_num, line_content, forbidden_pattern, suggestion) tuples
    """
    if not file_path.exists():
        return []
    
    violations = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, start=1):
                for pattern, forbidden, suggestion in FORBIDDEN_PATTERNS:
                    if re.search(pattern, line):
                        violations.append((
                            line_num,
                            line.rstrip(),
                            forbidden,
                            suggestion
                        ))
    except Exception as e:
        print(f"⚠️  Error reading {file_path}: {e}")
    
    return violations


def main():
    """Scan all dependency files and report violations."""
    print("🔍 Checking dependency files for typos and invalid packages...")
    print()
    
    repo_root = Path(__file__).parent.parent
    all_violations = {}
    
    for dep_file in DEPENDENCY_FILES:
        file_path = repo_root / dep_file
        violations = check_file(file_path)
        
        if violations:
            all_violations[dep_file] = violations
    
    if not all_violations:
        print("✅ All dependency files are clean!")
        print()
        for dep_file in DEPENDENCY_FILES:
            file_path = repo_root / dep_file
            if file_path.exists():
                print(f"  ✓ {dep_file}")
        return 0
    
    # Report violations
    print("❌ Found invalid dependency references:")
    print()
    
    for file_path, violations in all_violations.items():
        print(f"📄 {file_path}:")
        for line_num, line_content, forbidden, suggestion in violations:
            print(f"  Line {line_num}: {line_content}")
            print(f"    ❌ Should NOT use: {forbidden}")
            print(f"    ✓ Should use: {suggestion}")
        print()
    
    return 1


if __name__ == "__main__":
    sys.exit(main())
