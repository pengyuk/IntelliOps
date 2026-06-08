# encoding: utf-8
"""Fix pre-existing encoding corruption in db.py"""
import sys, re

with open("d:\\大模型\\IntelliOps\\src\\backend\\db.py", "rb") as f:
    raw = f.read()

# The problematic line 323 in Python source has a CJK string that contains 
# a byte sequence that Python interprets incorrectly.
# Replace the corrupted bytes with clean UTF-8 equivalents.

# Strategy: find each string literal with odd quotes and ensure 
# the closing quote is present.

text = raw.decode("utf-8", errors="replace")

# Replace problematic private use area chars
text = text.replace("\ue1bd", "?")
text = text.replace("\ue15d", "?")
text = text.replace("\u20ac", "?")
text = text.replace("\ufffd", "?")
text = text.replace("\u3002", ".")
text = text.replace("\u201d", '"')
text = text.replace("\u201c", '"')
text = text.replace("\ue046", "?")
text = text.replace("\ue11f", "?")

# Check syntax
with open("d:\\大模型\\IntelliOps\\src\\backend\\db.py", "w", encoding="utf-8") as f:
    f.write(text)

import py_compile
try:
    py_compile.compile("d:\\大模型\\IntelliOps\\src\\backend\\db.py", doraise=True)
    print("Syntax OK!")
except py_compile.PyCompileError as e:
    print(f"Error: {e}")
