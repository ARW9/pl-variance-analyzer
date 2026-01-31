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


# QBO account type mappings (handles various QBO formats and regional variations)
QBO_TYPE_MAP = {
    # Assets
    "Bank": AccountType.ASSET,
    "Cash": AccountType.ASSET,
    "Cash and cash equivalents": AccountType.ASSET,
    "Accounts Receivable": AccountType.ASSET,
    "Accounts receivable (A/R)": AccountType.ASSET,
    "A/R": AccountType.ASSET,
    "Other Current Asset": AccountType.ASSET,
    "Other Current Assets": AccountType.ASSET,
    "Current Assets": AccountType.ASSET,
    "Fixed Asset": AccountType.ASSET,
    "Fixed Assets": AccountType.ASSET,
    "Other Asset": AccountType.ASSET,
    "Other Assets": AccountType.ASSET,
    "Long-term Assets": AccountType.ASSET,
    "Non-current Assets": AccountType.ASSET,
    "Property, plant and equipment": AccountType.ASSET,
    "Inventory": AccountType.ASSET,
    "Prepaid Expenses": AccountType.ASSET,
    
    # Liabilities
    "Accounts Payable": AccountType.LIABILITY,
    "Accounts payable (A/P)": AccountType.LIABILITY,
    "A/P": AccountType.LIABILITY,
    "Credit Card": AccountType.LIABILITY,
    "Other Current Liability": AccountType.LIABILITY,
    "Other Current Liabilities": AccountType.LIABILITY,
    "Current Liabilities": AccountType.LIABILITY,
    "Long Term Liability": AccountType.LIABILITY,
    "Long-term Liabilities": AccountType.LIABILITY,
    "Non-current Liabilities": AccountType.LIABILITY,
    "Payroll Liabilities": AccountType.LIABILITY,
    "Sales Tax Payable": AccountType.LIABILITY,
    "Loan": AccountType.LIABILITY,
    "Line of Credit": AccountType.LIABILITY,
    
    # Equity
    "Equity": AccountType.EQUITY,
    "Owner's Equity": AccountType.EQUITY,
    "Shareholders' Equity": AccountType.EQUITY,
    "Retained Earnings": AccountType.EQUITY,
    "Opening Balance Equity": AccountType.EQUITY,
    
    # Income / Revenue
    "Income": AccountType.REVENUE,
    "Revenue": AccountType.REVENUE,
    "Sales": AccountType.REVENUE,
    "Service Revenue": AccountType.REVENUE,
    "Sales Revenue": AccountType.REVENUE,
    "Other Income": AccountType.OTHER_INCOME,
    "Interest Income": AccountType.OTHER_INCOME,
    "Dividend Income": AccountType.OTHER_INCOME,
    
    # Cost of Goods Sold
    "Cost of Goods Sold": AccountType.COGS,
    "COGS": AccountType.COGS,
    "Cost of Sales": AccountType.COGS,
    "Cost of Revenue": AccountType.COGS,
    "Direct Costs": AccountType.COGS,
    
    # Expenses
    "Expense": AccountType.EXPENSE,
    "Expenses": AccountType.EXPENSE,
    "Operating Expense": AccountType.EXPENSE,
    "Operating Expenses": AccountType.EXPENSE,
    "General & Administrative": AccountType.EXPENSE,
    "G&A": AccountType.EXPENSE,
    "Selling Expense": AccountType.EXPENSE,
    "Other Expense": AccountType.OTHER_EXPENSE,
    "Other Expenses": AccountType.OTHER_EXPENSE,
    "Interest Expense": AccountType.OTHER_EXPENSE,
    "Depreciation": AccountType.EXPENSE,
    "Amortization": AccountType.EXPENSE,
}


