"""
QBO General Ledger Parser
Parses QuickBooks Online GL exports and builds financial statements
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


@dataclass
class Account:
    name: str
    account_type: AccountType
    balance: float
    parent: str = None


def classify_account(account_name: str) -> AccountType:
    """Classify an account based on its name"""
    name_lower = account_name.lower().strip()
    
    # Skip parent accounts with sub-accounts (avoid double counting)
    if "with sub-accounts" in name_lower:
        return AccountType.UNKNOWN
    
    # Assets - check first to catch bank accounts
    if any(x in name_lower for x in ['rbc ', 'scotiabank', 'paypal', 'stripe', 
                                      'wix', 'wealthsimple', 'inventory', 'prepaid', 
                                      'accrued revenue', 'receivable', 'pocket', 'clearing']):
        return AccountType.ASSET
    
    # Liabilities - check before revenue to catch deferred revenue
    if any(x in name_lower for x in ['payable', 'visa', 'mastercard', 'credit card', 'hst', 
                                      'gst', 'tax liabilities', 'deferred revenue', 'due to',
                                      'owing', 'liability', 'esdc']):
        return AccountType.LIABILITY
    
    # Equity
    if any(x in name_lower for x in ['equity', 'retained', 'capital', 'owner']):
        return AccountType.EQUITY
    
    # Other Income (check before revenue)
    if any(x in name_lower for x in ['interest income', 'cash back', 'rebate', 'canada summer', 'carbon canada']):
        return AccountType.OTHER_INCOME
    
    # Revenue (but not M&E Sales Tax which is an expense recovery)
    if any(x in name_lower for x in ['sales income', 'sales', 'revenue']) and 'm&e' not in name_lower:
        return AccountType.REVENUE
    
    # M&E Sales Tax is an expense
    if 'm&e sales tax' in name_lower:
        return AccountType.EXPENSE
    
    # COGS
    if any(x in name_lower for x in ['cog ', 'cos ', 'cost of goods', 'cost of sales', 'cogs']):
        return AccountType.COGS
    
    # Other Expense (CRA penalties only - Interest Expense is operating)
    if any(x in name_lower for x in ['penalties', 'cra interest']):
        return AccountType.OTHER_EXPENSE
    
    # Expenses
    if any(x in name_lower for x in ['expense', 'exp', 'fees', 'charges', 'rent', 'utilities', 
                                      'insurance', 'advertising', 'occupancy', 'amenities',
                                      'repairs', 'maintenance', 'travel', 'meals', 'office',
                                      'computer', 'software', 'telephone', 'internet', 
                                      'shipping', 'postage', 'donations', 'professional dev',
                                      'bookkeeping', 'accounting', 'gifts', 'interest expense']):
        return AccountType.EXPENSE
    
    return AccountType.UNKNOWN


def parse_qbo_gl(file_path: str) -> Dict[str, Account]:
    """Parse a QBO General Ledger export"""
    
    df = pd.read_excel(file_path, sheet_name=0, header=None)
    
    accounts = {}
    current_account = None
    current_parent = None
    
    # First pass: collect all account totals
    all_totals = {}
    for i, row in df.iterrows():
        col0 = str(row[0]).strip() if pd.notna(row[0]) else ""
        if col0.startswith("Total for "):
            account_name = col0.replace("Total for ", "")
            balance = row[8] if pd.notna(row[8]) else 0
            all_totals[account_name] = float(balance) if balance else 0
    
    # Identify summary accounts to exclude (roll-ups that would cause double-counting)
    parent_accounts = set()
    
    # These are QBO summary accounts that roll up their children
    summary_accounts = ["SALES INCOME", "GENERAL & ADMIN EXP", "OCCUPANCY COSTS", 
                        "SALES TAX LIABILITIES"]
    
    for name in all_totals.keys():
        # "with sub-accounts" entries are always summaries - exclude them
        if "with sub-accounts" in name:
            parent_accounts.add(name)
        # Also exclude known summary parent accounts
        if name in summary_accounts:
            parent_accounts.add(name)
    
    # Second pass: only include leaf accounts (not parents)
    for i, row in df.iterrows():
        col0 = str(row[0]).strip() if pd.notna(row[0]) else ""
        
        # Skip header rows
        if col0 in ["General Ledger", "nan", ""] or "2024" in col0 or "2025" in col0 or "2026" in col0:
            continue
        
        # Check for "Total for X" row - this gives us the account balance
        if col0.startswith("Total for "):
            account_name = col0.replace("Total for ", "")
            
            # Skip parent/summary accounts
            if account_name in parent_accounts:
                continue
            
            balance = row[8] if pd.notna(row[8]) else 0
            
            if account_name not in accounts:
                accounts[account_name] = Account(
                    name=account_name,
                    account_type=classify_account(account_name),
                    balance=float(balance) if balance else 0,
                    parent=current_parent
                )
        
        # Check for account header (new account section)
        elif col0 and not col0.startswith("Total") and pd.isna(row[1]):
            # This is an account name row
            # Check if it's a sub-account (indented with spaces)
            original = str(row[0]) if pd.notna(row[0]) else ""
            if original.startswith("   "):
                current_account = col0
            else:
                current_parent = col0
                current_account = col0
    
    return accounts


def build_financial_statements(accounts: Dict[str, Account]) -> Tuple[Dict, Dict]:
    """Build P&L and Balance Sheet from parsed accounts"""
    
    pnl = {
        "Revenue": {},
        "Cost of Goods Sold": {},
        "Expenses": {},
        "Other Income": {},
        "Other Expense": {}
    }
    
    balance_sheet = {
        "Assets": {},
        "Liabilities": {},
        "Equity": {}
    }
    
    for name, account in accounts.items():
        if account.account_type == AccountType.REVENUE:
            pnl["Revenue"][name] = account.balance
        elif account.account_type == AccountType.COGS:
            pnl["Cost of Goods Sold"][name] = account.balance
        elif account.account_type == AccountType.EXPENSE:
            pnl["Expenses"][name] = account.balance
        elif account.account_type == AccountType.OTHER_INCOME:
            pnl["Other Income"][name] = account.balance
        elif account.account_type == AccountType.OTHER_EXPENSE:
            pnl["Other Expense"][name] = account.balance
        elif account.account_type == AccountType.ASSET:
            balance_sheet["Assets"][name] = account.balance
        elif account.account_type == AccountType.LIABILITY:
            balance_sheet["Liabilities"][name] = account.balance
        elif account.account_type == AccountType.EQUITY:
            balance_sheet["Equity"][name] = account.balance
    
    return pnl, balance_sheet


def format_currency(amount: float) -> str:
    """Format a number as currency"""
    if amount < 0:
        return f"(${abs(amount):,.2f})"
    return f"${amount:,.2f}"


def print_pnl(pnl: Dict) -> str:
    """Generate a formatted P&L report"""
    lines = []
    lines.append("=" * 60)
    lines.append("PROFIT & LOSS STATEMENT")
    lines.append("=" * 60)
    
    # Revenue
    lines.append("\nREVENUE")
    total_revenue = 0
    for name, amount in pnl["Revenue"].items():
        lines.append(f"  {name}: {format_currency(abs(amount))}")
        total_revenue += abs(amount)
    lines.append(f"  TOTAL REVENUE: {format_currency(total_revenue)}")
    
    # COGS
    lines.append("\nCOST OF GOODS SOLD")
    total_cogs = 0
    for name, amount in pnl["Cost of Goods Sold"].items():
        lines.append(f"  {name}: {format_currency(abs(amount))}")
        total_cogs += abs(amount)
    lines.append(f"  TOTAL COGS: {format_currency(total_cogs)}")
    
    # Gross Profit
    gross_profit = total_revenue - total_cogs
    lines.append(f"\nGROSS PROFIT: {format_currency(gross_profit)}")
    
    # Expenses
    lines.append("\nOPERATING EXPENSES")
    total_expenses = 0
    for name, amount in pnl["Expenses"].items():
        lines.append(f"  {name}: {format_currency(abs(amount))}")
        total_expenses += abs(amount)
    lines.append(f"  TOTAL EXPENSES: {format_currency(total_expenses)}")
    
    # Operating Income
    operating_income = gross_profit - total_expenses
    lines.append(f"\nOPERATING INCOME: {format_currency(operating_income)}")
    
    # Other Income/Expense
    total_other_income = sum(abs(v) for v in pnl["Other Income"].values())
    total_other_expense = sum(abs(v) for v in pnl["Other Expense"].values())
    
    if total_other_income or total_other_expense:
        lines.append("\nOTHER INCOME/EXPENSE")
        for name, amount in pnl["Other Income"].items():
            lines.append(f"  {name}: {format_currency(abs(amount))}")
        for name, amount in pnl["Other Expense"].items():
            lines.append(f"  {name}: ({format_currency(abs(amount))})")
    
    # Net Income
    net_income = operating_income + total_other_income - total_other_expense
    lines.append(f"\n{'=' * 60}")
    lines.append(f"NET INCOME: {format_currency(net_income)}")
    lines.append("=" * 60)
    
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python qbo_parser.py <path_to_gl.xlsx>")
        sys.exit(1)
    
    file_path = sys.argv[1]
    
    print(f"Parsing: {file_path}")
    accounts = parse_qbo_gl(file_path)
    
    print(f"\nFound {len(accounts)} accounts")
    
    pnl, balance_sheet = build_financial_statements(accounts)
    
    print(print_pnl(pnl))
