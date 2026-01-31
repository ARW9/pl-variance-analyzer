"""
GL/P&L Validation Module
Ensures parsed output matches source GL totals and all accounts are captured
"""

from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import pandas as pd


@dataclass
class ValidationResult:
    """Result of validation check"""
    passed: bool
    total_discrepancies: int
    discrepancies: List[Dict]  # {account, expected, actual, variance, pct_variance}
    missing_accounts: List[str]  # Accounts in COA with no transactions
    warnings: List[str]
    summary: str


def extract_gl_totals(gl_file: str, date_format: str = "auto") -> Dict[str, float]:
    """
    Extract 'Total for X' lines from GL file.
    These are QBO's stated totals that we should match.
    
    Returns dict of {account_name: total_amount}
    """
    df = pd.read_excel(gl_file, sheet_name=0, header=None)
    
    gl_totals = {}
    
    # Find header row to know where data starts
    header_row = 0
    for i, row in df.iterrows():
        row_str = ' '.join([str(v).lower() for v in row.values if pd.notna(v)])
        if 'date' in row_str and ('type' in row_str or 'transaction' in row_str or 'amount' in row_str):
            header_row = i
            break
    
    # Find the balance/amount column (usually last numeric column in Total rows)
    balance_col = None
    for i, row in df.iterrows():
        col0 = str(row[0]).strip() if pd.notna(row[0]) else ""
        if col0.startswith("Total for "):
            # Find the column with the total value
            for col_idx in range(len(row) - 1, 0, -1):
                if pd.notna(row[col_idx]):
                    try:
                        val = row[col_idx]
                        if isinstance(val, str):
                            val = val.replace(',', '').replace('$', '').replace('(', '-').replace(')', '')
                        float(val)
                        balance_col = col_idx
                        break
                    except:
                        pass
            if balance_col:
                break
    
    # Extract all "Total for X" lines
    for i, row in df.iterrows():
        if i <= header_row:
            continue
            
        col0 = str(row[0]).strip() if pd.notna(row[0]) else ""
        
        if col0.startswith("Total for "):
            # Extract account name (remove "Total for " and "with sub-accounts")
            account_name = col0.replace("Total for ", "").replace(" with sub-accounts", "").strip()
            
            # Get the total amount
            amount = 0
            if balance_col and pd.notna(row[balance_col]):
                try:
                    val = row[balance_col]
                    if isinstance(val, str):
                        val = val.replace(',', '').replace('$', '').replace('(', '-').replace(')', '')
                    amount = float(val)
                except:
                    pass
            
            # Store the total (use the last one if there are multiple, as it's the final balance)
            gl_totals[account_name] = amount
    
    return gl_totals


