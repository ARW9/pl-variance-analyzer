"""
G&A Expense Analyzer - Deep Dive Module
Audits expenses, identifies cost drivers, provides contextual insights
"""

import os
import json
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from collections import defaultdict
from gl_analyzer import (
    load_account_mapping, parse_gl_with_mapping, build_financial_statements,
    AccountType, Transaction, AccountSummary, format_currency
)


@dataclass
class VendorAnalysis:
    """Analysis of spend by vendor"""
    name: str
    total_spend: float
    transaction_count: int
    avg_transaction: float
    accounts_used: List[str] = field(default_factory=list)
    months_active: int = 0
    is_recurring: bool = False


@dataclass
class ExpenseCategory:
    """Detailed expense category breakdown"""
    name: str
    total: float
    pct_of_total_expenses: float
    pct_of_revenue: float
    transaction_count: int
    avg_transaction: float
    top_vendors: List[Tuple[str, float]] = field(default_factory=list)
    monthly_trend: Dict[str, float] = field(default_factory=dict)
    is_fixed: bool = False
    is_discretionary: bool = True
    notes: List[str] = field(default_factory=list)
    # Variance analysis
    monthly_avg: float = 0
    monthly_std: float = 0
    coefficient_of_variation: float = 0  # std/mean - higher = more volatile
    is_consistent: bool = True  # True if CV < threshold
    consistency_expected: bool = False  # True for rent, insurance, etc.
    has_anomaly: bool = False  # Flagged if expected consistent but isn't


@dataclass
class GAAnalysis:
    """Complete G&A expense analysis"""
    total_ga_expenses: float
    ga_as_pct_of_revenue: float
    categories: List[ExpenseCategory]
    top_vendors: List[VendorAnalysis]
    fixed_costs: float
    variable_costs: float
    discretionary_costs: float
    essential_costs: float
    unknown_vendors_total: float
    unknown_vendors_count: int
    monthly_totals: Dict[str, float]
    insights: List[str]
    recommendations: List[str]


# Classification rules for common G&A expense types
# consistency_expected: True = should be same each month (rent, salary), False = naturally varies
EXPENSE_CLASSIFICATIONS = {
    # Fixed/Essential - Hard to reduce quickly, SHOULD BE CONSISTENT
    "rent": {"fixed": True, "discretionary": False, "consistent": True},
    "lease": {"fixed": True, "discretionary": False, "consistent": True},
    "insurance": {"fixed": True, "discretionary": False, "consistent": True},
    "depreciation": {"fixed": True, "discretionary": False, "consistent": True},
    "amortization": {"fixed": True, "discretionary": False, "consistent": True},
    "salary": {"fixed": True, "discretionary": False, "consistent": True},
    "wages": {"fixed": True, "discretionary": False, "consistent": False},  # Can vary with hours
    "payroll": {"fixed": True, "discretionary": False, "consistent": False},  # Can include bonuses
    "benefits": {"fixed": True, "discretionary": False, "consistent": True},
    "health": {"fixed": True, "discretionary": False, "consistent": True},
    "license": {"fixed": True, "discretionary": False, "consistent": True},
    "permit": {"fixed": True, "discretionary": False, "consistent": True},
    "interest": {"fixed": True, "discretionary": False, "consistent": True},  # Loan payments
    
    # Variable/Essential - Scales with business, EXPECTED TO VARY
    "utilities": {"fixed": False, "discretionary": False, "consistent": False},
    "telephone": {"fixed": False, "discretionary": False, "consistent": True},  # Usually fixed plan
    "internet": {"fixed": False, "discretionary": False, "consistent": True},  # Usually fixed plan
    "bank": {"fixed": False, "discretionary": False, "consistent": False},
    "merchant": {"fixed": False, "discretionary": False, "consistent": False},
    "processing": {"fixed": False, "discretionary": False, "consistent": False},
    "accounting": {"fixed": False, "discretionary": False, "consistent": True},  # Usually fixed fee
    "bookkeeping": {"fixed": False, "discretionary": False, "consistent": True},
    "legal": {"fixed": False, "discretionary": False, "consistent": False},
    "professional": {"fixed": False, "discretionary": False, "consistent": False},
    
    # Variable/Discretionary - Can be adjusted, EXPECTED TO VARY
    "advertising": {"fixed": False, "discretionary": True, "consistent": False},
    "marketing": {"fixed": False, "discretionary": True, "consistent": False},
    "promotion": {"fixed": False, "discretionary": True, "consistent": False},
    "travel": {"fixed": False, "discretionary": True, "consistent": False},
    "entertainment": {"fixed": False, "discretionary": True, "consistent": False},
    "meals": {"fixed": False, "discretionary": True, "consistent": False},
    "office supplies": {"fixed": False, "discretionary": True, "consistent": False},
    "supplies": {"fixed": False, "discretionary": True, "consistent": False},
    "training": {"fixed": False, "discretionary": True, "consistent": False},
    "education": {"fixed": False, "discretionary": True, "consistent": False},
    "subscriptions": {"fixed": False, "discretionary": True, "consistent": True},  # Should be fixed
    "software": {"fixed": False, "discretionary": True, "consistent": True},  # Usually fixed subscriptions
    "dues": {"fixed": False, "discretionary": True, "consistent": True},
    "membership": {"fixed": False, "discretionary": True, "consistent": True},
    "donations": {"fixed": False, "discretionary": True, "consistent": False},
    "gifts": {"fixed": False, "discretionary": True, "consistent": False},
    "shipping": {"fixed": False, "discretionary": False, "consistent": False},  # Varies with sales
    "freight": {"fixed": False, "discretionary": False, "consistent": False},
    "postage": {"fixed": False, "discretionary": False, "consistent": False},
}

