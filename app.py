"""
P&L Variance Analyzer - Web App
Upload GL + CoA exports, get instant expense analysis
"""

import streamlit as st
import pandas as pd
import tempfile
import os
from pathlib import Path

# Import our analyzers
from coa_parser import parse_qbo_coa, AccountType
from expense_analyzer import (
    run_ga_analysis, format_currency, 
    CV_CONSISTENT_THRESHOLD, CV_VOLATILE_THRESHOLD,
    INDUSTRY_BENCHMARKS, GAAnalysis, ExpenseCategory, VendorAnalysis
)

# Page config
st.set_page_config(
    page_title="P&L Variance Analyzer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS - Red and Black theme
st.markdown("""
<style>
    /* Main theme colors */
    :root {
        --primary: #dc2626;
        --primary-dark: #b91c1c;
        --primary-light: #ef4444;
        --dark: #171717;
        --dark-light: #262626;
        --gray: #525252;
        --gray-light: #a3a3a3;
        --light: #fafafa;
        --white: #ffffff;
    }
    
    /* Header styling */
    .main-header {
        font-size: 2.8rem;
        font-weight: 800;
        background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #525252;
        margin-bottom: 2rem;
    }
    
    /* Cards */
    .metric-card {
        background: linear-gradient(135deg, #171717 0%, #262626 100%);
        border-radius: 12px;
        padding: 1.5rem;
        border-left: 4px solid #dc2626;
        color: white;
    }
    .anomaly-card {
        background: linear-gradient(135deg, #450a0a 0%, #7f1d1d 100%);
        border-radius: 12px;
        padding: 1.5rem;
        border-left: 4px solid #dc2626;
        margin-bottom: 1rem;
        color: white;
    }
    .anomaly-card h4 {
        color: #fecaca;
        margin-bottom: 0.5rem;
    }
    .volatile-card {
        background: linear-gradient(135deg, #171717 0%, #262626 100%);
        border-radius: 12px;
        padding: 1.5rem;
        border-left: 4px solid #f59e0b;
        margin-bottom: 1rem;
        color: white;
    }
    .consistent-card {
        background: linear-gradient(135deg, #171717 0%, #262626 100%);
        border-radius: 12px;
        padding: 1.5rem;
        border-left: 4px solid #22c55e;
        color: white;
    }
    .info-card {
        background: linear-gradient(135deg, #171717 0%, #262626 100%);
        border-radius: 12px;
        padding: 1.5rem;
        border: 1px solid #404040;
        color: white;
        margin-bottom: 1rem;
    }
    .info-card h4 {
        color: #dc2626;
        margin-bottom: 0.75rem;
    }
    
    /* Demo card */
    .demo-section {
        background: linear-gradient(135deg, #0f0f0f 0%, #1a1a1a 100%);
        border-radius: 16px;
        padding: 2rem;
        border: 1px solid #333;
        margin: 1rem 0;
    }
    .demo-badge {
        background: #dc2626;
        color: white;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .demo-metric {
        background: #262626;
        border-radius: 8px;
        padding: 1rem;
        text-align: center;
        border-left: 3px solid #dc2626;
    }
    .demo-metric-value {
        font-size: 1.5rem;
        font-weight: 700;
        color: #dc2626;
    }
    .demo-metric-label {
        font-size: 0.85rem;
        color: #a3a3a3;
        margin-top: 0.25rem;
    }
    .demo-anomaly {
        background: linear-gradient(135deg, #450a0a 0%, #5c1010 100%);
        border-radius: 8px;
        padding: 1rem;
        border-left: 3px solid #dc2626;
        margin-bottom: 0.75rem;
    }
    .demo-anomaly-title {
        color: #fecaca;
        font-weight: 600;
        margin-bottom: 0.25rem;
    }
    .demo-anomaly-detail {
        color: #a3a3a3;
        font-size: 0.85rem;
    }
    
    /* Sidebar - Light theme for readability */
    [data-testid="stSidebar"] {
        background: #f8f8f8;
    }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] span,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] .stSelectbox label,
    [data-testid="stSidebar"] h1, 
    [data-testid="stSidebar"] h2, 
    [data-testid="stSidebar"] h3 {
        color: #171717 !important;
    }
    [data-testid="stSidebar"] [data-testid="stFileUploader"] label {
        color: #171717 !important;
    }
    [data-testid="stSidebar"] .stFileUploader [data-testid="stMarkdownContainer"] {
        color: #525252 !important;
    }
    [data-testid="stSidebar"] hr {
        border-color: #e5e5e5;
    }
    
    /* Buttons */
    .stButton > button {
        background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%);
        color: white;
        border: none;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
        box-shadow: 0 4px 15px rgba(220, 38, 38, 0.4);
    }
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 1rem;
        background: #171717;
        padding: 0.5rem;
        border-radius: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        font-weight: 600;
        color: #a3a3a3;
        background: transparent;
    }
    .stTabs [aria-selected="true"] {
        color: #dc2626 !important;
        background: #262626 !important;
        border-radius: 6px;
    }
    
    /* Expanders */
    .streamlit-expanderHeader {
        background: #f5f5f5;
        color: #171717 !important;
        border-radius: 8px;
    }
    
    /* FAQ styling */
    .faq-question {
        color: #dc2626;
        font-weight: 700;
        font-size: 1.1rem;
        margin-bottom: 0.5rem;
    }
    .faq-answer {
        color: #525252;
        line-height: 1.7;
        margin-bottom: 1.5rem;
    }
    
    /* Video guide cards */
    .video-card {
        background: #171717;
        border-radius: 12px;
        padding: 1.5rem;
        text-align: center;
        border: 2px solid #262626;
        transition: all 0.3s ease;
    }
    .video-card:hover {
        border-color: #dc2626;
        transform: translateY(-2px);
    }
    .video-card h4 {
        color: white;
        margin: 1rem 0 0.5rem 0;
    }
    .video-card p {
        color: #a3a3a3;
        font-size: 0.9rem;
    }
    .step-number {
        background: #dc2626;
        color: white;
        width: 32px;
        height: 32px;
        border-radius: 50%;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-weight: 700;
        margin-right: 0.5rem;
    }
    
    /* Metrics */
    [data-testid="stMetricValue"] {
        color: #dc2626;
    }
    
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# Header
st.markdown('<p class="main-header">📊 P&L Variance Analyzer</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Upload your QuickBooks exports • Identify cost anomalies • Get actionable insights</p>', unsafe_allow_html=True)

# Sidebar for file uploads
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/analytics.png", width=60)
    st.header("Upload Files")
    
    coa_file = st.file_uploader(
        "Chart of Accounts (.xlsx)",
        type=['xlsx'],
        help="Export from QBO: Settings → Chart of Accounts → Run Report → Export to Excel"
    )
    
    gl_file = st.file_uploader(
        "General Ledger (.xlsx)",
        type=['xlsx'],
        help="Export from QBO: Reports → General Ledger → Export to Excel"
    )
    
    st.divider()
    
    industry = st.selectbox(
        "Industry (for benchmarks)",
        options=list(INDUSTRY_BENCHMARKS.keys()),
        index=list(INDUSTRY_BENCHMARKS.keys()).index("default"),
        format_func=lambda x: x.replace("_", " ").title()
    )
    
    analyze_btn = st.button("🔍 Analyze", type="primary", use_container_width=True)


def save_uploaded_file(uploaded_file) -> str:
    """Save uploaded file to temp location and return path"""
    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
        tmp.write(uploaded_file.getvalue())
        return tmp.name


def run_analysis(coa_path: str, gl_path: str, industry: str):
    """Run the full analysis pipeline"""
    # Parse CoA to create mapping
    account_map = parse_qbo_coa(coa_path)
    
    # Save mapping to temp file
    import json
    mapping_path = tempfile.mktemp(suffix='.json')
    with open(mapping_path, 'w') as f:
        json.dump({k: v.value for k, v in account_map.items()}, f)
    
    # Run analysis
    analysis = run_ga_analysis(gl_path, mapping_path, industry=industry)
    
    # Cleanup
    os.unlink(mapping_path)
    
    return analysis, account_map


# Create mock demo data
def get_demo_analysis():
    """Generate mock analysis for demo preview"""
    # Mock expense categories
    demo_categories = [
        ExpenseCategory(
            name="Rent Expense",
            total=54000,
            pct_of_total_expenses=18.2,
            pct_of_revenue=6.4,
            transaction_count=12,
            avg_transaction=4500,
            top_vendors=[("Westfield Properties", 54000)],
            monthly_trend={"01/2025": 4500, "02/2025": 4500, "03/2025": 6200, "04/2025": 4500, "05/2025": 2800, "06/2025": 4500, "07/2025": 4500, "08/2025": 5100, "09/2025": 4500, "10/2025": 4500, "11/2025": 4500, "12/2025": 3900},
            is_fixed=True,
            is_discretionary=False,
            monthly_avg=4500,
            monthly_std=800,
            coefficient_of_variation=0.47,
            is_consistent=False,
            consistency_expected=True,
            has_anomaly=True
        ),
        ExpenseCategory(
            name="Insurance Premium",
            total=14400,
            pct_of_total_expenses=4.8,
            pct_of_revenue=1.7,
            transaction_count=12,
            avg_transaction=1200,
            top_vendors=[("StateFarm Business", 14400)],
            monthly_trend={"01/2025": 1200, "02/2025": 1200, "03/2025": 1200, "04/2025": 1200, "05/2025": 1200, "06/2025": 1650, "07/2025": 1650, "08/2025": 1650, "09/2025": 890, "10/2025": 890, "11/2025": 890, "12/2025": 890},
            is_fixed=True,
            is_discretionary=False,
            monthly_avg=1200,
            monthly_std=320,
            coefficient_of_variation=0.38,
            is_consistent=False,
            consistency_expected=True,
            has_anomaly=True
        ),
        ExpenseCategory(
            name="Marketing & Advertising",
            total=72000,
            pct_of_total_expenses=24.3,
            pct_of_revenue=8.5,
            transaction_count=89,
            avg_transaction=809,
            top_vendors=[("Google Ads", 38000), ("Facebook Ads", 24000), ("Mailchimp", 6000), ("Canva Pro", 4000)],
            monthly_trend={"01/2025": 4200, "02/2025": 5800, "03/2025": 6200, "04/2025": 5500, "05/2025": 7200, "06/2025": 6800, "07/2025": 5200, "08/2025": 6100, "09/2025": 7800, "10/2025": 8200, "11/2025": 4500, "12/2025": 4500},
            is_fixed=False,
            is_discretionary=True,
            monthly_avg=6000,
            monthly_std=1200,
            coefficient_of_variation=0.72,
            is_consistent=False,
            consistency_expected=False,
            has_anomaly=False
        ),
        ExpenseCategory(
            name="Software Subscriptions",
            total=18600,
            pct_of_total_expenses=6.3,
            pct_of_revenue=2.2,
            transaction_count=36,
            avg_transaction=517,
            top_vendors=[("Salesforce", 7200), ("Slack", 3600), ("Zoom", 2400), ("Adobe CC", 2400), ("QuickBooks", 1800)],
            monthly_trend={"01/2025": 1550, "02/2025": 1550, "03/2025": 1550, "04/2025": 1550, "05/2025": 1550, "06/2025": 1550, "07/2025": 1550, "08/2025": 1550, "09/2025": 1550, "10/2025": 1550, "11/2025": 1550, "12/2025": 1550},
            is_fixed=False,
            is_discretionary=True,
            monthly_avg=1550,
            monthly_std=0,
            coefficient_of_variation=0.0,
            is_consistent=True,
            consistency_expected=True,
            has_anomaly=False
        ),
        ExpenseCategory(
            name="Payroll",
            total=420000,
            pct_of_total_expenses=49.6,
            pct_of_revenue=35.0,
            transaction_count=24,
            avg_transaction=35000,
            top_vendors=[],
            monthly_trend={"01/2025": 35000, "02/2025": 35000, "03/2025": 35000, "04/2025": 35000, "05/2025": 35000, "06/2025": 35000, "07/2025": 35000, "08/2025": 35000, "09/2025": 35000, "10/2025": 35000, "11/2025": 35000, "12/2025": 35000},
            is_fixed=True,
            is_discretionary=False,
            monthly_avg=35000,
            monthly_std=0,
            coefficient_of_variation=0.0,
            is_consistent=True,
            consistency_expected=False,
            has_anomaly=False
        ),
    ]
    
    # Mock vendors
    demo_vendors = [
        VendorAnalysis(name="Google Ads", total_spend=38000, transaction_count=48, avg_transaction=792, accounts_used=["Marketing"], months_active=12, is_recurring=True),
        VendorAnalysis(name="Westfield Properties", total_spend=54000, transaction_count=12, avg_transaction=4500, accounts_used=["Rent"], months_active=12, is_recurring=True),
        VendorAnalysis(name="Facebook Ads", total_spend=24000, transaction_count=36, avg_transaction=667, accounts_used=["Marketing"], months_active=12, is_recurring=True),
        VendorAnalysis(name="StateFarm Business", total_spend=14400, transaction_count=12, avg_transaction=1200, accounts_used=["Insurance"], months_active=12, is_recurring=True),
        VendorAnalysis(name="Salesforce", total_spend=7200, transaction_count=12, avg_transaction=600, accounts_used=["Software"], months_active=12, is_recurring=True),
        VendorAnalysis(name="Mailchimp", total_spend=6000, transaction_count=12, avg_transaction=500, accounts_used=["Marketing"], months_active=12, is_recurring=True),
    ]
    
    return GAAnalysis(
        total_ga_expenses=296500,
        ga_as_pct_of_revenue=35.0,
        categories=demo_categories,
        top_vendors=demo_vendors,
        fixed_costs=68400,
        variable_costs=228100,
        discretionary_costs=90600,
        essential_costs=205900,
        unknown_vendors_total=42300,
        unknown_vendors_count=67,
        monthly_totals={"01/2025": 46450, "02/2025": 48050, "03/2025": 50150, "04/2025": 47750, "05/2025": 47750, "06/2025": 50200, "07/2025": 47950, "08/2025": 49400, "09/2025": 46040, "10/2025": 50940, "11/2025": 46440, "12/2025": 45340},
        insights=[
            "📊 Expenses at 35.0% of revenue is within normal range (15-40%).",
            "📌 Balanced cost structure (23% fixed). Good flexibility with stable base.",
            "⚠️ $42,300 (14%) of expenses have no vendor identified.",
        ],
        recommendations=[
            "💰 **Total Potential Annual Savings: $18,720**\n",
            "🚨 INVESTIGATE Rent Expense: Expected $4,500/month but varies by ±$800. Check for billing errors, rate changes, or missed payments. Potential recovery: $4,800.",
            "🚨 INVESTIGATE Insurance Premium: Expected $1,200/month but varies by ±$320. Check for billing errors, rate changes, or missed payments. Potential recovery: $1,920.",
            "Negotiate with Google Ads: $38,000 (13% of total). Large concentrated spend creates negotiating leverage. Consider annual commitment for 5-10% discount.",
            "Subscription audit: $18,600 in software/subscriptions. Review all active subscriptions, eliminate unused tools, consolidate overlapping services. Typical savings: 15-25%.",
        ]
    )


def render_analysis(analysis, is_demo=False):
    """Render analysis results - used for both real and demo data"""
    
    if is_demo:
        st.markdown('<span style="background: #dc2626; color: white; padding: 4px 12px; border-radius: 20px; font-size: 0.75rem; font-weight: 700;">SAMPLE ANALYSIS</span>', unsafe_allow_html=True)
        st.caption("This is example data showing what your analysis will look like")
    
    # Summary metrics
    st.header("💰 Summary")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Expenses", format_currency(analysis.total_ga_expenses))
    
    with col2:
        st.metric("% of Revenue", f"{analysis.ga_as_pct_of_revenue:.1f}%")
    
    with col3:
        fixed_pct = (analysis.fixed_costs / analysis.total_ga_expenses * 100) if analysis.total_ga_expenses > 0 else 0
        st.metric("Fixed Costs", format_currency(analysis.fixed_costs), f"{fixed_pct:.0f}% of total")
    
    with col4:
        st.metric("Unidentified Vendors", format_currency(analysis.unknown_vendors_total), f"{analysis.unknown_vendors_count} txns", delta_color="inverse")
    
    st.divider()
    
    # Tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["🚨 Anomalies", "📊 Volatile", "✓ Consistent", "🏢 Vendors", "✅ Recommendations"])
    
    with tab1:
        anomalies = [c for c in analysis.categories if c.has_anomaly]
        if anomalies:
            st.error(f"Found {len(anomalies)} expense categories that should be consistent but aren't")
            for cat in anomalies:
                st.markdown(f"""
                <div class="anomaly-card">
                    <h4>⚠️ {cat.name}</h4>
                    <p><strong>Total:</strong> {format_currency(cat.total)} &nbsp;|&nbsp; <strong>Monthly Avg:</strong> {format_currency(cat.monthly_avg)}</p>
                    <p><strong>Variance:</strong> {cat.coefficient_of_variation:.0%} <span style="color: #fca5a5;">(should be &lt;15%)</span></p>
                    <p><strong>Range:</strong> {format_currency(max(0, cat.monthly_avg - cat.monthly_std))} - {format_currency(cat.monthly_avg + cat.monthly_std)}</p>
                </div>
                """, unsafe_allow_html=True)
                if cat.monthly_trend:
                    df = pd.DataFrame([{"Month": k, "Amount": v} for k, v in sorted(cat.monthly_trend.items())])
                    st.bar_chart(df.set_index("Month"), color="#dc2626")
                if cat.top_vendors and cat.top_vendors[0][0] != "Unknown":
                    st.caption(f"🏢 Top Vendor: {cat.top_vendors[0][0]}")
                st.markdown("---")
        else:
            st.success("✓ No anomalies detected!")
    
    with tab2:
        volatile = [c for c in analysis.categories if not c.is_consistent and not c.has_anomaly and c.coefficient_of_variation > CV_VOLATILE_THRESHOLD]
        if volatile:
            st.warning(f"Found {len(volatile)} volatile expense categories worth reviewing")
            for cat in volatile[:10]:
                with st.expander(f"📊 {cat.name} — {format_currency(cat.total)} ({cat.coefficient_of_variation:.0%} variance)"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**% of Revenue:** {cat.pct_of_revenue:.1f}%")
                        st.write(f"**Transactions:** {cat.transaction_count}")
                        st.write(f"**Avg Transaction:** {format_currency(cat.avg_transaction)}")
                    with col2:
                        if cat.top_vendors:
                            st.write("**Top Vendors:**")
                            for vendor, amount in cat.top_vendors[:3]:
                                if vendor != "Unknown":
                                    st.write(f"- {vendor}: {format_currency(amount)}")
                    if cat.monthly_trend:
                        df = pd.DataFrame([{"Month": k, "Amount": v} for k, v in sorted(cat.monthly_trend.items())])
                        st.bar_chart(df.set_index("Month"), color="#f59e0b")
        else:
            st.success("✓ No highly volatile expenses found.")
    
    with tab3:
        consistent = [c for c in analysis.categories if c.is_consistent and not c.has_anomaly]
        if consistent:
            consistent_total = sum(c.total for c in consistent)
            st.success(f"✓ {len(consistent)} categories are stable ({format_currency(consistent_total)} total)")
            df = pd.DataFrame([{"Category": c.name, "Total": c.total, "CV": f"{c.coefficient_of_variation:.0%}", "Status": "✓ Stable" if c.coefficient_of_variation < 0.10 else "~ Mostly Stable"} for c in sorted(consistent, key=lambda x: -x.total)])
            st.dataframe(df, column_config={"Total": st.column_config.NumberColumn(format="$%.2f")}, hide_index=True, use_container_width=True)
        else:
            st.info("No consistently stable expenses identified.")
    
    with tab4:
        st.subheader("Top Vendors by Spend")
        vendors_data = [{"Vendor": v.name, "Total Spend": v.total_spend, "Transactions": v.transaction_count, "Avg Transaction": v.avg_transaction, "Recurring": "🔄 Yes" if v.is_recurring else "No"} for v in analysis.top_vendors[:20] if v.name != "Unknown"]
        if vendors_data:
            df = pd.DataFrame(vendors_data)
            st.dataframe(df, column_config={"Total Spend": st.column_config.NumberColumn(format="$%.2f"), "Avg Transaction": st.column_config.NumberColumn(format="$%.2f")}, hide_index=True, use_container_width=True)
        if analysis.unknown_vendors_total > 0:
            st.error(f"⚠️ {format_currency(analysis.unknown_vendors_total)} in expenses have no vendor identified ({analysis.unknown_vendors_count} transactions)")
    
    with tab5:
        st.subheader("Actionable Recommendations")
        for rec in analysis.recommendations:
            if rec.startswith("💰"):
                st.success(rec)
            elif "🚨" in rec:
                st.error(rec)
            else:
                st.warning(rec)
    
    # Monthly trend
    st.divider()
    st.header("📅 Monthly Expense Trend")
    if analysis.monthly_totals:
        df = pd.DataFrame([{"Month": k, "Total Expenses": v} for k, v in sorted(analysis.monthly_totals.items())])
        st.bar_chart(df.set_index("Month"), color="#dc2626")


# Main content - Show landing page if no analysis yet
if 'analysis' not in st.session_state:
    
    # Demo Preview Section
    st.header("📈 See What You'll Get")
    st.markdown("Here's an example analysis from a sample company:")
    
    demo_analysis = get_demo_analysis()
    render_analysis(demo_analysis, is_demo=True)
    
    st.divider()
    
    # How-To Guides Section
    st.header("🎬 How to Export Your Data")
    st.markdown("Follow these step-by-step guides to export your data from QuickBooks Online")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        <div class="info-card">
            <h4>📋 Export Chart of Accounts</h4>
            <div style="margin: 1rem 0;">
                <p><span class="step-number">1</span> Log into QuickBooks Online</p>
                <p><span class="step-number">2</span> Click the <strong>Settings</strong> gear icon (top right)</p>
                <p><span class="step-number">3</span> Select <strong>Chart of Accounts</strong></p>
                <p><span class="step-number">4</span> Click <strong>Run Report</strong> button (top right)</p>
                <p><span class="step-number">5</span> Click <strong>Export</strong> dropdown → <strong>Export to Excel</strong></p>
                <p><span class="step-number">6</span> Save the .xlsx file to your computer</p>
            </div>
            <p style="color: #a3a3a3; font-size: 0.85rem; margin-top: 1rem;">
                ⏱️ This only needs to be done once per company
            </p>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("""
        <div class="info-card">
            <h4>📊 Export General Ledger</h4>
            <div style="margin: 1rem 0;">
                <p><span class="step-number">1</span> Go to <strong>Reports</strong> in the left menu</p>
                <p><span class="step-number">2</span> Search for <strong>"General Ledger"</strong></p>
                <p><span class="step-number">3</span> Set your <strong>date range</strong> (e.g., This Fiscal Year)</p>
                <p><span class="step-number">4</span> Click <strong>Run Report</strong></p>
                <p><span class="step-number">5</span> Click <strong>Export</strong> dropdown → <strong>Export to Excel</strong></p>
                <p><span class="step-number">6</span> Save the .xlsx file to your computer</p>
            </div>
            <p style="color: #a3a3a3; font-size: 0.85rem; margin-top: 1rem;">
                💡 Export for any period you want to analyze
            </p>
        </div>
        """, unsafe_allow_html=True)
    
    st.divider()
    
    # FAQ Section
    st.header("❓ Frequently Asked Questions")
    
    faq_data = [
        {
            "q": "How safe is the data I import here?",
            "a": """Your data security is our top priority. Here's how we protect your information:
            
• **Local Processing** — All analysis happens directly on our secure servers. Your data is never shared with third parties.

• **Temporary Storage** — Uploaded files are processed and then automatically deleted. We don't retain your financial data after analysis.

• **Read-Only Analysis** — This tool only reads your exported files. It cannot access, modify, or connect to your QuickBooks account.

• **Encrypted Connection** — All data transmitted between your browser and our servers is encrypted via HTTPS."""
        },
        {
            "q": "What KPIs are available for me to track?",
            "a": """The analyzer provides insights into several key performance indicators:

• **Expenses as % of Revenue** — How much of your revenue goes to costs. Benchmarked against industry standards.

• **Fixed vs Variable Cost Ratio** — Understanding your cost structure and operational flexibility.

• **Expense Consistency (CV)** — Coefficient of variation for each expense category. Identifies unpredictable spending.

• **Vendor Concentration** — How dependent you are on key vendors. Highlights negotiation opportunities.

• **Monthly Expense Trends** — Visual tracking of spending patterns over time.

• **Discretionary vs Essential Split** — What portion of expenses are adjustable vs required for operations."""
        },
        {
            "q": "What does the 'Anomaly Detection' feature do?",
            "a": """The anomaly detection automatically identifies expenses that should be consistent but aren't:

• **Expected Consistency** — Certain expenses (rent, insurance, loan payments, subscriptions) should be the same every month.

• **Variance Threshold** — If these expenses vary by more than 15%, they're flagged as anomalies.

• **Root Cause Analysis** — The tool shows you which months were high/low, helping identify billing errors, rate changes, or missed payments.

• **Potential Recovery** — Estimates how much you might recover by investigating and correcting these anomalies."""
        },
        {
            "q": "How accurate are the savings estimates?",
            "a": """The savings estimates are conservative projections based on industry benchmarks:

• **Vendor Tracking (10-15%)** — Unidentified vendors often indicate waste. Estimate assumes 10-15% recovery through better controls.

• **Negotiation Opportunities (5-10%)** — Large vendor concentrations typically yield 5-10% discounts with annual commitments.

• **Subscription Audits (15-25%)** — Industry data shows most companies have 15-25% unused or duplicate subscriptions.

• **Anomaly Recovery** — Based on the actual variance detected in your data.

These are starting points for investigation, not guarantees. Actual savings depend on your specific situation."""
        },
        {
            "q": "What file formats are supported?",
            "a": """Currently, the analyzer supports:

• **Excel files (.xlsx)** — The standard export format from QuickBooks Online.

• **QuickBooks Online exports** — The tool is specifically designed for QBO's Chart of Accounts and General Ledger report formats.

• **Date ranges** — Any date range is supported. For best results, export at least 6-12 months of data to identify meaningful patterns.

**Coming soon:** CSV files, QuickBooks Desktop exports, Xero integration."""
        },
        {
            "q": "Why do some expenses show as 'Unknown' vendor?",
            "a": """Expenses appear with 'Unknown' vendor when:

• **Missing data in QBO** — The original transaction wasn't assigned a vendor/payee name.

• **Bank feed imports** — Automatic bank imports sometimes don't capture vendor names.

• **Journal entries** — Manual journal entries typically don't have vendor information.

**Why it matters:** High percentages of unknown vendors indicate data quality issues and potential control gaps. Consider implementing stricter receipt/invoice requirements for better tracking."""
        }
    ]
    
    for faq in faq_data:
        with st.expander(faq["q"]):
            st.markdown(faq["a"])
    
    st.divider()
    
    # Call to action
    st.markdown("""
    <div style="text-align: center; padding: 2rem; background: linear-gradient(135deg, #171717 0%, #262626 100%); border-radius: 12px; margin-top: 2rem;">
        <h3 style="color: white; margin-bottom: 1rem;">Ready to analyze your expenses?</h3>
        <p style="color: #a3a3a3;">Upload your Chart of Accounts and General Ledger files using the sidebar</p>
    </div>
    """, unsafe_allow_html=True)


# Handle analysis
if analyze_btn and coa_file and gl_file:
    with st.spinner("Analyzing expenses..."):
        try:
            # Save uploaded files
            coa_path = save_uploaded_file(coa_file)
            gl_path = save_uploaded_file(gl_file)
            
            # Run analysis
            analysis, account_map = run_analysis(coa_path, gl_path, industry)
            
            # Cleanup temp files
            os.unlink(coa_path)
            os.unlink(gl_path)
            
            # Store in session state
            st.session_state['analysis'] = analysis
            st.session_state['account_map'] = account_map
            
            st.rerun()
            
        except Exception as e:
            st.error(f"Error during analysis: {str(e)}")
            st.stop()

# Display results if we have them
if 'analysis' in st.session_state:
    analysis = st.session_state['analysis']
    
    # Clear analysis button
    if st.sidebar.button("🔄 New Analysis", use_container_width=True):
        del st.session_state['analysis']
        del st.session_state['account_map']
        st.rerun()
    
    render_analysis(analysis, is_demo=False)