def parse_qbo_coa(file_path: str) -> Dict[str, AccountType]:
    """
    Parse QBO Chart of Accounts export
    
    Handles various QBO export formats with flexible column detection
    """
    # First, find the header row
    df_raw = pd.read_excel(file_path, sheet_name=0, header=None)
    
    header_row = 0
    for i in range(min(15, len(df_raw))):
        row_values = [str(v).lower() for v in df_raw.iloc[i].values if pd.notna(v)]
        row_str = ' '.join(row_values)
        # Look for rows that contain both name-like and type-like columns
        has_name = any(x in row_str for x in ['name', 'account'])
        has_type = 'type' in row_str
        if has_name and has_type:
            header_row = i
            break
        # Fallback: just "type" column
        if 'type' in row_values and any('name' in v or 'account' in v for v in row_values):
            header_row = i
            break
    
    # Re-read with correct header
    df = pd.read_excel(file_path, sheet_name=0, header=header_row)
    
    # Normalize column names
    df.columns = [str(c).strip().lower() for c in df.columns]
    
    # Flexible column detection
    def find_col(candidates):
        """Find column by trying multiple name variations"""
        for col in df.columns:
            for candidate in candidates:
                if candidate in col:
                    return col
        return None
    
    # Find the name, type, and number columns with multiple fallbacks
    # Order matters - more specific matches first
    number_col = find_col(['account #', 'account number', 'acct #', 'number', 'no.'])
    # For name, explicitly exclude the number column and prefer 'full name'
    name_col = None
    for candidate in ['full name', 'account name', 'name']:
        for col in df.columns:
            if candidate in col and col != number_col:
                name_col = col
                break
        if name_col:
            break
    # Fallback to 'account' if nothing else found, but not if it's the number column
    if not name_col:
        for col in df.columns:
            if 'account' in col and col != number_col and '#' not in col:
                name_col = col
                break
    
    type_col = find_col(['account type', 'type'])
    
    # If we still can't find columns, try positional guessing
    if not name_col:
        # Look for a column with actual text names (not just numbers)
        for col in df.columns:
            if 'unnamed' not in col.lower() and col not in ['type', 'balance', 'total']:
                sample_vals = df[col].dropna().head(20).astype(str).tolist()
                # Check if values are mostly text (not pure numbers)
                text_count = sum(1 for v in sample_vals if v and not v.replace('-', '').replace('.', '').isdigit())
                if text_count > len(sample_vals) * 0.5:  # More than half are text
                    name_col = col
                    break
        # Fallback: just use first column if nothing else works
        if not name_col:
            for col in df.columns:
                if 'unnamed' not in col.lower():
                    name_col = col
                    break
    
    if not type_col:
        # Look for a column that contains account type values
        for col in df.columns:
            sample_vals = df[col].dropna().head(10).astype(str).tolist()
            if any(v in QBO_TYPE_MAP for v in sample_vals):
                type_col = col
                break
    
    if not name_col or not type_col:
        raise ValueError(f"Could not find Name and Type columns. Found: {list(df.columns)}")
    
    # Debug: store detected columns for troubleshooting
    _coa_debug_info = {
        'columns': list(df.columns),
        'name_col': name_col,
        'type_col': type_col,
        'number_col': number_col,
        'header_row': header_row,
        'sample_row': df.iloc[0].to_dict() if len(df) > 0 else {}
    }
    
    # Build the mapping
    account_map = {}
    
    for _, row in df.iterrows():
        try:
            name = str(row[name_col]).strip() if pd.notna(row[name_col]) else ""
            qbo_type = str(row[type_col]).strip() if pd.notna(row[type_col]) else ""
            
            # Get account number if present
            acct_number = ""
            if number_col and pd.notna(row.get(number_col)):
                acct_number = str(row[number_col]).strip()
                if acct_number == "nan":
                    acct_number = ""
            
            if name and name != "nan" and qbo_type and qbo_type != "nan":
                # Map QBO type to our AccountType
                account_type = QBO_TYPE_MAP.get(qbo_type, AccountType.UNKNOWN)
                
                # Try case-insensitive matching if exact match fails
                if account_type == AccountType.UNKNOWN:
                    for qbo_key, mapped_type in QBO_TYPE_MAP.items():
                        if qbo_key.lower() == qbo_type.lower():
                            account_type = mapped_type
                            break
                
                # Add the plain name
                account_map[name] = account_type
                
                # Also add with account number prefix (for GL matching)
                # QBO formats: "1000 Account Name" or "1000-Account Name"
                if acct_number:
                    account_map[f"{acct_number} {name}"] = account_type
                    account_map[f"{acct_number}-{name}"] = account_type
                    account_map[f"{acct_number}  {name}"] = account_type  # double space variant
        except:
            continue
    
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
