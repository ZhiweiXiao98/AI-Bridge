import sys
import os
import re

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Build pattern dynamically
fence = "```"
pattern = fence + r"(?:python|py|bash|sh|javascript|js|typescript|ts|java|cpp|c|go|rust|ruby|php|swift|kotlin)?\s*\n(.*?)\n" + fence

print("Testing pattern:", pattern)
print("=" * 60)

# Test 1: Simple Python block
test1 = "Some text\n\n" + fence + "python\nprint(\"hello\")\n" + fence + "\n\nMore"
matches1 = re.findall(pattern, test1, re.DOTALL)
print(f"Test 1 - Simple block: {len(matches1)} matches (expected 1)")
if matches1:
    print(f"  Content: {matches1[0][:50]}")

# Test 2: Multiple blocks
test2 = fence + "python\ncode1\n" + fence + "\n\n" + fence + "python\ncode2\n" + fence
matches2 = re.findall(pattern, test2, re.DOTALL)
print(f"Test 2 - Multiple blocks: {len(matches2)} matches (expected 2)")

# Test 3: With filename (should filter out)
test3 = fence + "python\n# filename: test.py\ncode\n" + fence
matches3 = re.findall(pattern, test3, re.DOTALL)
executable3 = [c for c in matches3 if not re.match(r"^\s*#\s*filename:", c, re.MULTILINE)]
print(f"Test 3 - With filename: {len(matches3)} raw, {len(executable3)} executable (expected 0)")

# Test 4: No language tag
test4 = fence + "\nprint(\"no tag\")\n" + fence
matches4 = re.findall(pattern, test4, re.DOTALL)
print(f"Test 4 - No tag: {len(matches4)} matches (expected 1)")

print("=" * 60)