# Coefficient of variation thresholds
CV_CONSISTENT_THRESHOLD = 0.15  # <15% CV = consistent
CV_VOLATILE_THRESHOLD = 0.50   # >50% CV = highly volatile, worth analyzing

# Industry benchmark ranges (G&A as % of revenue)
INDUSTRY_BENCHMARKS = {
    "retail": {"low": 15, "typical": 20, "high": 30},
    "ecommerce": {"low": 10, "typical": 15, "high": 25},
    "professional_services": {"low": 20, "typical": 30, "high": 45},
    "manufacturing": {"low": 10, "typical": 15, "high": 25},
    "construction": {"low": 12, "typical": 18, "high": 28},
    "restaurant": {"low": 25, "typical": 35, "high": 45},
    "healthcare": {"low": 15, "typical": 22, "high": 35},
    "technology": {"low": 20, "typical": 30, "high": 50},
    "default": {"low": 15, "typical": 25, "high": 40},
}

# Seasonality patterns
SEASONAL_FACTORS = {
    "Q1": {
        "notes": [
            "Post-holiday slowdown common in Jan-Feb for retail",
            "Tax preparation costs typically spike",
            "Insurance renewals often occur",
            "Annual subscriptions may renew",
        ],
        "typical_variance": -0.05  # 5% below annual average typical
    },
    "Q2": {
        "notes": [
            "Spring hiring season may increase HR costs",
            "Marketing spend often increases for summer prep",
            "Property tax bills may hit in Q2",
        ],
        "typical_variance": 0.0
    },
    "Q3": {
        "notes": [
            "Summer vacation payouts can increase payroll",
            "Back-to-school marketing for relevant industries",
            "Mid-year insurance audits may trigger adjustments",
        ],
        "typical_variance": 0.0
    },
    "Q4": {
        "notes": [
            "Holiday marketing spend typically highest",
            "Year-end bonuses increase payroll costs",
            "Accelerated purchasing for tax benefits common",
            "Inventory buildup increases carrying costs",
        ],
        "typical_variance": 0.10  # 10% above annual average typical
    }
}

# Current economic factors (update periodically)
ECONOMIC_CONTEXT_2025_2026 = {
    "inflation": {
        "rate": "3-4%",
        "impact": "General upward pressure on all costs. Vendor rate increases of 5-10% not unusual.",
        "watch": ["Insurance premiums", "Rent renewals", "Software subscriptions"]
    },
    "labor_market": {
        "status": "Tight",
        "impact": "Wage pressure persists. Benefits costs rising. Retention bonuses common.",
        "watch": ["Payroll", "Benefits", "Contractor rates"]
    },
    "interest_rates": {
        "direction": "Elevated, potential cuts in 2026",
        "impact": "Higher borrowing costs. Lease rates elevated. Credit card processing fees stable.",
        "watch": ["Interest expense", "Equipment leases", "Line of credit costs"]
    },
    "technology": {
        "trend": "AI adoption accelerating",
        "impact": "New software subscriptions common. May see efficiency gains offsetting cost.",
        "watch": ["Software subscriptions", "IT consulting", "Training costs"]
    },
    "supply_chain": {
        "status": "Largely normalized",
        "impact": "Shipping and logistics costs stabilizing. Still elevated from pre-2020.",
        "watch": ["Freight", "Shipping supplies", "Import duties"]
    }
}


def classify_expense(account_name: str) -> Tuple[bool, bool, bool]:
    """
    Classify an expense as fixed/variable, essential/discretionary, and consistency expected
    Returns (is_fixed, is_discretionary, consistency_expected)
    """
    name_lower = account_name.lower()
    
    for keyword, classification in EXPENSE_CLASSIFICATIONS.items():
        if keyword in name_lower:
            return (
                classification["fixed"],
                classification["discretionary"],
                classification.get("consistent", False)
            )
    
    # Default: variable, discretionary, not expected to be consistent
    return (False, True, False)


