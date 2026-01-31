"""
GL Analyzer - Full Pipeline
Uses Chart of Accounts mapping for accurate classification
Preserves transaction detail for AI analysis
"""

import pandas as pd
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
import requests
import os


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
class Transaction:
    date: str
    account: str
    account_type: AccountType
    description: str
    amount: float
    vendor: str = ""


@dataclass
class AccountSummary:
    name: str
    account_type: AccountType
    total: float
    transaction_count: int
    transactions: List[Transaction]


def load_account_mapping(mapping_file: str) -> Dict[str, AccountType]:
    """Load the Chart of Accounts mapping"""
    with open(mapping_file, 'r') as f:
        data = json.load(f)
    return {k: AccountType(v) for k, v in data.items()}


def parse_gl_with_mapping(gl_file: str, account_map: Dict[str, AccountType]) -> Tuple[Dict[str, AccountSummary], List[Transaction]]:
    """
    Parse GL using CoA mapping for accurate classification
    Returns account summaries and all transactions
    
    Calculates account totals by summing individual transactions, not from
    "Total for" lines. This avoids double-counting when transactions post
    to both parent and child accounts.
    """
    df = pd.read_excel(gl_file, sheet_name=0, header=None)
    
    accounts = {}
    all_transactions = []
    current_account = None
    current_account_type = AccountType.UNKNOWN
    
    # Find header row (contains "Date", "Transaction Type", etc.)
    header_row = None
    for i, row in df.iterrows():
        if 'Date' in str(row.values):
            header_row = i
            break
    
    if header_row is None:
        header_row = 3  # Default QBO position
    
    # Parse accounts and transactions
    for i, row in df.iterrows():
        if i <= header_row:
            continue
            
        col0 = str(row[0]).strip() if pd.notna(row[0]) else ""
        col1 = str(row[1]).strip() if pd.notna(row[1]) else ""
        
        if col0 == "nan":
            col0 = ""
        if col1 == "nan":
            col1 = ""
        
        # Skip completely empty rows
        if not col0 and not col1:
            continue
        
        # Check if this is an account header (has value in col0, nothing meaningful in col1)
        if col0 and (pd.isna(row[1]) or col1 == "" or col1 == "Beginning Balance") and not col0.startswith("Total"):
            # This is an account name
            current_account = col0.strip()
            # Look up type in mapping
            current_account_type = account_map.get(current_account, AccountType.UNKNOWN)
            
            # Try smarter matching if exact match fails
            if current_account_type == AccountType.UNKNOWN:
                for mapped_name, mapped_type in account_map.items():
                    if mapped_name.endswith(":" + current_account) or mapped_name == current_account:
                        current_account_type = mapped_type
                        break
                if current_account_type == AccountType.UNKNOWN:
                    for mapped_name, mapped_type in account_map.items():
                        if mapped_name.lower().endswith(":" + current_account.lower()):
                            current_account_type = mapped_type
                            break
            
            if current_account not in accounts:
                accounts[current_account] = AccountSummary(
                    name=current_account,
                    account_type=current_account_type,
                    total=0,
                    transaction_count=0,
                    transactions=[]
                )
        
        # Skip all "Total for" lines - we'll calculate totals from transactions
        elif col0.startswith("Total for "):
            continue
        
        # Otherwise it might be a transaction row
        elif current_account and col1 and col1 != "nan" and col1 != "Beginning Balance":
            # Transaction row: Date in col1, Type in col2, etc.
            date = col1
            # Handle datetime objects
            if hasattr(row[1], 'strftime'):
                date = row[1].strftime('%m/%d/%Y')
            
            vendor = str(row[5]).strip() if len(row) > 5 and pd.notna(row[5]) else ""
            if vendor == "nan":
                vendor = ""
            description = str(row[6]).strip() if len(row) > 6 and pd.notna(row[6]) else ""
            if description == "nan":
                description = ""
            
            # Amount is typically in column 8
            amount = 0
            try:
                if len(row) > 8 and pd.notna(row[8]):
                    amount = float(row[8])
            except:
                pass
            
            if date and date != "nan":
                txn = Transaction(
                    date=date,
                    account=current_account,
                    account_type=current_account_type,
                    description=description,
                    amount=amount,
                    vendor=vendor
                )
                all_transactions.append(txn)
                
                if current_account in accounts:
                    accounts[current_account].transactions.append(txn)
                    accounts[current_account].transaction_count += 1
    
    # Calculate totals from transactions (not from "Total for" lines)
    for account_name, account in accounts.items():
        account.total = sum(txn.amount for txn in account.transactions)
    
    return accounts, all_transactions


def build_financial_statements(accounts: Dict[str, AccountSummary]) -> Tuple[Dict, Dict]:
    """Build P&L and Balance Sheet from account summaries"""
    
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
        # Skip summary/parent accounts
        if "with sub-accounts" in name:
            continue
            
        if account.account_type == AccountType.REVENUE:
            pnl["Revenue"][name] = account.total
        elif account.account_type == AccountType.COGS:
            pnl["Cost of Goods Sold"][name] = account.total
        elif account.account_type == AccountType.EXPENSE:
            pnl["Expenses"][name] = account.total
        elif account.account_type == AccountType.OTHER_INCOME:
            pnl["Other Income"][name] = account.total
        elif account.account_type == AccountType.OTHER_EXPENSE:
            pnl["Other Expense"][name] = account.total
        elif account.account_type == AccountType.ASSET:
            balance_sheet["Assets"][name] = account.total
        elif account.account_type == AccountType.LIABILITY:
            balance_sheet["Liabilities"][name] = account.total
        elif account.account_type == AccountType.EQUITY:
            balance_sheet["Equity"][name] = account.total
    
    return pnl, balance_sheet


