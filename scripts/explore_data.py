"""Quick script to explore real data files"""
import pandas as pd
import warnings
from docx import Document
from pathlib import Path

warnings.filterwarnings('ignore')
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 400)
pd.set_option('display.max_colwidth', 80)
pd.set_option('display.max_rows', 20)

DATA = Path('data')

# --- Alarm data ---
print("=" * 80)
print("ALARM DATA")
print("=" * 80)
for f in (DATA / '告警信息').glob('*'):
    if f.suffix.lower() in ('.xls', '.xlsx'):
        print(f"\nFile: {f.name}")
        df = pd.read_excel(f, dtype=str)
        print(f"Shape: {df.shape}")
        print(f"Columns: {df.columns.tolist()}")
        print("\nFirst 5 rows:")
        print(df.head(5).to_string())

# --- Postmortem data (just titles) ---
print("\n" + "=" * 80)
print("POSTMORTEM REPORTS")
print("=" * 80)
for f in sorted((DATA / '故障复盘报告').glob('*.docx')):
    print(f"\nFile: {f.name}")
    doc = Document(f)
    paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    print(f"Title/First line: {paras[0] if paras else 'N/A'}")
    print(f"Total paragraphs: {len(paras)}")
    # Print first 10 lines
    for i, p in enumerate(paras[:10]):
        print(f"  [{i}] {p[:120]}...")

# --- Application registry ---
print("\n" + "=" * 80)
print("APPLICATION REGISTRY")
print("=" * 80)
for f in sorted((DATA / '系统基本信息').glob('*.xlsx')):
    print(f"\nFile: {f.name}")
    try:
        xl = pd.ExcelFile(f, engine='openpyxl')
        print(f"Sheets: {xl.sheet_names}")
        for sheet in xl.sheet_names[:3]:
            df = pd.read_excel(f, sheet_name=sheet, dtype=str)
            print(f"\n  Sheet [{sheet}]: {df.shape}")
            print(f"  Columns: {df.columns.tolist()[:15]}")
            print(df.head(3).to_string())
    except Exception as e:
        print(f"  Error: {e}")

# --- System relations ---
print("\n" + "=" * 80)
print("SYSTEM RELATIONS")
print("=" * 80)
for f in sorted((DATA / '系统上下游关系').glob('*')):
    print(f"\nFile: {f.name}")
    try:
        df = pd.read_excel(f, dtype=str, engine='openpyxl')
        print(f"Shape: {df.shape}")
        print(f"Columns: {df.columns.tolist()}")
        print(df.head(5).to_string())
    except Exception as e:
        print(f"  Error: {e}")
