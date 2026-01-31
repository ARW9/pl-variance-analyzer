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
import requests
import os

# Import AccountType from coa_parser to ensure single enum definition
from coa_parser import AccountType


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


def detect_date_format(df, date_col=1) -> bool:
    """
    Detect if dates are in day-first format (DD/MM/YYYY) or month-first (MM/DD/YYYY).
    Returns True if day-first format detected.
    """
    for i, row in df.iterrows():
        if i < 5:  # Skip header rows
            continue
        if pd.notna(row[date_col]):
            date_str = str(row[date_col]).strip()
            if '/' in date_str:
                parts = date_str.split('/')
                if len(parts) >= 2:
                    first_num = int(parts[0]) if parts[0].isdigit() else 0
                    # If first number > 12, it must be a day (DD/MM/YYYY)
                    if first_num > 12:
                        return True
    return False  # Default to MM/DD/YYYY


def find_gl_sheet(file_path: str) -> str:
    """Find the sheet containing General Ledger data"""
    xl = pd.ExcelFile(file_path)
    
    # Priority order for GL sheet names
    gl_keywords = ['general ledger', 'gl', 'ytd gl', 'historic gl', 'ledger']
    
    # First, try exact/partial matches
    for sheet in xl.sheet_names:
        sheet_lower = sheet.lower()
        for keyword in gl_keywords:
            if keyword in sheet_lower:
                return sheet
    
    # If no match found, check each sheet for GL-like structure
    for sheet in xl.sheet_names:
        try:
            df = pd.read_excel(file_path, sheet_name=sheet, header=None, nrows=20)
            # Look for GL-like headers (Date, Transaction Type, Amount)
            for i, row in df.iterrows():
                row_str = ' '.join([str(v).lower() for v in row.values if pd.notna(v)])
                if 'date' in row_str and ('transaction' in row_str or 'amount' in row_str):
                    return sheet
        except:
            pass
    
    # Default to first sheet
    return xl.sheet_names[0]


