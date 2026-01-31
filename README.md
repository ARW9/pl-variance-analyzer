# P&L Variance Analyzer

Instantly analyze your QuickBooks Online Profit & Loss statement with monthly trends, variance detection, and expense breakdowns.

## How to Export from QBO

### Profit & Loss by Month (Required)

1. Go to **Reports** → **Profit and Loss**
2. Click **Customize**
3. Under **Display**, select **Months** for columns
4. Set your date range (e.g., January 1 - December 31, 2025)
5. Click **Run Report**
6. Click **Export** → **Export to CSV**

### General Ledger (Optional)

For transaction-level drill-down:

1. Go to **Reports** → **General Ledger**
2. Set your date range
3. Click **Run Report**
4. Click **Export** → **Export to CSV**

## Features

- **Accurate Financials**: Uses QBO's native P&L report as source of truth
- **Monthly Trends**: Visualize revenue and net income over time
- **Variance Detection**: Automatic flagging of significant month-over-month changes
- **Expense Breakdown**: See where your money is going
- **Full P&L Table**: Complete statement with all accounts and months

## Live App

https://pl-variance-analyzer.streamlit.app

## Local Development

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Files

- `app.py` - Main Streamlit application
- `pl_parser.py` - P&L CSV parser (source of truth)
- `auth.py` - Authentication and paywall logic
- `csv_parser.py` - Legacy GL+COA parser (deprecated)