def calculate_variance_stats(monthly_amounts: Dict[str, float]) -> Tuple[float, float, float, bool]:
    """
    Calculate variance statistics for monthly expense data
    Returns (mean, std_dev, coefficient_of_variation, is_consistent)
    """
    import statistics
    
    if len(monthly_amounts) < 2:
        return (0, 0, 0, True)
    
    values = list(monthly_amounts.values())
    
    # Filter out zero months (no activity isn't variance)
    non_zero = [v for v in values if v > 0]
    if len(non_zero) < 2:
        return (0, 0, 0, True)
    
    mean = statistics.mean(non_zero)
    if mean == 0:
        return (0, 0, 0, True)
    
    std_dev = statistics.stdev(non_zero)
    cv = std_dev / mean  # Coefficient of variation
    
    is_consistent = cv < CV_CONSISTENT_THRESHOLD
    
    return (mean, std_dev, cv, is_consistent)


def analyze_vendors(transactions: List[Transaction]) -> List[VendorAnalysis]:
    """Analyze spending by vendor"""
    vendor_data = defaultdict(lambda: {
        "total": 0,
        "count": 0,
        "accounts": set(),
        "months": set()
    })
    
    for txn in transactions:
        if txn.account_type != AccountType.EXPENSE:
            continue
        
        vendor = txn.vendor.strip() if txn.vendor else "Unknown"
        if vendor in ("", "nan", "None"):
            vendor = "Unknown"
        
        vendor_data[vendor]["total"] += abs(txn.amount)
        vendor_data[vendor]["count"] += 1
        vendor_data[vendor]["accounts"].add(txn.account)
        
        # Extract month from date
        try:
            if "/" in txn.date:
                month = txn.date.split("/")[0] + "/" + txn.date.split("/")[2]
            else:
                month = txn.date[:7]  # YYYY-MM format
            vendor_data[vendor]["months"].add(month)
        except:
            pass
    
    # Build vendor analyses
    vendors = []
    for name, data in vendor_data.items():
        avg_txn = data["total"] / data["count"] if data["count"] > 0 else 0
        months_active = len(data["months"])
        is_recurring = months_active >= 3  # Active 3+ months = recurring
        
        vendors.append(VendorAnalysis(
            name=name,
            total_spend=data["total"],
            transaction_count=data["count"],
            avg_transaction=avg_txn,
            accounts_used=list(data["accounts"]),
            months_active=months_active,
            is_recurring=is_recurring
        ))
    
    # Sort by total spend
    vendors.sort(key=lambda x: x.total_spend, reverse=True)
    return vendors


def analyze_expense_categories(
    accounts: Dict[str, AccountSummary],
    transactions: List[Transaction],
    total_revenue: float
) -> List[ExpenseCategory]:
    """Deep analysis of each expense category with variance detection"""
    
    # Get total expenses for percentage calculation
    total_expenses = sum(
        abs(acc.total) for acc in accounts.values()
        if acc.account_type == AccountType.EXPENSE
    )
    
    categories = []
    
    # Group transactions by account
    txns_by_account = defaultdict(list)
    for txn in transactions:
        txns_by_account[txn.account].append(txn)
    
    for name, account in accounts.items():
        if account.account_type != AccountType.EXPENSE:
            continue
        if abs(account.total) < 0.01:
            continue
        
        account_txns = txns_by_account.get(name, [])
        
        # Calculate metrics
        pct_of_expenses = (abs(account.total) / total_expenses * 100) if total_expenses else 0
        pct_of_revenue = (abs(account.total) / total_revenue * 100) if total_revenue else 0
        avg_txn = abs(account.total) / len(account_txns) if account_txns else abs(account.total)
        
        # Classify (now includes consistency expectation)
        is_fixed, is_discretionary, consistency_expected = classify_expense(name)
        
        # Get top vendors for this category
        vendor_totals = defaultdict(float)
        for txn in account_txns:
            vendor = txn.vendor.strip() if txn.vendor else "Unknown"
            if vendor in ("", "nan", "None"):
                vendor = "Unknown"
            vendor_totals[vendor] += abs(txn.amount)
        
        top_vendors = sorted(vendor_totals.items(), key=lambda x: x[1], reverse=True)[:5]
        
        # Monthly trend
        monthly = defaultdict(float)
        for txn in account_txns:
            try:
                if "/" in txn.date:
                    parts = txn.date.split("/")
                    month_key = f"{parts[0]}/{parts[2]}"  # MM/YYYY
                else:
                    month_key = txn.date[:7]
                monthly[month_key] += abs(txn.amount)
            except:
                pass
        
        # Calculate variance statistics
        monthly_avg, monthly_std, cv, is_consistent = calculate_variance_stats(monthly)
        
        # Detect anomalies: expected to be consistent but isn't
        has_anomaly = consistency_expected and not is_consistent and cv > CV_CONSISTENT_THRESHOLD
        
        # Generate notes
        notes = []
        
        # ANOMALY: Expected consistent but shows high variance
        if has_anomaly:
            notes.append(f"🚨 ANOMALY: Should be consistent but varies significantly (CV: {cv:.0%})")
            if monthly_std > 0:
                notes.append(f"   Monthly range: ${monthly_avg - monthly_std:,.0f} - ${monthly_avg + monthly_std:,.0f}")
        
        if pct_of_revenue > 10:
            notes.append(f"⚠️ High: {pct_of_revenue:.1f}% of revenue")
        if len(top_vendors) > 0 and top_vendors[0][0] == "Unknown":
            unknown_pct = top_vendors[0][1] / abs(account.total) * 100 if account.total else 0
            if unknown_pct > 20:
                notes.append(f"⚠️ {unknown_pct:.0f}% has no vendor identified")
        
        categories.append(ExpenseCategory(
            name=name,
            total=abs(account.total),
            pct_of_total_expenses=pct_of_expenses,
            pct_of_revenue=pct_of_revenue,
            transaction_count=len(account_txns),
            avg_transaction=avg_txn,
            top_vendors=top_vendors,
            monthly_trend=dict(monthly),
            is_fixed=is_fixed,
            is_discretionary=is_discretionary,
            notes=notes,
            monthly_avg=monthly_avg,
            monthly_std=monthly_std,
            coefficient_of_variation=cv,
            is_consistent=is_consistent,
            consistency_expected=consistency_expected,
            has_anomaly=has_anomaly
        ))
    
    # Sort: anomalies first, then by volatility (high CV), then by total
    categories.sort(key=lambda x: (
        -int(x.has_anomaly),  # Anomalies first
        -x.coefficient_of_variation if not x.is_consistent else 0,  # Then volatile
        -x.total  # Then by size
    ))
    
    return categories


