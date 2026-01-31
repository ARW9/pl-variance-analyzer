"""
CSV Parser for QBO Exports
Handles Chart of Accounts and General Ledger CSV files
"""

import pandas as pd
from typing import Dict, List, Tuple
from dataclasses import dataclass
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


# QBO account type mappings
QBO_TYPE_MAP = {
    # Assets
    "Bank": AccountType.ASSET,
    "Accounts receivable (A/R)": AccountType.ASSET,
    "Other Current Asset": AccountType.ASSET,
    "Other Current Assets": AccountType.ASSET,
    "Fixed Asset": AccountType.ASSET,
    "Other Asset": AccountType.ASSET,
    
    # Liabilities
    "Accounts payable (A/P)": AccountType.LIABILITY,
    "Credit Card": AccountType.LIABILITY,
    "Other Current Liability": AccountType.LIABILITY,
    "Long Term Liability": AccountType.LIABILITY,
    
    # Equity
    "Equity": AccountType.EQUITY,
    "Owner's Equity": AccountType.EQUITY,
    "Partner's Equity": AccountType.EQUITY,
    "Opening Balance Equity": AccountType.EQUITY,
    "Retained Earnings": AccountType.EQUITY,
    "Partner Contributions": AccountType.EQUITY,
    "Partner Distributions": AccountType.EQUITY,
    
    # Revenue
    "Income": AccountType.REVENUE,
    "Revenue": AccountType.REVENUE,
    "Sales of Product Income": AccountType.REVENUE,
    "Service/Fee Income": AccountType.REVENUE,
    "Discounts/Refunds Given": AccountType.REVENUE,
    
    # COGS
    "Cost of Goods Sold": AccountType.COGS,
    "Cost of labor - COS": AccountType.COGS,
    "Supplies & Materials - COGS": AccountType.COGS,
    
    # Expenses
    "Expense": AccountType.EXPENSE,
    "Expenses": AccountType.EXPENSE,
    
    # Other Income
    "Other Income": AccountType.OTHER_INCOME,
    
    # Other Expense
    "Other Expense": AccountType.OTHER_EXPENSE,
}


@dataclass
class Transaction:
    date: str
    account: str
    account_type: AccountType
    description: str
    amount: float
    vendor: str = ""


def parse_coa_csv(file_path: str) -> Dict[str, AccountType]:
    """
    Parse QBO Chart of Accounts CSV export
    
    Returns: Dict mapping account names to their types
    """
    df = pd.read_csv(file_path, header=None)
    
    # Find header row (contains "Full name" and "Type")
    header_row = 0
    for i, row in df.iterrows():
        row_str = ' '.join([str(v).lower() for v in row.values if pd.notna(v)])
        if 'full name' in row_str and 'type' in row_str:
            header_row = i
            break
    
    # Re-read with correct header
    df = pd.read_csv(file_path, header=header_row)
    df.columns = [str(c).strip().lower() for c in df.columns]
    
    # Find columns
    name_col = None
    type_col = None
    detail_col = None
    
    for col in df.columns:
        if 'full name' in col or col == 'name':
            name_col = col
        elif col == 'type':
            type_col = col
        elif 'detail' in col:
            detail_col = col
    
    if not name_col or not type_col:
        raise ValueError(f"Could not find required columns. Found: {list(df.columns)}")
    
    account_map = {}
    
    for _, row in df.iterrows():
        name = str(row[name_col]).strip() if pd.notna(row[name_col]) else ""
        qbo_type = str(row[type_col]).strip() if pd.notna(row[type_col]) else ""
        detail_type = str(row[detail_col]).strip() if detail_col and pd.notna(row[detail_col]) else ""
        
        if name and name != "nan" and qbo_type and qbo_type != "nan":
            # Try detail type first (more specific), then main type
            account_type = QBO_TYPE_MAP.get(detail_type, QBO_TYPE_MAP.get(qbo_type, AccountType.UNKNOWN))
            
            # Case-insensitive fallback
            if account_type == AccountType.UNKNOWN:
                for key, val in QBO_TYPE_MAP.items():
                    if key.lower() == qbo_type.lower() or key.lower() == detail_type.lower():
                        account_type = val
                        break
            
            account_map[name] = account_type
            
            # Also add the last part after colon for matching
            if ":" in name:
                child_name = name.split(":")[-1].strip()
                if child_name not in account_map:
                    account_map[child_name] = account_type
    
    return account_map


