"""
P&L CSV Parser for QBO Profit & Loss by Month Export
Parses the native QBO P&L report - the source of truth for financials
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum
import re


class PLSection(Enum):
    INCOME = "Income"
    COGS = "Cost of Goods Sold"
    GROSS_PROFIT = "Gross Profit"
    EXPENSES = "Expenses"
    NET_OPERATING_INCOME = "Net Operating Income"
    OTHER_INCOME = "Other Income"
    OTHER_EXPENSE = "Other Expense"
    NET_OTHER_INCOME = "Net Other Income"
    NET_INCOME = "Net Income"
    UNKNOWN = "Unknown"


@dataclass
class PLLineItem:
    """A single line item from the P&L"""
    name: str
    section: PLSection
    parent: Optional[str]  # Parent account if this is a sub-account
    monthly_values: Dict[str, float]  # month -> amount
    total: float
    is_total_row: bool = False  # True if this is a "Total for X" row
    indent_level: int = 0


@dataclass
class PLStatement:
    """Parsed P&L statement with monthly data"""
    company_name: str
    date_range: str
    months: List[str]  # Column headers for months
    line_items: List[PLLineItem]
    
    # Calculated totals
    total_income: Dict[str, float] = field(default_factory=dict)
    total_cogs: Dict[str, float] = field(default_factory=dict)
    gross_profit: Dict[str, float] = field(default_factory=dict)
    total_expenses: Dict[str, float] = field(default_factory=dict)
    net_operating_income: Dict[str, float] = field(default_factory=dict)
    total_other_income: Dict[str, float] = field(default_factory=dict)
    total_other_expense: Dict[str, float] = field(default_factory=dict)
    net_income: Dict[str, float] = field(default_factory=dict)


def parse_currency(value: str) -> float:
    """Parse a currency string to float, handling various formats"""
    if pd.isna(value) or value == "" or value == "nan":
        return 0.0
    
    # Convert to string and clean
    val_str = str(value).strip()
    
    # Handle empty or dash values
    if val_str in ["", "-", "–", "—"]:
        return 0.0
    
    # Remove currency symbols and whitespace
    val_str = re.sub(r'[$€£¥]', '', val_str)
    val_str = val_str.replace(',', '').replace(' ', '')
    
    # Handle parentheses for negative numbers
    if val_str.startswith('(') and val_str.endswith(')'):
        val_str = '-' + val_str[1:-1]
    
    try:
        return float(val_str)
    except ValueError:
        return 0.0


def detect_section(row_name: str, current_section: PLSection) -> PLSection:
    """Detect which P&L section a row belongs to"""
    name_lower = row_name.lower().strip()
    
    # Section headers
    if name_lower == "income" or name_lower == "revenue":
        return PLSection.INCOME
    elif name_lower in ["cost of goods sold", "cost of sales", "cogs"]:
        return PLSection.COGS
    elif name_lower == "gross profit":
        return PLSection.GROSS_PROFIT
    elif name_lower == "expenses" or name_lower == "operating expenses":
        return PLSection.EXPENSES
    elif name_lower in ["net operating income", "operating income"]:
        return PLSection.NET_OPERATING_INCOME
    elif name_lower == "other income":
        return PLSection.OTHER_INCOME
    elif name_lower in ["other expense", "other expenses", "other costs"]:
        return PLSection.OTHER_EXPENSE
    elif name_lower in ["net other income", "total other income/expense"]:
        return PLSection.NET_OTHER_INCOME
    elif name_lower == "net income":
        return PLSection.NET_INCOME
    
    return current_section


def parse_pl_csv(file_path: str) -> PLStatement:
    """
    Parse a QBO Profit & Loss by Month CSV export
    
    Expected format:
    Row 1: "Profit and Loss"
    Row 2: Company name
    Row 3: Date range (e.g., "January 1-December 31, 2025")
    Row 4: (blank)
    Row 5: Headers - "Distribution account" | Month1 | Month2 | ... | Total
    Row 6+: Data rows with account names and monthly values
    
    Returns: PLStatement with all parsed data
    """
    # Read raw CSV
    df = pd.read_csv(file_path, header=None)
    
    # Extract header info
    company_name = ""
    date_range = ""
    header_row = 0
    
    for i, row in df.iterrows():
        row_str = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
        
        if row_str.lower() == "profit and loss":
            continue
        elif company_name == "" and row_str and "january" not in row_str.lower() and "distribution" not in row_str.lower():
            company_name = row_str
        elif "january" in row_str.lower() or "-" in row_str and any(m in row_str.lower() for m in ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]):
            date_range = row_str
        elif "distribution" in row_str.lower() or "account" in row_str.lower() or row_str == "":
            # Check if next cells are month names
            has_months = False
            for j in range(1, min(5, len(row))):
                cell = str(row.iloc[j]).strip().lower() if pd.notna(row.iloc[j]) else ""
                if any(m in cell for m in ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december", "total"]):
                    has_months = True
                    break
            if has_months:
                header_row = i
                break
    
    # Get column headers (months)
    header = df.iloc[header_row]
    months = []
    for j in range(1, len(header)):
        val = str(header.iloc[j]).strip() if pd.notna(header.iloc[j]) else ""
        if val and val.lower() != "nan":
            months.append(val)
    
    # Parse data rows
    line_items = []
    current_section = PLSection.UNKNOWN
    parent_stack = []  # Track parent accounts for indentation
    
    # Temp storage for QBO calculated values (captured during parsing, assigned after statement creation)
    qbo_total_income = {}
    qbo_total_cogs = {}
    qbo_total_expenses = {}
    qbo_gross_profit = {}
    qbo_net_operating_income = {}
    qbo_total_other_income = {}
    qbo_total_other_expense = {}
    qbo_net_income = {}
    
    for i in range(header_row + 1, len(df)):
        row = df.iloc[i]
        
        # Get account name
        account_name = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
        if not account_name or account_name == "nan":
            continue
        
        # Detect section changes
        new_section = detect_section(account_name, current_section)
        if new_section != current_section:
            current_section = new_section
            # Skip section header rows (they have no values)
            has_values = False
            for j in range(1, min(len(row), len(months) + 2)):
                if pd.notna(row.iloc[j]) and str(row.iloc[j]).strip() not in ["", "nan"]:
                    has_values = True
                    break
            if not has_values:
                continue
        
        # Skip footer/metadata rows
        if "accrual basis" in account_name.lower() or "cash basis" in account_name.lower():
            continue
        
        # Capture QBO's calculated rows as source of truth (don't add as line items)
        name_lower = account_name.lower()
        
        # Check for QBO total/summary rows
        is_qbo_total = name_lower in [
            "gross profit", "net operating income", "operating income", "net other income", "net income",
            "total for income", "total income", "total revenue",
            "total for cost of goods sold", "total cost of goods sold", "total cogs",
            "total for expenses", "total expenses", "total operating expenses",
            "total for other income", "total other income",
            "total for other expense", "total other expense", "total other expenses"
        ]
        
        if is_qbo_total:
            monthly_values = {}
            for j, month in enumerate(months):
                if j + 1 < len(row):
                    monthly_values[month] = parse_currency(row.iloc[j + 1])
            
            # Store QBO's values in temp variables (assigned to statement after creation)
            if name_lower == "gross profit":
                qbo_gross_profit = monthly_values
            elif name_lower in ["net operating income", "operating income"]:
                qbo_net_operating_income = monthly_values
            elif name_lower == "net income":
                qbo_net_income = monthly_values
            elif name_lower in ["total for income", "total income", "total revenue"]:
                qbo_total_income = monthly_values
            elif name_lower in ["total for cost of goods sold", "total cost of goods sold", "total cogs"]:
                qbo_total_cogs = monthly_values
            elif name_lower in ["total for expenses", "total expenses", "total operating expenses"]:
                qbo_total_expenses = monthly_values
            elif name_lower in ["total for other income", "total other income"]:
                qbo_total_other_income = monthly_values
            elif name_lower in ["total for other expense", "total other expense", "total other expenses", "total for other expenses"]:
                qbo_total_other_expense = monthly_values
            continue
        
        # Parse monthly values
        monthly_values = {}
        for j, month in enumerate(months):
            if j + 1 < len(row):
                monthly_values[month] = parse_currency(row.iloc[j + 1])
        
        # Detect if this is a total row
        is_total = account_name.lower().startswith("total for ") or account_name.lower().startswith("total ")
        
        # Detect indent level (number of leading spaces or tabs, or account number prefix)
        indent_level = 0
        original_name = str(row.iloc[0]) if pd.notna(row.iloc[0]) else ""
        leading_spaces = len(original_name) - len(original_name.lstrip())
        if leading_spaces > 0:
            indent_level = leading_spaces // 2  # Assume 2 spaces per indent
        
        # Determine parent account
        parent = None
        if indent_level > 0 and parent_stack:
            # Find parent at lower indent level
            for p_name, p_indent in reversed(parent_stack):
                if p_indent < indent_level:
                    parent = p_name
                    break
        
        # Update parent stack
        if not is_total:
            # Remove items at same or higher indent
            parent_stack = [(n, i) for n, i in parent_stack if i < indent_level]
            parent_stack.append((account_name, indent_level))
        
        # Get total from last column (usually "Total")
        total_val = monthly_values.get(months[-1], 0) if months else 0
        
        # Create line item
        item = PLLineItem(
            name=account_name,
            section=current_section,
            parent=parent,
            monthly_values=monthly_values,
            total=total_val,
            is_total_row=is_total,
            indent_level=indent_level
        )
        line_items.append(item)
    
    # Build the statement
    statement = PLStatement(
        company_name=company_name,
        date_range=date_range,
        months=months,
        line_items=line_items
    )
    
    # Assign QBO's values (source of truth from the P&L report)
    if qbo_total_income:
        statement.total_income = qbo_total_income
    if qbo_total_cogs:
        statement.total_cogs = qbo_total_cogs
    if qbo_total_expenses:
        statement.total_expenses = qbo_total_expenses
    if qbo_total_other_income:
        statement.total_other_income = qbo_total_other_income
    if qbo_total_other_expense:
        statement.total_other_expense = qbo_total_other_expense
    if qbo_gross_profit:
        statement.gross_profit = qbo_gross_profit
    if qbo_net_operating_income:
        statement.net_operating_income = qbo_net_operating_income
    if qbo_net_income:
        statement.net_income = qbo_net_income
    
    # Calculate section totals (only for values not already set from QBO)
    calculate_section_totals(statement)
    
    # Validate that totals match expected P&L relationships
    validation_errors = validate_pl_totals(statement)
    if validation_errors:
        # Log errors but don't fail - the QBO values are the source of truth
        print(f"P&L validation warnings: {validation_errors}")
    
    return statement


def calculate_section_totals(statement: PLStatement) -> None:
    """
    Calculate/validate totals for each P&L section by month.
    Uses QBO totals as source of truth if available, falls back to summing line items.
    """
    months = statement.months[:-1] if statement.months and statement.months[-1].lower() == "total" else statement.months
    all_months = months + ["Total"]
    
    # Only calculate from line items if we don't have QBO totals
    # (QBO totals are already set before this function is called)
    has_qbo_income = bool(statement.total_income)
    has_qbo_cogs = bool(statement.total_cogs)
    has_qbo_expenses = bool(statement.total_expenses)
    has_qbo_other_income = bool(statement.total_other_income)
    has_qbo_other_expense = bool(statement.total_other_expense)
    
    # If we don't have QBO totals, calculate from line items
    if not has_qbo_income or not has_qbo_expenses:
        calculated_income = {m: 0 for m in all_months}
        calculated_cogs = {m: 0 for m in all_months}
        calculated_expenses = {m: 0 for m in all_months}
        calculated_other_income = {m: 0 for m in all_months}
        calculated_other_expense = {m: 0 for m in all_months}
        
        for item in statement.line_items:
            if item.is_total_row:
                continue
            
            for month, value in item.monthly_values.items():
                if item.section == PLSection.INCOME:
                    calculated_income[month] = calculated_income.get(month, 0) + value
                elif item.section == PLSection.COGS:
                    calculated_cogs[month] = calculated_cogs.get(month, 0) + value
                elif item.section == PLSection.EXPENSES:
                    calculated_expenses[month] = calculated_expenses.get(month, 0) + value
                elif item.section == PLSection.OTHER_INCOME:
                    calculated_other_income[month] = calculated_other_income.get(month, 0) + value
                elif item.section == PLSection.OTHER_EXPENSE:
                    calculated_other_expense[month] = calculated_other_expense.get(month, 0) + value
        
        # Only use calculated values if QBO values aren't set
        if not has_qbo_income:
            statement.total_income = calculated_income
        if not has_qbo_cogs:
            statement.total_cogs = calculated_cogs
        if not has_qbo_expenses:
            statement.total_expenses = calculated_expenses
        if not has_qbo_other_income:
            statement.total_other_income = calculated_other_income
        if not has_qbo_other_expense:
            statement.total_other_expense = calculated_other_expense
    
    # Calculate derived totals ONLY if not already populated from QBO
    for month in all_months:
        # Gross Profit
        if month not in statement.gross_profit:
            statement.gross_profit[month] = statement.total_income.get(month, 0) - statement.total_cogs.get(month, 0)
        
        # Net Operating Income
        if month not in statement.net_operating_income:
            statement.net_operating_income[month] = statement.gross_profit.get(month, 0) - statement.total_expenses.get(month, 0)
        
        # Net Income
        if month not in statement.net_income:
            net_other = statement.total_other_income.get(month, 0) - statement.total_other_expense.get(month, 0)
            statement.net_income[month] = statement.net_operating_income.get(month, 0) + net_other


def validate_pl_totals(statement: PLStatement) -> list:
    """
    Validate that P&L totals match expected relationships.
    Returns list of validation errors (empty if all valid).
    """
    errors = []
    
    # Check for Total column
    total_key = "Total" if "Total" in statement.total_income else None
    if not total_key:
        return errors  # Can't validate without Total column
    
    # Get totals
    income = statement.total_income.get(total_key, 0)
    cogs = statement.total_cogs.get(total_key, 0)
    gross_profit = statement.gross_profit.get(total_key, 0)
    expenses = statement.total_expenses.get(total_key, 0)
    net_op_income = statement.net_operating_income.get(total_key, 0)
    other_income = statement.total_other_income.get(total_key, 0)
    other_expense = statement.total_other_expense.get(total_key, 0)
    net_income = statement.net_income.get(total_key, 0)
    
    # Tolerance for rounding (1 cent)
    tol = 0.01
    
    # Validate: Gross Profit = Income - COGS
    expected_gp = income - cogs
    if abs(gross_profit - expected_gp) > tol:
        errors.append(f"Gross Profit mismatch: got ${gross_profit:,.2f}, expected ${expected_gp:,.2f} (Income ${income:,.2f} - COGS ${cogs:,.2f})")
    
    # Validate: Net Operating Income = Gross Profit - Expenses
    expected_noi = gross_profit - expenses
    if abs(net_op_income - expected_noi) > tol:
        errors.append(f"Net Operating Income mismatch: got ${net_op_income:,.2f}, expected ${expected_noi:,.2f} (Gross Profit ${gross_profit:,.2f} - Expenses ${expenses:,.2f})")
    
    # Validate: Net Income = Net Operating Income + Other Income - Other Expense
    expected_ni = net_op_income + other_income - other_expense
    if abs(net_income - expected_ni) > tol:
        errors.append(f"Net Income mismatch: got ${net_income:,.2f}, expected ${expected_ni:,.2f}")
    
    return errors


def get_monthly_dataframe(statement: PLStatement, section: Optional[PLSection] = None) -> pd.DataFrame:
    """
    Convert statement to a DataFrame for display/analysis
    
    Args:
        statement: Parsed P&L statement
        section: Optional filter for specific section
    
    Returns:
        DataFrame with accounts as rows, months as columns
    """
    data = []
    
    for item in statement.line_items:
        if section and item.section != section:
            continue
        
        row = {"Account": item.name, "Section": item.section.value}
        for month in statement.months:
            row[month] = item.monthly_values.get(month, 0)
        
        data.append(row)
    
    return pd.DataFrame(data)


def get_summary_dict(statement: PLStatement) -> dict:
    """
    Get summary totals compatible with existing app format
    
    Returns dict matching the format from csv_parser.analyze_csv_files
    """
    # Get the "Total" column or sum all months
    total_key = "Total" if "Total" in statement.total_income else list(statement.total_income.keys())[-1] if statement.total_income else None
    
    if total_key:
        return {
            "totals": {
                "revenue": statement.total_income.get(total_key, 0),
                "cogs": statement.total_cogs.get(total_key, 0),
                "gross_profit": statement.gross_profit.get(total_key, 0),
                "expenses": statement.total_expenses.get(total_key, 0),
                "operating_income": statement.net_operating_income.get(total_key, 0),
                "other_income": statement.total_other_income.get(total_key, 0),
                "other_expense": statement.total_other_expense.get(total_key, 0),
                "net_income": statement.net_income.get(total_key, 0)
            },
            "monthly": {
                "income": statement.total_income,
                "cogs": statement.total_cogs,
                "gross_profit": statement.gross_profit,
                "expenses": statement.total_expenses,
                "net_operating_income": statement.net_operating_income,
                "other_income": statement.total_other_income,
                "other_expense": statement.total_other_expense,
                "net_income": statement.net_income
            },
            "company_name": statement.company_name,
            "date_range": statement.date_range,
            "months": statement.months
        }
    
    return {"totals": {}, "monthly": {}}


def get_variance_analysis(statement: PLStatement) -> List[dict]:
    """
    Analyze month-over-month variances for each line item
    
    Returns list of variance records with:
    - account name
    - section
    - monthly values
    - MoM changes
    - flags for significant variances
    """
    variances = []
    
    # Get month columns (excluding "Total")
    months = [m for m in statement.months if m.lower() != "total"]
    
    for item in statement.line_items:
        if item.is_total_row:
            continue
        
        record = {
            "account": item.name,
            "section": item.section.value,
            "parent": item.parent,
            "values": {},
            "changes": {},
            "pct_changes": {},
            "flags": []
        }
        
        prev_value = None
        for month in months:
            value = item.monthly_values.get(month, 0)
            record["values"][month] = value
            
            if prev_value is not None:
                change = value - prev_value
                record["changes"][month] = change
                
                # Calculate percentage change
                if prev_value != 0:
                    pct_change = (change / abs(prev_value)) * 100
                    record["pct_changes"][month] = pct_change
                    
                    # Flag significant changes (>50% or large absolute)
                    if abs(pct_change) > 50 and abs(change) > 500:
                        record["flags"].append({
                            "month": month,
                            "change": change,
                            "pct_change": pct_change,
                            "severity": "high" if abs(pct_change) > 100 else "medium"
                        })
                else:
                    record["pct_changes"][month] = float('inf') if change > 0 else float('-inf') if change < 0 else 0
            
            prev_value = value
        
        variances.append(record)
    
    return variances


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python pl_parser.py <profit_and_loss.csv>")
        sys.exit(1)
    
    statement = parse_pl_csv(sys.argv[1])
    summary = get_summary_dict(statement)
    
    print(f"\n=== {statement.company_name} ===")
    print(f"Period: {statement.date_range}")
    print(f"Months: {', '.join(statement.months)}")
    print(f"\n=== P&L Summary ===")
    print(f"Revenue:          ${summary['totals']['revenue']:,.2f}")
    print(f"COGS:             ${summary['totals']['cogs']:,.2f}")
    print(f"Gross Profit:     ${summary['totals']['gross_profit']:,.2f}")
    print(f"Expenses:         ${summary['totals']['expenses']:,.2f}")
    print(f"Operating Income: ${summary['totals']['operating_income']:,.2f}")
    print(f"Other Income:     ${summary['totals']['other_income']:,.2f}")
    print(f"Other Expense:    ${summary['totals']['other_expense']:,.2f}")
    print(f"Net Income:       ${summary['totals']['net_income']:,.2f}")
    
    print(f"\n=== Line Items ({len(statement.line_items)}) ===")
    for item in statement.line_items[:10]:
        indent = "  " * item.indent_level
        print(f"{indent}{item.section.value}: {item.name} = ${item.total:,.2f}")