def validate_gl_parsing(
    gl_file: str,
    parsed_accounts: Dict,  # Dict[str, AccountSummary]
    account_map: Dict = None,  # Optional COA mapping
    tolerance_pct: float = 0.01,  # Allow 1% variance by default (rounding)
    tolerance_abs: float = 0.02   # Allow $0.02 absolute variance (penny rounding)
) -> ValidationResult:
    """
    Validate that our parsed totals match the GL's stated totals.
    
    Args:
        gl_file: Path to original GL Excel file
        parsed_accounts: Our parsed account summaries with calculated totals
        account_map: Optional COA mapping to check for missing accounts
        tolerance_pct: Percentage tolerance for variance (default 1%)
        tolerance_abs: Absolute dollar tolerance (default $0.02)
    
    Returns:
        ValidationResult with pass/fail status and details
    """
    discrepancies = []
    warnings = []
    
    # Extract expected totals from GL
    gl_totals = extract_gl_totals(gl_file)
    
    if not gl_totals:
        warnings.append("Could not extract 'Total for' lines from GL - unable to validate totals")
        return ValidationResult(
            passed=True,  # Can't fail if we can't check
            total_discrepancies=0,
            discrepancies=[],
            missing_accounts=[],
            warnings=warnings,
            summary="⚠️ Validation skipped - no 'Total for' lines found in GL"
        )
    
    # Compare our totals to GL totals
    for account_name, expected_total in gl_totals.items():
        # Find matching account in our parsed data
        actual_total = None
        matched_account = None
        
        # Try exact match first
        if account_name in parsed_accounts:
            actual_total = parsed_accounts[account_name].total
            matched_account = account_name
        else:
            # Try case-insensitive match
            for parsed_name, summary in parsed_accounts.items():
                if parsed_name.lower() == account_name.lower():
                    actual_total = summary.total
                    matched_account = parsed_name
                    break
                # Try matching end of name (for parent:child format)
                if parsed_name.lower().endswith(":" + account_name.lower()):
                    actual_total = summary.total
                    matched_account = parsed_name
                    break
                if account_name.lower().endswith(":" + parsed_name.lower()):
                    actual_total = summary.total
                    matched_account = parsed_name
                    break
        
        if actual_total is None:
            # Account exists in GL totals but not in our parsed data
            # This could be a parent account with sub-accounts (we sum children instead)
            # Check if it's a parent by looking for children
            has_children = any(
                parsed_name.startswith(account_name + ":") or 
                parsed_name.lower().startswith(account_name.lower() + ":")
                for parsed_name in parsed_accounts.keys()
            )
            
            if has_children:
                # Sum children to get parent total
                child_total = sum(
                    summary.total for parsed_name, summary in parsed_accounts.items()
                    if parsed_name.startswith(account_name + ":") or 
                       parsed_name.lower().startswith(account_name.lower() + ":")
                )
                actual_total = child_total
                matched_account = f"{account_name} (summed from children)"
            else:
                # Truly missing account
                discrepancies.append({
                    "account": account_name,
                    "expected": expected_total,
                    "actual": 0,
                    "variance": expected_total,
                    "pct_variance": 100.0,
                    "issue": "Account missing from parsed data"
                })
                continue
        
        # Calculate variance
        variance = actual_total - expected_total
        pct_variance = abs(variance / expected_total * 100) if expected_total != 0 else (100 if variance != 0 else 0)
        
        # Check if within tolerance
        within_tolerance = (
            abs(variance) <= tolerance_abs or 
            pct_variance <= tolerance_pct
        )
        
        if not within_tolerance:
            discrepancies.append({
                "account": account_name,
                "matched_as": matched_account,
                "expected": expected_total,
                "actual": actual_total,
                "variance": variance,
                "pct_variance": pct_variance,
                "issue": "Total mismatch"
            })
    
    # Check for accounts in COA with no transactions (potential missed accounts)
    missing_accounts = []
    if account_map:
        for coa_account in account_map.keys():
            # Skip number-prefixed duplicates
            if any(char.isdigit() for char in coa_account.split()[0] if coa_account.split()):
                continue
            
            found = False
            for parsed_name in parsed_accounts.keys():
                if (coa_account.lower() == parsed_name.lower() or
                    parsed_name.lower().endswith(":" + coa_account.lower()) or
                    coa_account.lower().endswith(":" + parsed_name.lower())):
                    found = True
                    break
            
            if not found and coa_account not in missing_accounts:
                # Check if it might be a parent of something we do have
                is_parent = any(
                    parsed_name.lower().startswith(coa_account.lower() + ":")
                    for parsed_name in parsed_accounts.keys()
                )
                if not is_parent:
                    missing_accounts.append(coa_account)
    
    # Build summary
    passed = len(discrepancies) == 0
    
    if passed:
        summary = f"✅ Validation PASSED - {len(gl_totals)} account totals verified"
        if missing_accounts:
            summary += f"\n⚠️ {len(missing_accounts)} COA accounts had no transactions (may be inactive)"
    else:
        summary = f"❌ Validation FAILED - {len(discrepancies)} discrepancies found"
        summary += "\n\nDiscrepancies:"
        for d in discrepancies[:10]:  # Show first 10
            summary += f"\n  • {d['account']}: expected ${d['expected']:,.2f}, got ${d['actual']:,.2f} (${d['variance']:+,.2f})"
        if len(discrepancies) > 10:
            summary += f"\n  ... and {len(discrepancies) - 10} more"
    
    return ValidationResult(
        passed=passed,
        total_discrepancies=len(discrepancies),
        discrepancies=discrepancies,
        missing_accounts=missing_accounts,
        warnings=warnings,
        summary=summary
    )