def parse_gl_csv(file_path: str, account_map: Dict[str, AccountType]) -> Tuple[Dict[str, dict], List[Transaction]]:
    """
    Parse QBO General Ledger CSV export
    
    Returns: (account_totals, all_transactions)
    """
    df = pd.read_csv(file_path, header=None)
    
    # Find header row
    header_row = 0
    for i, row in df.iterrows():
        row_str = ' '.join([str(v).lower() for v in row.values if pd.notna(v)])
        if 'date' in row_str and 'amount' in row_str:
            header_row = i
            break
    
    # Map columns
    header = df.iloc[header_row]
    col_map = {}
    for j, val in enumerate(header.values):
        if pd.notna(val):
            col_map[str(val).strip().lower()] = j
    
    def find_col(names):
        for name in names:
            for col_name, idx in col_map.items():
                if name in col_name:
                    return idx
        return None
    
    date_col = find_col(['transaction date', 'date'])
    name_col = find_col(['name'])
    desc_col = find_col(['memo', 'description'])
    split_col = find_col(['split'])
    amount_col = find_col(['amount'])
    
    # Parse transactions by Split account (where P&L accounts appear)
    account_totals = {}
    all_transactions = []
    
    for i in range(header_row + 1, len(df)):
        row = df.iloc[i]
        
        # Get split account (this is the P&L account)
        split_account = str(row[split_col]).strip() if split_col and pd.notna(row[split_col]) else ""
        if not split_account or split_account == "nan" or split_account == "-Split-":
            continue
        
        # Get amount
        amount = 0
        if amount_col and pd.notna(row[amount_col]):
            try:
                val = str(row[amount_col]).replace(',', '').replace('"', '')
                amount = float(val)
            except:
                continue
        
        if amount == 0:
            continue
        
        # Get date
        date = str(row[date_col]).strip() if date_col and pd.notna(row[date_col]) else ""
        if date == "nan" or date == "Beginning Balance":
            continue
        
        # Get vendor/name
        vendor = str(row[name_col]).strip() if name_col and pd.notna(row[name_col]) else ""
        if vendor == "nan":
            vendor = ""
        
        # Get description
        desc = str(row[desc_col]).strip() if desc_col and pd.notna(row[desc_col]) else ""
        if desc == "nan":
            desc = ""
        
        # Look up account type
        account_type = lookup_account_type(split_account, account_map)
        
        # Create transaction (reverse sign - GL shows from bank perspective)
        txn = Transaction(
            date=date,
            account=split_account,
            account_type=account_type,
            description=desc,
            amount=-amount,  # Reverse sign for P&L perspective
            vendor=vendor
        )
        all_transactions.append(txn)
        
        # Aggregate by account
        if split_account not in account_totals:
            account_totals[split_account] = {
                "name": split_account,
                "type": account_type,
                "total": 0,
                "count": 0
            }
        account_totals[split_account]["total"] += -amount
        account_totals[split_account]["count"] += 1
    
    return account_totals, all_transactions


def lookup_account_type(name: str, account_map: Dict[str, AccountType]) -> AccountType:
    """Look up account type with fuzzy matching"""
    # Direct match
    if name in account_map:
        return account_map[name]
    
    # Case-insensitive
    name_lower = name.lower()
    for coa_name, coa_type in account_map.items():
        if coa_name.lower() == name_lower:
            return coa_type
    
    # Match child name in parent:child format
    for coa_name, coa_type in account_map.items():
        if ":" in coa_name:
            child = coa_name.split(":")[-1].strip()
            if child.lower() == name_lower:
                return coa_type
    
    return AccountType.UNKNOWN


def build_pnl_from_csv(account_totals: Dict[str, dict]) -> Dict[str, Dict[str, float]]:
    """Build P&L statement from parsed account totals"""
    pnl = {
        "Revenue": {},
        "Cost of Goods Sold": {},
        "Expenses": {},
        "Other Income": {},
        "Other Expense": {}
    }
    
    for name, data in account_totals.items():
        acc_type = data["type"]
        total = data["total"]
        
        if acc_type == AccountType.REVENUE:
            pnl["Revenue"][name] = total
        elif acc_type == AccountType.COGS:
            pnl["Cost of Goods Sold"][name] = total
        elif acc_type == AccountType.EXPENSE:
            pnl["Expenses"][name] = total
        elif acc_type == AccountType.OTHER_INCOME:
            pnl["Other Income"][name] = total
        elif acc_type == AccountType.OTHER_EXPENSE:
            pnl["Other Expense"][name] = total
    
    return pnl


def analyze_csv_files(coa_path: str, gl_path: str) -> dict:
    """
    Main entry point: analyze COA and GL CSV files
    
    Returns dict with P&L data and summary
    """
    # Parse COA
    account_map = parse_coa_csv(coa_path)
    
    # Parse GL
    account_totals, transactions = parse_gl_csv(gl_path, account_map)
    
    # Build P&L
    pnl = build_pnl_from_csv(account_totals)
    
    # Calculate totals
    total_revenue = sum(abs(v) for v in pnl["Revenue"].values())
    total_cogs = sum(abs(v) for v in pnl["Cost of Goods Sold"].values())
    total_expenses = sum(abs(v) for v in pnl["Expenses"].values())
    total_other_income = sum(abs(v) for v in pnl["Other Income"].values())
    total_other_expense = sum(abs(v) for v in pnl["Other Expense"].values())
    
    gross_profit = total_revenue - total_cogs
    operating_income = gross_profit - total_expenses
    net_income = operating_income + total_other_income - total_other_expense
    
    return {
        "pnl": pnl,
        "totals": {
            "revenue": total_revenue,
            "cogs": total_cogs,
            "gross_profit": gross_profit,
            "expenses": total_expenses,
            "operating_income": operating_income,
            "other_income": total_other_income,
            "other_expense": total_other_expense,
            "net_income": net_income
        },
        "account_totals": account_totals,
        "transactions": transactions,
        "accounts_parsed": len(account_map),
        "transactions_parsed": len(transactions)
    }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python csv_parser.py <coa.csv> <gl.csv>")
        sys.exit(1)
    
    result = analyze_csv_files(sys.argv[1], sys.argv[2])
    
    print(f"\nParsed {result['accounts_parsed']} accounts, {result['transactions_parsed']} transactions")
    print(f"\n=== P&L Summary ===")
    print(f"Revenue:          ${result['totals']['revenue']:,.2f}")
    print(f"COGS:             ${result['totals']['cogs']:,.2f}")
    print(f"Gross Profit:     ${result['totals']['gross_profit']:,.2f}")
    print(f"Expenses:         ${result['totals']['expenses']:,.2f}")
    print(f"Operating Income: ${result['totals']['operating_income']:,.2f}")
    print(f"Other Income:     ${result['totals']['other_income']:,.2f}")
    print(f"Other Expense:    ${result['totals']['other_expense']:,.2f}")
    print(f"Net Income:       ${result['totals']['net_income']:,.2f}")