def calculate_metrics(pnl: dict) -> dict:
    """Calculate key financial metrics"""
    
    total_revenue = sum(abs(v) for v in pnl["Revenue"].values())
    total_cogs = sum(abs(v) for v in pnl["Cost of Goods Sold"].values())
    total_expenses = sum(abs(v) for v in pnl["Expenses"].values())
    total_other_income = sum(abs(v) for v in pnl["Other Income"].values())
    total_other_expense = sum(abs(v) for v in pnl["Other Expense"].values())
    
    gross_profit = total_revenue - total_cogs
    gross_margin = (gross_profit / total_revenue * 100) if total_revenue else 0
    operating_income = gross_profit - total_expenses
    operating_margin = (operating_income / total_revenue * 100) if total_revenue else 0
    net_income = operating_income + total_other_income - total_other_expense
    net_margin = (net_income / total_revenue * 100) if total_revenue else 0
    
    top_expenses = sorted(pnl["Expenses"].items(), key=lambda x: abs(x[1]), reverse=True)[:5]
    
    return {
        "total_revenue": total_revenue,
        "total_cogs": total_cogs,
        "gross_profit": gross_profit,
        "gross_margin": gross_margin,
        "total_expenses": total_expenses,
        "operating_income": operating_income,
        "operating_margin": operating_margin,
        "net_income": net_income,
        "net_margin": net_margin,
        "total_other_income": total_other_income,
        "total_other_expense": total_other_expense,
        "top_expenses": top_expenses
    }


def find_unusual_transactions(transactions: List[Transaction], threshold_multiplier: float = 3.0) -> List[Transaction]:
    """Find transactions that are unusually large compared to average"""
    
    # Group by account
    by_account = {}
    for txn in transactions:
        if txn.account not in by_account:
            by_account[txn.account] = []
        by_account[txn.account].append(txn)
    
    unusual = []
    for account, txns in by_account.items():
        if len(txns) < 3:
            continue
        
        amounts = [abs(t.amount) for t in txns]
        avg = sum(amounts) / len(amounts)
        
        for txn in txns:
            if abs(txn.amount) > avg * threshold_multiplier and abs(txn.amount) > 500:
                unusual.append(txn)
    
    return unusual


def format_currency(amount: float) -> str:
    """Format as currency"""
    if amount < 0:
        return f"(${abs(amount):,.2f})"
    return f"${amount:,.2f}"


def generate_report(gl_file: str, mapping_file: str, api_key: str = None) -> str:
    """Generate full analysis report"""
    
    # Load mapping
    account_map = load_account_mapping(mapping_file)
    
    # Parse GL
    accounts, transactions = parse_gl_with_mapping(gl_file, account_map)
    
    # Build statements
    pnl, balance_sheet = build_financial_statements(accounts)
    
    # Calculate metrics
    metrics = calculate_metrics(pnl)
    
    # Find unusual transactions
    unusual = find_unusual_transactions(transactions)
    
    # Build report
    report = []
    report.append("=" * 70)
    report.append("📊 FINANCIAL ANALYSIS REPORT")
    report.append("=" * 70)
    
    report.append("\n📈 KEY METRICS")
    report.append("-" * 50)
    report.append(f"Revenue:          {format_currency(metrics['total_revenue'])}")
    report.append(f"Cost of Sales:    {format_currency(metrics['total_cogs'])}")
    report.append(f"Gross Profit:     {format_currency(metrics['gross_profit'])} ({metrics['gross_margin']:.1f}%)")
    report.append(f"Expenses:         {format_currency(metrics['total_expenses'])}")
    report.append(f"Operating Income: {format_currency(metrics['operating_income'])} ({metrics['operating_margin']:.1f}%)")
    report.append(f"Other Income:     {format_currency(metrics['total_other_income'])}")
    report.append(f"Other Expense:    {format_currency(metrics['total_other_expense'])}")
    report.append(f"Net Income:       {format_currency(metrics['net_income'])} ({metrics['net_margin']:.1f}%)")
    
    report.append("\n💰 TOP 5 EXPENSES")
    report.append("-" * 50)
    for name, amount in metrics['top_expenses']:
        pct = abs(amount) / metrics['total_expenses'] * 100 if metrics['total_expenses'] else 0
        report.append(f"  {name}: {format_currency(abs(amount))} ({pct:.1f}%)")
    
    if unusual:
        report.append("\n⚠️ UNUSUAL TRANSACTIONS")
        report.append("-" * 50)
        for txn in unusual[:10]:
            report.append(f"  {txn.date} | {txn.account} | {txn.vendor} | {format_currency(txn.amount)}")
    
    report.append("\n" + "=" * 70)
    report.append("📝 TRANSACTION SUMMARY")
    report.append("=" * 70)
    report.append(f"Total transactions analyzed: {len(transactions)}")
    report.append(f"Accounts with activity: {len([a for a in accounts.values() if a.transaction_count > 0])}")
    
    return "\n".join(report)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python gl_analyzer.py <general_ledger.xlsx> <account_mapping.json> [api_key]")
        print("\nFirst, create the mapping by running:")
        print("  python coa_parser.py <chart_of_accounts.xlsx>")
        sys.exit(1)
    
    gl_file = sys.argv[1]
    mapping_file = sys.argv[2]
    api_key = sys.argv[3] if len(sys.argv) > 3 else None
    
    print(generate_report(gl_file, mapping_file, api_key))