def parse_gl_with_mapping(gl_file: str, account_map: Dict[str, AccountType], date_format: str = "auto") -> Tuple[Dict[str, AccountSummary], List[Transaction]]:
    """
    Parse GL using CoA mapping for accurate classification
    Returns account summaries and all transactions
    
    Calculates account totals by summing individual transactions, not from
    "Total for" lines. This avoids double-counting when transactions post
    to both parent and child accounts.
    """
    # Find the correct sheet
    sheet_name = find_gl_sheet(gl_file)
    
    df = pd.read_excel(gl_file, sheet_name=sheet_name, header=None)
    
    # Determine date format
    if date_format == "dmy":
        dayfirst = True
    elif date_format == "mdy":
        dayfirst = False
    else:  # auto
        dayfirst = detect_date_format(df)
    
    accounts = {}
    all_transactions = []
    current_account = None
    current_account_type = AccountType.UNKNOWN
    
    # Find header row (contains "Date", "Transaction Type", etc.)
    header_row = None
    header_cols = {}  # Map column names to indices
    
    for i, row in df.iterrows():
        row_str = ' '.join([str(v).lower() for v in row.values if pd.notna(v)])
        if 'date' in row_str and ('type' in row_str or 'transaction' in row_str or 'amount' in row_str):
            header_row = i
            # Map column names to indices
            for j, val in enumerate(row.values):
                if pd.notna(val):
                    col_name = str(val).strip().lower()
                    header_cols[col_name] = j
            break
    
    if header_row is None:
        header_row = 3  # Default QBO position
    
    # Flexible column detection - find likely columns by name
    def find_col(names, default=None):
        """Find column index by trying multiple name variations"""
        for name in names:
            for col_name, idx in header_cols.items():
                if name in col_name:
                    return idx
        return default
    
    date_col = find_col(['date'], 1)
    vendor_col = find_col(['name', 'vendor', 'payee', 'customer'], 5)
    desc_col = find_col(['memo', 'description', 'desc'], 6)
    amount_col = find_col(['amount'], 8)
    
    # Also check for debit/credit columns if no amount column
    debit_col = find_col(['debit'], None)
    credit_col = find_col(['credit'], None)
    
    # Track parent accounts for nested sub-accounts
    parent_account_stack = []  # Stack to track parent hierarchy
    
    # Parse accounts and transactions
    for i, row in df.iterrows():
        if i <= header_row:
            continue
        
        try:
            col0 = str(row[0]).strip() if pd.notna(row[0]) else ""
            col1 = str(row[1]).strip() if pd.notna(row[1]) else ""
            
            if col0 == "nan":
                col0 = ""
            if col1 == "nan":
                col1 = ""
            
            # Skip completely empty rows
            if not col0 and not col1:
                continue
            
            # Handle "Total for X" lines - pop parent when we see total
            if col0.startswith("Total for "):
                total_name = col0.replace("Total for ", "").replace(" with sub-accounts", "").strip()
                # Pop matching parent from stack
                if parent_account_stack and parent_account_stack[-1].lower() == total_name.lower():
                    parent_account_stack.pop()
                elif parent_account_stack:
                    # Try to find and remove the matching parent
                    for idx, parent in enumerate(reversed(parent_account_stack)):
                        if parent.lower() == total_name.lower():
                            parent_account_stack = parent_account_stack[:len(parent_account_stack)-idx-1]
                            break
                continue
            
            # Check if this is an account header (has value in col0, nothing meaningful in col1)
            if col0 and (pd.isna(row[1]) or col1 == "" or col1 == "Beginning Balance") and not col0.startswith("Total"):
                # This is an account name - could be parent or sub-account
                raw_account_name = col0.strip()
                
                # Try to find as "Parent:SubAccount" first
                full_account_name = raw_account_name
                if parent_account_stack:
                    # Try with parent prefix
                    for depth in range(len(parent_account_stack), 0, -1):
                        parent_path = ":".join(parent_account_stack[:depth])
                        test_name = f"{parent_path}:{raw_account_name}"
                        if test_name in account_map:
                            full_account_name = test_name
                            break
                
                current_account = full_account_name
                # Look up type in mapping
                current_account_type = account_map.get(current_account, AccountType.UNKNOWN)
                
                # Try smarter matching if exact match fails
                if current_account_type == AccountType.UNKNOWN:
                    # Try stripping account number prefix (e.g., "1000 Rent" -> "Rent")
                    import re
                    stripped_name = re.sub(r'^\d+[\s\-]+', '', current_account).strip()
                    if stripped_name and stripped_name != current_account:
                        current_account_type = account_map.get(stripped_name, AccountType.UNKNOWN)
                    
                    # Try matching with parent:child format
                    if current_account_type == AccountType.UNKNOWN:
                        for mapped_name, mapped_type in account_map.items():
                            if mapped_name.endswith(":" + current_account) or mapped_name == current_account:
                                current_account_type = mapped_type
                                break
                    
                    # Try case-insensitive parent:child matching
                    if current_account_type == AccountType.UNKNOWN:
                        for mapped_name, mapped_type in account_map.items():
                            if mapped_name.lower().endswith(":" + current_account.lower()):
                                current_account_type = mapped_type
                                break
                    
                    # Try matching stripped name with parent:child format
                    if current_account_type == AccountType.UNKNOWN and stripped_name:
                        for mapped_name, mapped_type in account_map.items():
                            if mapped_name.endswith(":" + stripped_name) or mapped_name == stripped_name:
                                current_account_type = mapped_type
                                break
                            if mapped_name.lower().endswith(":" + stripped_name.lower()):
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
                
                # Track as potential parent (might have sub-accounts)
                # Check if this account has children in COA
                has_children = any(name.startswith(raw_account_name + ":") for name in account_map.keys())
                if has_children:
                    parent_account_stack = [raw_account_name]  # Reset to this as the new parent
                elif not parent_account_stack or not any(name.startswith(parent_account_stack[0] + ":" + raw_account_name) for name in account_map.keys()):
                    parent_account_stack = []  # Clear stack if this isn't a sub-account
            
            # Skip "Total" lines - already handled above for popping parent stack
            elif col0.startswith("Total "):
                continue
            
            # Otherwise it might be a transaction row
            elif current_account and col1 and col1 != "nan" and col1 != "Beginning Balance":
                # Get date from detected column
                date_val = row[date_col] if date_col and len(row) > date_col else row[1]
                date = ""
                if pd.notna(date_val):
                    # Always normalize to YYYY-MM-DD format
                    try:
                        if hasattr(date_val, 'strftime'):
                            date = date_val.strftime('%Y-%m-%d')
                        else:
                            # Parse string dates with pandas and normalize
                            # Use detected dayfirst setting
                            parsed = pd.to_datetime(date_val, dayfirst=dayfirst)
                            date = parsed.strftime('%Y-%m-%d')
                    except:
                        # Fallback: keep original string
                        date = str(date_val).strip()
                
                # Get vendor
                vendor = ""
                if vendor_col and len(row) > vendor_col and pd.notna(row[vendor_col]):
                    vendor = str(row[vendor_col]).strip()
                    if vendor == "nan":
                        vendor = ""
                
                # Get description
                description = ""
                if desc_col and len(row) > desc_col and pd.notna(row[desc_col]):
                    description = str(row[desc_col]).strip()
                    if description == "nan":
                        description = ""
                
                # Get amount - try multiple strategies
                amount = 0
                try:
                    # Strategy 1: Use detected amount column
                    if amount_col and len(row) > amount_col and pd.notna(row[amount_col]):
                        val = row[amount_col]
                        if isinstance(val, str):
                            val = val.replace(',', '').replace('$', '').replace('(', '-').replace(')', '')
                        amount = float(val)
                    # Strategy 2: Use debit/credit columns
                    elif debit_col is not None or credit_col is not None:
                        debit = 0
                        credit = 0
                        if debit_col and len(row) > debit_col and pd.notna(row[debit_col]):
                            val = row[debit_col]
                            if isinstance(val, str):
                                val = val.replace(',', '').replace('$', '')
                            debit = float(val) if val else 0
                        if credit_col and len(row) > credit_col and pd.notna(row[credit_col]):
                            val = row[credit_col]
                            if isinstance(val, str):
                                val = val.replace(',', '').replace('$', '')
                            credit = float(val) if val else 0
                        amount = debit - credit
                    # Strategy 3: Search last few columns for a number
                    else:
                        for col_idx in range(len(row) - 1, max(0, len(row) - 4), -1):
                            if pd.notna(row[col_idx]):
                                try:
                                    val = row[col_idx]
                                    if isinstance(val, str):
                                        val = val.replace(',', '').replace('$', '').replace('(', '-').replace(')', '')
                                    test_amount = float(val)
                                    if test_amount != 0:
                                        amount = test_amount
                                        break
                                except:
                                    pass
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
        except Exception as e:
            # Skip malformed rows but continue processing
            continue
    
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


def generate_report(gl_file: str, mapping_file: str, api_key: str = None, validate: bool = True) -> str:
    """Generate full analysis report with optional validation"""
    
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
    
    # Run validation to ensure parsing accuracy
    validation_result = None
    if validate:
        from validation import validate_gl_parsing, generate_validation_report
        validation_result = validate_gl_parsing(gl_file, accounts, account_map)
    
    # Build report
    report = []
    
    # Show validation status first if there are issues
    if validation_result and not validation_result.passed:
        report.append("⚠️" + "=" * 68)
        report.append("⚠️  VALIDATION WARNING - REVIEW BEFORE TRUSTING OUTPUT")
        report.append("⚠️" + "=" * 68)
        report.append(validation_result.summary)
        report.append("=" * 70 + "\n")
    
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
    
    # Add validation summary at end
    if validation_result:
        report.append("\n" + "=" * 70)
        report.append("🔍 VALIDATION STATUS")
        report.append("=" * 70)
        if validation_result.passed:
            report.append("✅ All account totals match GL source file")
        else:
            report.append(validation_result.summary)
    
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
