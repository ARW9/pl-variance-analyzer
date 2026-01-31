"""
QBO Chart of Accounts Parser
Extracts account names and types for accurate GL classification
"""

import pandas as pd
import json
from pathlib import Path
from typing import Dict
from enum import Enum


class AccountType(Enum):
    ASSET = "Asset"
    LIABILITY = "Liability"
    EQUITY = "Equity"
    REVENUE = "Revenue"
    COGS = "Cost of Goods Sold"
    EXPENSE = "Expense"
    OTHER_INCOME = "Other Income"
    OTHER_EXPENSE = "Other Expense"
    UNKNOWN = "Unknown"


# QBO account type mappings (handles various QBO formats)
QBO_TYPE_MAP = {
    # Assets
    "Bank": AccountType.ASSET,
    "Accounts Receivable": AccountType.ASSET,
    "Accounts receivable (A/R)": AccountType.ASSET,
    "Other Current Asset": AccountType.ASSET,
    "Other Current Assets": AccountType.ASSET,
    "Fixed Asset": AccountType.ASSET,
    "Other Asset": AccountType.ASSET,
    "Long-term Assets": AccountType.ASSET,
    "Property, plant and equipment": AccountType.ASSET,
    
    # Liabilities
    "Accounts Payable": AccountType.LIABILITY,
    "Accounts payable (A/P)": AccountType.LIABILITY,
    "Credit Card": AccountType.LIABILITY,
    "Other Current Liability": AccountType.LIABILITY,
    "Other Current Liabilities": AccountType.LIABILITY,
    "Long Term Liability": AccountType.LIABILITY,
    "Long-term Liabilities": AccountType.LIABILITY,
    
    # Equity
    "Equity": AccountType.EQUITY,
    
    # Income
    "Income": AccountType.REVENUE,
    "Other Income": AccountType.OTHER_INCOME,
    
    # Expenses
    "Cost of Goods Sold": AccountType.COGS,
    "Expense": AccountType.EXPENSE,
    "Expenses": AccountType.EXPENSE,
    "Other Expense": AccountType.OTHER_EXPENSE,
}


def parse_qbo_coa(file_path: str) -> Dict[str, AccountType]:
    """
    Parse QBO Chart of Accounts export
    
    Expected columns: Full name, Type, Detail Type, Description, Total balance
    """
    # First, find the header row
    df_raw = pd.read_excel(file_path, sheet_name=0, header=None)
    
    header_row = 0
    for i in range(min(10, len(df_raw))):
        row_values = [str(v).lower() for v in df_raw.iloc[i].values if pd.notna(v)]
        if any('full name' in v or ('name' in v and 'type' in str(df_raw.iloc[i].values)) for v in row_values):
            header_row = i
            break
        if 'type' in row_values:
            header_row = i
            break
    
    # Re-read with correct header
    df = pd.read_excel(file_path, sheet_name=0, header=header_row)
    
    # Normalize column names
    df.columns = [str(c).strip().lower() for c in df.columns]
    
    # Find the name and type columns
    name_col = None
    type_col = None
    
    for col in df.columns:
        if 'full name' in col or col == 'name' or col == 'account':
            name_col = col
        if col == 'type':
            type_col = col
    
    if not name_col or not type_col:
        raise ValueError(f"Could not find Name and Type columns. Found: {list(df.columns)}")
    
    # Build the mapping
    account_map = {}
    
    for _, row in df.iterrows():
        name = str(row[name_col]).strip() if pd.notna(row[name_col]) else ""
        qbo_type = str(row[type_col]).strip() if pd.notna(row[type_col]) else ""
        
        if name and name != "nan" and qbo_type:
            # Map QBO type to our AccountType
            account_type = QBO_TYPE_MAP.get(qbo_type, AccountType.UNKNOWN)
            account_map[name] = account_type
    
    return account_map


def save_account_map(account_map: Dict[str, AccountType], output_path: str):
    """Save account mapping to JSON for future use"""
    # Convert enum to string for JSON
    serializable = {k: v.value for k, v in account_map.items()}
    
    with open(output_path, 'w') as f:
        json.dump(serializable, f, indent=2)
    
    print(f"Saved {len(account_map)} account mappings to {output_path}")


def load_account_map(input_path: str) -> Dict[str, AccountType]:
    """Load previously saved account mapping"""
    with open(input_path, 'r') as f:
        data = json.load(f)
    
    # Convert string back to enum
    return {k: AccountType(v) for k, v in data.items()}


def print_setup_instructions():
    """Print instructions for exporting Chart of Accounts from QBO"""
    instructions = """
╔══════════════════════════════════════════════════════════════════╗
║           HOW TO EXPORT CHART OF ACCOUNTS FROM QBO               ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  1. Log into QuickBooks Online                                   ║
║                                                                  ║
║  2. Go to: Settings (gear icon) → Chart of Accounts              ║
║                                                                  ║
║  3. Click the "Run Report" button (top right)                    ║
║     This opens the Account List report                           ║
║                                                                  ║
║  4. Click "Export" (dropdown arrow) → Export to Excel            ║
║                                                                  ║
║  5. Save the .xlsx file                                          ║
║                                                                  ║
║  This only needs to be done once per company.                    ║
║  The mapping will be saved for future GL imports.                ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════╗
║              HOW TO EXPORT GENERAL LEDGER FROM QBO               ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  1. Go to: Reports → Search "General Ledger"                     ║
║                                                                  ║
║  2. Set your date range (e.g., This Month, Last Month, Custom)   ║
║                                                                  ║
║  3. Click "Run Report"                                           ║
║                                                                  ║
║  4. Click "Export" → Export to Excel                             ║
║                                                                  ║
║  5. Save the .xlsx file                                          ║
║                                                                  ║
║  Export the GL for any period you want to analyze.               ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
"""
    print(instructions)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print_setup_instructions()
        print("\nUsage: python coa_parser.py <chart_of_accounts.xlsx> [output_mapping.json]")
        sys.exit(0)
    
    coa_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "account_mapping.json"
    
    print(f"Parsing Chart of Accounts: {coa_file}")
    account_map = parse_qbo_coa(coa_file)
    
    print(f"\nFound {len(account_map)} accounts:")
    for acc_type in AccountType:
        accounts = [k for k, v in account_map.items() if v == acc_type]
        if accounts:
            print(f"\n{acc_type.value}:")
            for acc in accounts[:10]:  # Show first 10
                print(f"  - {acc}")
            if len(accounts) > 10:
                print(f"  ... and {len(accounts) - 10} more")
    
    save_account_map(account_map, output_file)