def get_current_quarter() -> str:
    """Get current quarter string"""
    month = datetime.now().month
    if month <= 3:
        return "Q1"
    elif month <= 6:
        return "Q2"
    elif month <= 9:
        return "Q3"
    else:
        return "Q4"


def generate_insights(analysis: GAAnalysis, industry: str = "default") -> List[str]:
    """Generate contextual insights about the expenses"""
    insights = []
    
    # Industry benchmark comparison
    benchmarks = INDUSTRY_BENCHMARKS.get(industry, INDUSTRY_BENCHMARKS["default"])
    ga_pct = analysis.ga_as_pct_of_revenue
    
    if ga_pct < benchmarks["low"]:
        insights.append(
            f"📊 G&A at {ga_pct:.1f}% of revenue is below typical range for the industry "
            f"({benchmarks['low']}-{benchmarks['high']}%). May indicate underinvestment "
            f"in infrastructure or very efficient operations."
        )
    elif ga_pct > benchmarks["high"]:
        insights.append(
            f"⚠️ G&A at {ga_pct:.1f}% of revenue is above typical range ({benchmarks['low']}-{benchmarks['high']}%). "
            f"Review discretionary spending and look for efficiency opportunities."
        )
    else:
        insights.append(
            f"✓ G&A at {ga_pct:.1f}% of revenue is within normal range ({benchmarks['low']}-{benchmarks['high']}%)."
        )
    
    # Fixed vs variable cost structure
    fixed_pct = (analysis.fixed_costs / analysis.total_ga_expenses * 100) if analysis.total_ga_expenses else 0
    if fixed_pct > 70:
        insights.append(
            f"📌 High fixed cost structure ({fixed_pct:.0f}% fixed). "
            f"Less flexibility to reduce costs in a downturn, but costs won't scale rapidly with growth."
        )
    elif fixed_pct < 30:
        insights.append(
            f"📊 Variable cost structure ({fixed_pct:.0f}% fixed). "
            f"Good flexibility, but costs may increase quickly as business grows."
        )
    
    # Unknown vendors concern
    if analysis.unknown_vendors_total > 0:
        unknown_pct = analysis.unknown_vendors_total / analysis.total_ga_expenses * 100
        if unknown_pct > 10:
            insights.append(
                f"⚠️ {format_currency(analysis.unknown_vendors_total)} ({unknown_pct:.0f}%) of expenses "
                f"have no vendor identified. This limits spend analysis and may indicate control gaps."
            )
    
    # Seasonal context
    quarter = get_current_quarter()
    seasonal = SEASONAL_FACTORS.get(quarter, {})
    if seasonal.get("notes"):
        insights.append(f"📅 {quarter} Seasonal Factors:")
        for note in seasonal["notes"][:2]:  # Top 2 most relevant
            insights.append(f"   • {note}")
    
    # Economic context
    insights.append("💹 Current Economic Factors:")
    for factor, data in list(ECONOMIC_CONTEXT_2025_2026.items())[:3]:
        insights.append(f"   • {factor.replace('_', ' ').title()}: {data['impact'][:80]}...")
    
    return insights


