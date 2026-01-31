"""
P&L Analyzer with AI Explanations
Takes parsed financial data and generates plain-English insights
"""

import os
import requests
from qbo_parser import parse_qbo_gl, build_financial_statements, format_currency


def calculate_metrics(pnl: dict) -> dict:
    """Calculate key financial metrics from P&L data"""
    
    # Totals
    total_revenue = sum(abs(v) for v in pnl["Revenue"].values())
    total_cogs = sum(abs(v) for v in pnl["Cost of Goods Sold"].values())
    total_expenses = sum(abs(v) for v in pnl["Expenses"].values())
    total_other_income = sum(abs(v) for v in pnl["Other Income"].values())
    total_other_expense = sum(abs(v) for v in pnl["Other Expense"].values())
    
    # Calculated metrics
    gross_profit = total_revenue - total_cogs
    gross_margin = (gross_profit / total_revenue * 100) if total_revenue else 0
    operating_income = gross_profit - total_expenses
    operating_margin = (operating_income / total_revenue * 100) if total_revenue else 0
    net_income = operating_income + total_other_income - total_other_expense
    net_margin = (net_income / total_revenue * 100) if total_revenue else 0
    
    # Top expenses
    all_expenses = {**pnl["Expenses"]}
    top_expenses = sorted(all_expenses.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
    
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
        "top_expenses": top_expenses,
        "expense_breakdown": pnl["Expenses"],
        "revenue_breakdown": pnl["Revenue"],
        "cogs_breakdown": pnl["Cost of Goods Sold"]
    }


def generate_ai_analysis(metrics: dict, api_key: str = None) -> str:
    """Generate AI-powered analysis of the financial metrics"""
    
    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
    
    if not api_key:
        return "⚠️ No API key provided. Set ANTHROPIC_API_KEY environment variable."
    
    # Build the prompt
    prompt = f"""You are a friendly financial advisor explaining a small business's Profit & Loss statement. 
Analyze these numbers and provide insights in plain English that a non-accountant can understand.

FINANCIAL SUMMARY:
- Total Revenue: {format_currency(metrics['total_revenue'])}
- Cost of Goods Sold: {format_currency(metrics['total_cogs'])}
- Gross Profit: {format_currency(metrics['gross_profit'])} ({metrics['gross_margin']:.1f}% margin)
- Operating Expenses: {format_currency(metrics['total_expenses'])}
- Operating Income: {format_currency(metrics['operating_income'])} ({metrics['operating_margin']:.1f}% margin)
- Other Income: {format_currency(metrics['total_other_income'])}
- Other Expenses: {format_currency(metrics['total_other_expense'])}
- Net Income: {format_currency(metrics['net_income'])} ({metrics['net_margin']:.1f}% margin)

TOP 5 EXPENSES:
{chr(10).join([f"- {name}: {format_currency(abs(amt))}" for name, amt in metrics['top_expenses']])}

Please provide:
1. A brief overall health assessment (2-3 sentences)
2. What's going well (2-3 bullet points)
3. Areas to watch or improve (2-3 bullet points)
4. One actionable recommendation

Keep the tone friendly and avoid jargon. Use simple language."""

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "content-type": "application/json",
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30
        )
        
        if response.status_code == 200:
            return response.json()["content"][0]["text"]
        else:
            return f"⚠️ API Error: {response.status_code} - {response.text}"
    
    except Exception as e:
        return f"⚠️ Error calling AI: {str(e)}"


def analyze_file(file_path: str, api_key: str = None) -> str:
    """Full analysis pipeline: parse, calculate, analyze"""
    
    # Parse the GL
    accounts = parse_qbo_gl(file_path)
    pnl, balance_sheet = build_financial_statements(accounts)
    
    # Calculate metrics
    metrics = calculate_metrics(pnl)
    
    # Build report
    report = []
    report.append("=" * 60)
    report.append("📊 FINANCIAL ANALYSIS REPORT")
    report.append("=" * 60)
    
    report.append("\n📈 KEY METRICS")
    report.append("-" * 40)
    report.append(f"Revenue:          {format_currency(metrics['total_revenue'])}")
    report.append(f"Gross Profit:     {format_currency(metrics['gross_profit'])} ({metrics['gross_margin']:.1f}%)")
    report.append(f"Operating Income: {format_currency(metrics['operating_income'])} ({metrics['operating_margin']:.1f}%)")
    report.append(f"Net Income:       {format_currency(metrics['net_income'])} ({metrics['net_margin']:.1f}%)")
    
    report.append("\n💰 TOP EXPENSES")
    report.append("-" * 40)
    for name, amount in metrics['top_expenses']:
        pct = abs(amount) / metrics['total_expenses'] * 100 if metrics['total_expenses'] else 0
        report.append(f"{name}: {format_currency(abs(amount))} ({pct:.1f}% of expenses)")
    
    report.append("\n" + "=" * 60)
    report.append("🤖 AI ANALYSIS")
    report.append("=" * 60)
    
    # Get AI analysis
    ai_analysis = generate_ai_analysis(metrics, api_key)
    report.append(ai_analysis)
    
    return "\n".join(report)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python analyzer.py <path_to_gl.xlsx> [api_key]")
        sys.exit(1)
    
    file_path = sys.argv[1]
    api_key = sys.argv[2] if len(sys.argv) > 2 else None
    
    print(analyze_file(file_path, api_key))