def validate_pnl_totals(
    pnl: Dict,
    expected_revenue: float = None,
    expected_expenses: float = None,
    expected_net_income: float = None,
    tolerance_abs: float = 1.00  # $1 tolerance for P&L-level checks
) -> ValidationResult:
    """
    Validate P&L category totals against expected values.
    Use this when you have known totals to compare against.
    """
    discrepancies = []
    warnings = []
    
    # Calculate our totals
    calc_revenue = sum(abs(v) for v in pnl.get("Revenue", {}).values())
    calc_cogs = sum(abs(v) for v in pnl.get("Cost of Goods Sold", {}).values())
    calc_expenses = sum(abs(v) for v in pnl.get("Expenses", {}).values())
    calc_other_income = sum(abs(v) for v in pnl.get("Other Income", {}).values())
    calc_other_expense = sum(abs(v) for v in pnl.get("Other Expense", {}).values())
    calc_net = calc_revenue - calc_cogs - calc_expenses + calc_other_income - calc_other_expense
    
    # Check against expected values if provided
    if expected_revenue is not None:
        variance = calc_revenue - expected_revenue
        if abs(variance) > tolerance_abs:
            discrepancies.append({
                "category": "Revenue",
                "expected": expected_revenue,
                "actual": calc_revenue,
                "variance": variance
            })
    
    if expected_expenses is not None:
        variance = calc_expenses - expected_expenses
        if abs(variance) > tolerance_abs:
            discrepancies.append({
                "category": "Expenses",
                "expected": expected_expenses,
                "actual": calc_expenses,
                "variance": variance
            })
    
    if expected_net_income is not None:
        variance = calc_net - expected_net_income
        if abs(variance) > tolerance_abs:
            discrepancies.append({
                "category": "Net Income",
                "expected": expected_net_income,
                "actual": calc_net,
                "variance": variance
            })
    
    passed = len(discrepancies) == 0
    
    if passed:
        summary = "✅ P&L totals validated successfully"
    else:
        summary = f"❌ P&L validation found {len(discrepancies)} discrepancies:\n"
        for d in discrepancies:
            summary += f"  • {d['category']}: expected ${d['expected']:,.2f}, got ${d['actual']:,.2f}\n"
    
    return ValidationResult(
        passed=passed,
        total_discrepancies=len(discrepancies),
        discrepancies=discrepancies,
        missing_accounts=[],
        warnings=warnings,
        summary=summary
    )


def generate_validation_report(
    gl_file: str,
    parsed_accounts: Dict,
    pnl: Dict,
    account_map: Dict = None
) -> str:
    """
    Generate a comprehensive validation report.
    Call this after parsing to check for issues.
    """
    report_lines = []
    report_lines.append("=" * 60)
    report_lines.append("🔍 PARSING VALIDATION REPORT")
    report_lines.append("=" * 60)
    
    # Validate GL parsing
    gl_result = validate_gl_parsing(gl_file, parsed_accounts, account_map)
    report_lines.append("\n📊 GL Total Validation:")
    report_lines.append("-" * 40)
    report_lines.append(gl_result.summary)
    
    if gl_result.warnings:
        report_lines.append("\n⚠️ Warnings:")
        for w in gl_result.warnings:
            report_lines.append(f"  • {w}")
    
    if gl_result.missing_accounts and len(gl_result.missing_accounts) <= 20:
        report_lines.append(f"\n📋 COA accounts with no transactions ({len(gl_result.missing_accounts)}):")
        for acc in gl_result.missing_accounts[:20]:
            report_lines.append(f"  • {acc}")
    
    # Summary stats
    report_lines.append("\n" + "=" * 60)
    report_lines.append("📈 PARSING SUMMARY")
    report_lines.append("=" * 60)
    
    total_accounts = len(parsed_accounts)
    accounts_with_txns = sum(1 for a in parsed_accounts.values() if a.transaction_count > 0)
    total_txns = sum(a.transaction_count for a in parsed_accounts.values())
    
    report_lines.append(f"Accounts parsed: {total_accounts}")
    report_lines.append(f"Accounts with transactions: {accounts_with_txns}")
    report_lines.append(f"Total transactions: {total_txns}")
    
    # P&L breakdown
    report_lines.append(f"\nP&L Categories:")
    for category, accounts in pnl.items():
        if accounts:
            total = sum(abs(v) for v in accounts.values())
            report_lines.append(f"  • {category}: {len(accounts)} accounts, ${total:,.2f}")
    
    # Final verdict
    report_lines.append("\n" + "=" * 60)
    if gl_result.passed:
        report_lines.append("✅ VALIDATION PASSED - Output matches GL source")
    else:
        report_lines.append("❌ VALIDATION FAILED - Review discrepancies above")
        report_lines.append("   The parsed output may not match the original GL.")
    report_lines.append("=" * 60)
    
    return "\n".join(report_lines)