def generate_recommendations(analysis: GAAnalysis) -> List[str]:
    """Generate actionable recommendations"""
    recs = []
    
    # 1. ANOMALIES - Top priority, investigate immediately
    anomalies = [c for c in analysis.categories if c.has_anomaly]
    for cat in anomalies[:3]:  # Top 3 anomalies
        # Estimate potential overcharge/error recovery
        potential_overcharge = cat.monthly_std * 6  # ~6 months of excess variance
        recs.append({
            "priority": 0,  # Highest priority
            "savings": potential_overcharge,
            "text": f"🚨 INVESTIGATE {cat.name}: Expected {format_currency(cat.monthly_avg)}/month but varies "
                    f"by ±{format_currency(cat.monthly_std)}. Check for billing errors, rate changes, "
                    f"or missed payments. Potential recovery: {format_currency(potential_overcharge)}."
        })
    
    # 2. Unknown vendors
    if analysis.unknown_vendors_total > 5000:
        recs.append({
            "priority": 1,
            "savings": analysis.unknown_vendors_total * 0.15,
            "text": f"Implement vendor tracking: {format_currency(analysis.unknown_vendors_total)} in expenses "
                    f"has no vendor identified. Require receipts/invoices for all purchases. "
                    f"Poor tracking often indicates 10-15% waste in purchases."
        })
    
    # 3. Volatile discretionary expenses (optimization opportunities)
    volatile_discretionary = [c for c in analysis.categories 
                              if not c.is_consistent and c.is_discretionary and c.total > 3000]
    if volatile_discretionary:
        top = volatile_discretionary[0]
        recs.append({
            "priority": 2,
            "savings": top.total * 0.15,
            "text": f"Optimize {top.name}: {format_currency(top.total)} with {top.coefficient_of_variation:.0%} variance. "
                    f"High variability in discretionary spend suggests opportunity for better planning/budgeting. "
                    f"Set monthly targets and review overages."
        })
    
    # 4. Vendor concentration (negotiation opportunity)
    if analysis.top_vendors:
        top = analysis.top_vendors[0]
        if top.name != "Unknown" and top.total_spend > analysis.total_ga_expenses * 0.15:
            pct = top.total_spend / analysis.total_ga_expenses * 100
            recs.append({
                "priority": 3,
                "savings": top.total_spend * 0.05,
                "text": f"Negotiate with {top.name}: {format_currency(top.total_spend)} ({pct:.0f}% of G&A). "
                        f"Large concentrated spend creates negotiating leverage. "
                        f"Consider annual commitment for 5-10% discount."
            })
    
    # 5. Subscription audit
    software_cats = [c for c in analysis.categories 
                     if any(kw in c.name.lower() for kw in ["software", "subscription", "saas", "cloud"])]
    total_software = sum(c.total for c in software_cats)
    if total_software > 3000:
        recs.append({
            "priority": 4,
            "savings": total_software * 0.20,
            "text": f"Subscription audit: {format_currency(total_software)} in software/subscriptions. "
                    f"Review all active subscriptions, eliminate unused tools, "
                    f"consolidate overlapping services. Typical savings: 15-25%."
        })
    
    # 6. High-frequency small transactions
    high_freq_cats = [c for c in analysis.categories if c.transaction_count > 20 and c.avg_transaction < 100]
    if high_freq_cats:
        cat = high_freq_cats[0]
        recs.append({
            "priority": 5,
            "savings": cat.total * 0.05,
            "text": f"Consolidate {cat.name}: {cat.transaction_count} transactions averaging "
                    f"{format_currency(cat.avg_transaction)}. High-frequency small purchases often "
                    f"indicate lack of purchasing controls or bulk ordering opportunities."
        })
    
    # Sort by priority and format
    recs.sort(key=lambda x: x["priority"])
    
    formatted = []
    total_savings = 0
    for rec in recs[:6]:  # Top 6 recommendations
        total_savings += rec["savings"]
        formatted.append(rec["text"])
    
    if total_savings > 0:
        formatted.insert(0, f"💰 **Total Potential Annual Savings: {format_currency(total_savings)}**\n")
    
    return formatted


def parse_qbo_gl(gl_file: str, account_map: Dict[str, AccountType]) -> Tuple[Dict[str, AccountSummary], List[Transaction]]:
    """
    Parse standard QBO General Ledger export
    
    QBO GL format:
    - Row 0-3: Header info (Company name, Report name, Date range)
    - Row 4: Column headers (Date, Transaction Type, #, Adj, Name, Memo, Split, Amount, Balance)
    - Data rows: Account headers in col0, transactions have Date in col1
    - "Total for X" rows contain account totals
    """
    df = pd.read_excel(gl_file, sheet_name=0, header=None)
    
    accounts = {}
    all_transactions = []
    current_account = None
    current_account_type = AccountType.UNKNOWN
    
    # Find header row (contains "Date", "Transaction Type", etc.)
    header_row = 4  # Default QBO position
    for i, row in df.iterrows():
        row_values = [str(v) for v in row.values if pd.notna(v)]
        row_str = ' '.join(row_values)
        if 'Date' in row_str and 'Transaction' in row_str:
            header_row = i
            break
    
    for i, row in df.iterrows():
        if i <= header_row:
            continue
        
        col0 = str(row[0]).strip() if pd.notna(row[0]) else ""
        col1_raw = row[1]
        col1 = str(row[1]).strip() if pd.notna(row[1]) else ""
        
        # Skip empty rows
        if not col0 and not col1:
            continue
        
        # Skip "nan" strings
        if col0 == "nan":
            col0 = ""
        if col1 == "nan":
            col1 = ""
        
        # Check for "Total for X" - get the final balance
        if col0.startswith("Total for "):
            account_name = col0.replace("Total for ", "").strip()
            # Skip sub-account totals
            if "with sub-accounts" in account_name:
                continue
            if account_name in accounts:
                # Balance is in the last column (typically col 9)
                balance = None
                for c in [9, 8, -1]:
                    try:
                        idx = c if c >= 0 else len(row) + c
                        if idx < len(row) and pd.notna(row[idx]):
                            balance = float(row[idx])
                            break
                    except:
                        continue
                if balance is not None:
                    accounts[account_name].total = balance
            continue
        
        # Check if this is an account header
        # Account headers have: value in col0, nothing meaningful in col1 (or "Beginning Balance")
        if col0 and not col0.startswith("Total"):
            is_account_header = False
            
            if pd.isna(col1_raw) or col1 == "" or col1 == "Beginning Balance":
                is_account_header = True
            
            if is_account_header:
                current_account = col0
                current_account_type = account_map.get(current_account, AccountType.UNKNOWN)
                
                # Try smarter matching if exact match fails
                if current_account_type == AccountType.UNKNOWN:
                    # Priority 1: Account name matches end of CoA path (e.g., "Sales" matches "SALES INCOME:Sales")
                    for mapped_name, mapped_type in account_map.items():
                        if mapped_name.endswith(":" + current_account) or mapped_name == current_account:
                            current_account_type = mapped_type
                            break
                    
                    # Priority 2: CoA path ends with account name (case-insensitive)
                    if current_account_type == AccountType.UNKNOWN:
                        for mapped_name, mapped_type in account_map.items():
                            if mapped_name.lower().endswith(":" + current_account.lower()):
                                current_account_type = mapped_type
                                break
                    
                    # Priority 3: Account name is a significant part of CoA name (not just substring)
                    if current_account_type == AccountType.UNKNOWN:
                        for mapped_name, mapped_type in account_map.items():
                            # Split CoA path and check if account matches any segment
                            segments = mapped_name.split(":")
                            if current_account in segments or current_account.lower() in [s.lower() for s in segments]:
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
                continue
        
        # Transaction row: has a date in col1
        if current_account and col1 and col1 != "Beginning Balance":
            # Parse date
            date_str = col1
            if hasattr(col1_raw, 'strftime'):
                date_str = col1_raw.strftime('%m/%d/%Y')
            
            # Get transaction details
            vendor = str(row[5]).strip() if len(row) > 5 and pd.notna(row[5]) else ""
            if vendor == "nan":
                vendor = ""
            description = str(row[6]).strip() if len(row) > 6 and pd.notna(row[6]) else ""
            if description == "nan":
                description = ""
            
            # Amount is in column 8
            amount = 0
            try:
                if len(row) > 8 and pd.notna(row[8]):
                    amount = float(row[8])
            except:
                pass
            
            txn = Transaction(
                date=date_str,
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
    
    return accounts, all_transactions


def run_ga_analysis(
    gl_file: str,
    mapping_file: str,
    total_revenue: float = None,
    industry: str = "default"
) -> GAAnalysis:
    """
    Run complete G&A expense analysis
    
    Args:
        gl_file: Path to General Ledger Excel export (or Month End Close workbook)
        mapping_file: Path to account_mapping.json
        total_revenue: Total revenue for period (for % calculations)
        industry: Industry for benchmarking
    
    Returns:
        GAAnalysis object with complete analysis
    """
    # Load mapping
    account_map = load_account_mapping(mapping_file)
    
    # Parse the GL using QBO format parser
    accounts, transactions = parse_qbo_gl(gl_file, account_map)
    
    pnl, _ = build_financial_statements(accounts)
    
    # Get revenue if not provided
    if total_revenue is None:
        total_revenue = sum(abs(v) for v in pnl["Revenue"].values())
    
    # Total G&A
    total_ga = sum(abs(v) for v in pnl["Expenses"].values())
    ga_pct = (total_ga / total_revenue * 100) if total_revenue else 0
    
    # Analyze categories
    categories = analyze_expense_categories(accounts, transactions, total_revenue)
    
    # Analyze vendors
    vendors = analyze_vendors(transactions)
    
    # Calculate cost structure
    fixed_costs = sum(c.total for c in categories if c.is_fixed)
    variable_costs = total_ga - fixed_costs
    discretionary = sum(c.total for c in categories if c.is_discretionary)
    essential = total_ga - discretionary
    
    # Unknown vendors
    unknown = next((v for v in vendors if v.name == "Unknown"), None)
    unknown_total = unknown.total_spend if unknown else 0
    unknown_count = unknown.transaction_count if unknown else 0
    
    # Monthly totals
    monthly = defaultdict(float)
    for cat in categories:
        for month, amt in cat.monthly_trend.items():
            monthly[month] += amt
    
    # Build analysis object
    analysis = GAAnalysis(
        total_ga_expenses=total_ga,
        ga_as_pct_of_revenue=ga_pct,
        categories=categories,
        top_vendors=vendors[:15],
        fixed_costs=fixed_costs,
        variable_costs=variable_costs,
        discretionary_costs=discretionary,
        essential_costs=essential,
        unknown_vendors_total=unknown_total,
        unknown_vendors_count=unknown_count,
        monthly_totals=dict(monthly),
        insights=[],
        recommendations=[]
    )
    
    # Generate insights and recommendations
    analysis.insights = generate_insights(analysis, industry)
    analysis.recommendations = generate_recommendations(analysis)
    
    return analysis


def format_ga_report(analysis: GAAnalysis) -> str:
    """Format the G&A analysis as a text report"""
    lines = []
    
    lines.append("=" * 70)
    lines.append("📊 G&A EXPENSE ANALYSIS")
    lines.append("=" * 70)
    
    lines.append(f"\n💰 SUMMARY")
    lines.append("-" * 50)
    lines.append(f"Total G&A Expenses:      {format_currency(analysis.total_ga_expenses)}")
    lines.append(f"As % of Revenue:         {analysis.ga_as_pct_of_revenue:.1f}%")
    
    # Safe percentage calculation
    total = analysis.total_ga_expenses if analysis.total_ga_expenses > 0 else 1
    lines.append(f"Fixed Costs:             {format_currency(analysis.fixed_costs)} ({analysis.fixed_costs/total*100:.0f}%)")
    lines.append(f"Variable Costs:          {format_currency(analysis.variable_costs)} ({analysis.variable_costs/total*100:.0f}%)")
    lines.append(f"Essential Costs:         {format_currency(analysis.essential_costs)} ({analysis.essential_costs/total*100:.0f}%)")
    lines.append(f"Discretionary Costs:     {format_currency(analysis.discretionary_costs)} ({analysis.discretionary_costs/total*100:.0f}%)")
    
    if analysis.unknown_vendors_total > 0:
        lines.append(f"\n⚠️ Unidentified Vendors:  {format_currency(analysis.unknown_vendors_total)} ({analysis.unknown_vendors_count} transactions)")
    
    # Separate categories into groups
    anomalies = [c for c in analysis.categories if c.has_anomaly]
    volatile = [c for c in analysis.categories if not c.is_consistent and not c.has_anomaly and c.coefficient_of_variation > CV_VOLATILE_THRESHOLD]
    consistent = [c for c in analysis.categories if c.is_consistent and not c.has_anomaly]
    
    # 1. ANOMALIES - Expected consistent but varying (ALWAYS SHOW)
    if anomalies:
        lines.append(f"\n🚨 EXPENSE ANOMALIES (Expected Consistent)")
        lines.append("-" * 50)
        lines.append("These expenses SHOULD be the same each month but aren't:\n")
        for cat in anomalies:
            lines.append(f"  ⚠️ {cat.name}:")
            lines.append(f"    Total: {format_currency(cat.total)} | Monthly Avg: {format_currency(cat.monthly_avg)}")
            lines.append(f"    Variance: {cat.coefficient_of_variation:.0%} (should be <15%)")
            if cat.monthly_std > 0:
                lines.append(f"    Range: {format_currency(cat.monthly_avg - cat.monthly_std)} - {format_currency(cat.monthly_avg + cat.monthly_std)}")
            if cat.monthly_trend:
                sorted_months = sorted(cat.monthly_trend.items())
                min_month = min(sorted_months, key=lambda x: x[1])
                max_month = max(sorted_months, key=lambda x: x[1])
                lines.append(f"    Low: {min_month[0]} ({format_currency(min_month[1])}) | High: {max_month[0]} ({format_currency(max_month[1])})")
            if cat.top_vendors and cat.top_vendors[0][0] != "Unknown":
                lines.append(f"    Top Vendor: {cat.top_vendors[0][0]}")
            lines.append(f"    → INVESTIGATE: Why does this vary? Check for billing changes, errors, or missed payments.")
            lines.append("")
    
    # 2. VOLATILE EXPENSES - Worth analyzing (SHOW DETAIL)
    if volatile:
        lines.append(f"\n📊 VOLATILE EXPENSES (High Variance - Worth Reviewing)")
        lines.append("-" * 50)
        lines.append("These naturally vary but may have optimization opportunities:\n")
        for cat in volatile[:7]:  # Top 7 volatile
            lines.append(f"  {cat.name}:")
            lines.append(f"    Total: {format_currency(cat.total)} ({cat.pct_of_revenue:.1f}% of revenue)")
            lines.append(f"    Variance: {cat.coefficient_of_variation:.0%} | Transactions: {cat.transaction_count}")
            if cat.monthly_trend:
                sorted_months = sorted(cat.monthly_trend.items())
                trend_str = " → ".join([f"{m[0][:3]}: {format_currency(m[1])}" for m in sorted_months[-3:]])
                lines.append(f"    Recent: {trend_str}")
            if cat.top_vendors:
                vendors_str = ", ".join([f"{v[0]} ({format_currency(v[1])})" for v in cat.top_vendors[:3] if v[0] != "Unknown"])
                if vendors_str:
                    lines.append(f"    Vendors: {vendors_str}")
            for note in cat.notes:
                if "ANOMALY" not in note:
                    lines.append(f"    {note}")
            lines.append("")
    
    # 3. CONSISTENT EXPENSES - Just summarize (NO DETAIL NEEDED)
    if consistent:
        lines.append(f"\n✓ CONSISTENT EXPENSES (Predictable - No Analysis Needed)")
        lines.append("-" * 50)
        consistent_total = sum(c.total for c in consistent)
        lines.append(f"Total: {format_currency(consistent_total)} across {len(consistent)} categories")
        lines.append("These are stable month-to-month as expected:\n")
        for cat in sorted(consistent, key=lambda x: -x.total)[:8]:
            status = "✓" if cat.coefficient_of_variation < 0.10 else "~"
            lines.append(f"  {status} {cat.name}: {format_currency(cat.total)} (CV: {cat.coefficient_of_variation:.0%})")
        if len(consistent) > 8:
            lines.append(f"  ... and {len(consistent) - 8} more")
    
    lines.append(f"\n🏢 TOP VENDORS (All Expenses)")
    lines.append("-" * 50)
    for vendor in analysis.top_vendors[:10]:
        if vendor.name == "Unknown":
            continue
        recurring = "🔄" if vendor.is_recurring else "  "
        lines.append(f"  {recurring} {vendor.name}: {format_currency(vendor.total_spend)} ({vendor.transaction_count} transactions)")
    
    lines.append(f"\n📅 MONTHLY TREND")
    lines.append("-" * 50)
    for month, total in sorted(analysis.monthly_totals.items()):
        bar_len = int(total / max(analysis.monthly_totals.values()) * 30) if analysis.monthly_totals else 0
        lines.append(f"  {month}: {format_currency(total)} {'█' * bar_len}")
    
    lines.append(f"\n💡 INSIGHTS")
    lines.append("-" * 50)
    for insight in analysis.insights:
        lines.append(f"  {insight}")
    
    lines.append(f"\n✅ RECOMMENDATIONS")
    lines.append("-" * 50)
    for i, rec in enumerate(analysis.recommendations, 1):
        if rec.startswith("💰"):
            lines.append(f"\n{rec}")
        else:
            lines.append(f"\n  {i}. {rec}")
    
    lines.append("\n" + "=" * 70)
    
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python expense_analyzer.py <general_ledger.xlsx> <account_mapping.json> [revenue] [industry]")
        print("\nIndustry options: retail, ecommerce, professional_services, manufacturing,")
        print("                  construction, restaurant, healthcare, technology, default")
        sys.exit(1)
    
    gl_file = sys.argv[1]
    mapping_file = sys.argv[2]
    revenue = float(sys.argv[3]) if len(sys.argv) > 3 else None
    industry = sys.argv[4] if len(sys.argv) > 4 else "default"
    
    analysis = run_ga_analysis(gl_file, mapping_file, revenue, industry)
    print(format_ga_report(analysis))
