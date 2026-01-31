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

# Import auth
from auth import (
    render_auth_ui, render_usage_banner, render_upgrade_cta,
    render_paywall, can_analyze, increment_usage, get_or_create_user,
    create_checkout_session
)

# Page config
st.set_page_config(
    page_title="P&L Variance Analyzer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS - Modern 2026 Design
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
    
    /* CSS Variables */
    :root {
        --primary: #dc2626;
        --primary-glow: rgba(220, 38, 38, 0.15);
        --surface: rgba(23, 23, 23, 0.8);
        --surface-light: rgba(38, 38, 38, 0.6);
        --glass: rgba(255, 255, 255, 0.03);
        --glass-border: rgba(255, 255, 255, 0.08);
        --text: #fafafa;
        --text-muted: #a3a3a3;
        --text-dim: #737373;
        --success: #22c55e;
        --warning: #f59e0b;
        --radius: 16px;
        --radius-sm: 10px;
    }
    
    /* Global */
    .stApp {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    /* Animated gradient background accent */
    .main-header {
        font-size: 2.5rem;
        font-weight: 800;
        letter-spacing: -0.03em;
        background: linear-gradient(135deg, #dc2626 0%, #f87171 50%, #dc2626 100%);
        background-size: 200% 200%;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        animation: gradient-shift 8s ease infinite;
        margin-bottom: 0.25rem;
    }
    @keyframes gradient-shift {
        0%, 100% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
    }
    
    .sub-header {
        font-size: 1.1rem;
        color: var(--text-muted);
        font-weight: 400;
        letter-spacing: -0.01em;
        margin-bottom: 2.5rem;
    }
    
    /* Glass Cards */
    .glass-card {
        background: var(--glass);
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border: 1px solid var(--glass-border);
        border-radius: var(--radius);
        padding: 1.5rem;
        transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .glass-card:hover {
        border-color: rgba(220, 38, 38, 0.3);
        box-shadow: 0 8px 32px rgba(220, 38, 38, 0.1);
        transform: translateY(-2px);
    }
    
    /* Anomaly Cards */
    .anomaly-card {
        background: linear-gradient(135deg, rgba(69, 10, 10, 0.9) 0%, rgba(127, 29, 29, 0.7) 100%);
        backdrop-filter: blur(20px);
        border: 1px solid rgba(220, 38, 38, 0.3);
        border-radius: var(--radius);
        padding: 1.5rem;
        margin-bottom: 1rem;
        transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
        position: relative;
        overflow: hidden;
    }
    .anomaly-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        width: 4px;
        height: 100%;
        background: linear-gradient(180deg, #dc2626 0%, #f87171 100%);
    }
    .anomaly-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 12px 40px rgba(220, 38, 38, 0.2);
    }
    .anomaly-card h4 {
        color: #fecaca;
        font-weight: 600;
        margin-bottom: 0.75rem;
        font-size: 1.1rem;
    }
    .anomaly-card p {
        color: rgba(255, 255, 255, 0.8);
        line-height: 1.6;
    }
    
    /* Info Cards */
    .info-card {
        background: var(--surface);
        backdrop-filter: blur(20px);
        border: 1px solid var(--glass-border);
        border-radius: var(--radius);
        padding: 1.75rem;
        margin-bottom: 1rem;
        transition: all 0.3s ease;
    }
    .info-card:hover {
        border-color: rgba(255, 255, 255, 0.15);
    }
    .info-card h4 {
        color: var(--primary);
        font-weight: 600;
        margin-bottom: 1rem;
        font-size: 1rem;
    }
    
    /* Demo Section */
    .demo-section {
        background: linear-gradient(180deg, rgba(15, 15, 15, 0.95) 0%, rgba(23, 23, 23, 0.9) 100%);
        backdrop-filter: blur(40px);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 20px;
        padding: 2.5rem;
        margin: 1.5rem 0;
        position: relative;
        overflow: hidden;
    }
    .demo-section::after {
        content: '';
        position: absolute;
        top: -50%;
        right: -50%;
        width: 100%;
        height: 100%;
        background: radial-gradient(circle, rgba(220, 38, 38, 0.08) 0%, transparent 60%);
        pointer-events: none;
    }
    
    .demo-badge {
        background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%);
        color: white;
        padding: 6px 14px;
        border-radius: 100px;
        font-size: 0.7rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        display: inline-block;
        box-shadow: 0 4px 15px rgba(220, 38, 38, 0.3);
    }
    
    .demo-metric {
        background: rgba(38, 38, 38, 0.6);
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: var(--radius-sm);
        padding: 1.25rem;
        text-align: center;
        transition: all 0.3s ease;
        position: relative;
        overflow: hidden;
    }
    .demo-metric::before {
        content: '';
        position: absolute;
        bottom: 0;
        left: 0;
        width: 100%;
        height: 3px;
        background: linear-gradient(90deg, var(--primary) 0%, transparent 100%);
    }
    .demo-metric:hover {
        transform: scale(1.02);
        border-color: rgba(220, 38, 38, 0.2);
    }
    .demo-metric-value {
        font-size: 1.6rem;
        font-weight: 700;
        color: var(--primary);
        letter-spacing: -0.02em;
    }
    .demo-metric-label {
        font-size: 0.8rem;
        color: var(--text-muted);
        margin-top: 0.5rem;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    .demo-anomaly {
        background: linear-gradient(135deg, rgba(69, 10, 10, 0.8) 0%, rgba(92, 16, 16, 0.6) 100%);
        backdrop-filter: blur(10px);
        border: 1px solid rgba(220, 38, 38, 0.2);
        border-radius: var(--radius-sm);
        padding: 1rem 1.25rem;
        margin-bottom: 0.75rem;
        transition: all 0.3s ease;
    }
    .demo-anomaly:hover {
        border-color: rgba(220, 38, 38, 0.4);
    }
    .demo-anomaly-title {
        color: #fecaca;
        font-weight: 600;
        margin-bottom: 0.25rem;
        font-size: 0.95rem;
    }
    .demo-anomaly-detail {
        color: var(--text-muted);
        font-size: 0.85rem;
    }
    
    /* Sidebar */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #fafafa 0%, #f5f5f5 100%);
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
        opacity: 0.5;
    }
    
    /* Buttons */
    .stButton > button {
        background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%);
        color: white;
        border: none;
        font-weight: 600;
        border-radius: var(--radius-sm);
        padding: 0.6rem 1.5rem;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        position: relative;
        overflow: hidden;
    }
    .stButton > button::before {
        content: '';
        position: absolute;
        top: 0;
        left: -100%;
        width: 100%;
        height: 100%;
        background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
        transition: left 0.5s ease;
    }
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(220, 38, 38, 0.4);
    }
    .stButton > button:hover::before {
        left: 100%;
    }
    .stButton > button:active {
        transform: translateY(0);
    }
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0.5rem;
        background: rgba(23, 23, 23, 0.8);
        backdrop-filter: blur(20px);
        padding: 0.5rem;
        border-radius: var(--radius);
        border: 1px solid var(--glass-border);
    }
    .stTabs [data-baseweb="tab"] {
        font-weight: 500;
        color: var(--text-muted);
        background: transparent;
        border-radius: var(--radius-sm);
        padding: 0.5rem 1rem;
        transition: all 0.3s ease;
    }
    .stTabs [data-baseweb="tab"]:hover {
        color: var(--text);
        background: rgba(255, 255, 255, 0.05);
    }
    .stTabs [aria-selected="true"] {
        color: white !important;
        background: var(--primary) !important;
        box-shadow: 0 4px 15px rgba(220, 38, 38, 0.3);
    }
    
    /* Expanders */
    .streamlit-expanderHeader {
        background: rgba(245, 245, 245, 0.8);
        backdrop-filter: blur(10px);
        border-radius: var(--radius-sm);
        border: 1px solid rgba(0, 0, 0, 0.05);
        transition: all 0.3s ease;
    }
    .streamlit-expanderHeader:hover {
        background: rgba(245, 245, 245, 1);
    }
    
    /* Metrics */
    [data-testid="stMetricValue"] {
        color: var(--primary);
        font-weight: 700;
        letter-spacing: -0.02em;
    }
    [data-testid="stMetricLabel"] {
        font-weight: 500;
        opacity: 0.9;
    }
    [data-testid="stMetricDelta"] {
        font-weight: 500;
    }
    
    /* Data Tables */
    .stDataFrame {
        border-radius: var(--radius);
        overflow: hidden;
    }
    
    /* Dividers */
    hr {
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent, var(--glass-border), transparent);
        margin: 2rem 0;
    }
    
    /* Charts */
    .stPlotlyChart, [data-testid="stArrowVegaLiteChart"] {
        border-radius: var(--radius);
        overflow: hidden;
    }
    
    /* Success/Warning/Error Messages */
    .stSuccess {
        background: rgba(34, 197, 94, 0.1);
        border: 1px solid rgba(34, 197, 94, 0.3);
        border-radius: var(--radius-sm);
    }
    .stWarning {
        background: rgba(245, 158, 11, 0.1);
        border: 1px solid rgba(245, 158, 11, 0.3);
        border-radius: var(--radius-sm);
    }
    .stError {
        background: rgba(220, 38, 38, 0.1);
        border: 1px solid rgba(220, 38, 38, 0.3);
        border-radius: var(--radius-sm);
    }
    
    /* CTA Section */
    .cta-section {
        background: linear-gradient(135deg, rgba(23, 23, 23, 0.95) 0%, rgba(38, 38, 38, 0.9) 100%);
        backdrop-filter: blur(40px);
        border: 1px solid var(--glass-border);
        border-radius: 20px;
        padding: 3rem;
        text-align: center;
        position: relative;
        overflow: hidden;
    }
    .cta-section::before {
        content: '';
        position: absolute;
        top: -100px;
        left: 50%;
        transform: translateX(-50%);
        width: 300px;
        height: 300px;
        background: radial-gradient(circle, rgba(220, 38, 38, 0.15) 0%, transparent 70%);
        pointer-events: none;
    }
    .cta-section h3 {
        color: white;
        font-weight: 700;
        font-size: 1.5rem;
        margin-bottom: 0.75rem;
        position: relative;
    }
    .cta-section p {
        color: var(--text-muted);
        position: relative;
    }
    
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Smooth scrolling */
    html {
        scroll-behavior: smooth;
    }
    
    /* Selection color */
    ::selection {
        background: rgba(220, 38, 38, 0.3);
    }
</style>
""", unsafe_allow_html=True)

# Header
st.markdown('<p class="main-header">📊 P&L Variance Analyzer</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Upload your QuickBooks exports • Identify cost anomalies • Get actionable insights</p>', unsafe_allow_html=True)

# Dev mode bypass - add ?dev=SECRET_KEY to URL to skip auth
params = st.query_params
DEV_MODE = params.get("dev") == st.secrets.get("dev_key", "")

if DEV_MODE and st.secrets.get("dev_key"):
    st.warning("🔧 DEV MODE - Auth & paywall bypassed")
    user = {"id": "dev", "email": "dev@test.com", "is_pro": True, "analyses_used": 0}
    st.session_state.user = user
else:
    # Auth check - get user but don't block yet
    user = render_auth_ui()

# Initialize variables
coa_file = None
gl_file = None
industry = "default"
analyze_btn = False

# Sidebar
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/analytics.png", width=60)
    
    if user:
        st.success(f"✓ {user['email']}")
        if st.button("🗑️ Clear Cache", help="Clear all cached data and re-analyze"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.cache_data.clear()
            st.cache_resource.clear()
            st.rerun()
        
        # Show usage banner in sidebar
        if user.get("is_pro"):
            st.caption("⭐ Pro — Unlimited")
        else:
            remaining = max(0, 3 - user.get("analyses_used", 0))
            st.caption(f"📊 {remaining}/3 free uploads")
            if st.button("⭐ Upgrade to Pro", use_container_width=True):
                try:
                    checkout_url = create_checkout_session(user["email"], user["id"])
                    st.components.v1.html(f'<script>window.open("{checkout_url}", "_blank");</script>', height=0)
                except Exception as e:
                    st.error(f"Error: {e}")
        
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
        
        # Organized industry list
        INDUSTRY_OPTIONS = [
            "default",
            # Retail & Consumer
            "retail", "ecommerce", "restaurant", "hospitality", "grocery",
            # Professional Services
            "professional_services", "consulting", "legal", "accounting", "marketing_agency", "staffing",
            # Healthcare
            "healthcare", "dental", "medical_practice", "veterinary",
            # Construction & Trades
            "construction", "plumbing_hvac", "electrical", "landscaping",
            # Manufacturing & Distribution
            "manufacturing", "wholesale", "distribution",
            # Technology
            "technology", "saas", "it_services",
            # Real Estate
            "real_estate", "property_management",
            # Transportation
            "transportation", "trucking",
            # Other Services
            "fitness", "salon_spa", "childcare", "automotive_repair", "cleaning_services", "nonprofit",
        ]
        
        def format_industry(x):
            labels = {
                "default": "— Select your industry —",
                "saas": "SaaS / Software",
                "it_services": "IT Services",
                "plumbing_hvac": "Plumbing / HVAC",
                "salon_spa": "Salon / Spa",
            }
            return labels.get(x, x.replace("_", " ").title())
        
        industry = st.selectbox(
            "Industry (for benchmarks)",
            options=INDUSTRY_OPTIONS,
            index=0,
            format_func=format_industry
        )
        
        # Check if user can still analyze
        if can_analyze(user):
            analyze_btn = st.button("🔍 Analyze", type="primary", use_container_width=True)
        else:
            st.error("⚠️ Free uploads exhausted")
            analyze_btn = st.button("🔍 Analyze", type="primary", use_container_width=True, disabled=True)
            if st.button("🚀 Upgrade to Pro", type="secondary", use_container_width=True):
                try:
                    checkout_url = create_checkout_session(user["email"], user["id"])
                    st.components.v1.html(f'<script>window.open("{checkout_url}", "_blank");</script>', height=0)
                except Exception as e:
                    st.error(f"Error: {e}")
    else:
        st.info("👈 Sign in on the main page to start analyzing")
    
    # Always show help section in sidebar
    st.divider()
    st.markdown("**📚 Quick Help**")
    
    with st.expander("📋 How to Export Data"):
        st.markdown("""
        **Chart of Accounts:**
        Settings → Chart of Accounts → Run Report → Export to Excel
        
        **General Ledger:**
        Reports → General Ledger → Set date range → Run Report → Export to Excel
        """)
    
    with st.expander("💰 Pricing"):
        st.markdown("""
        **Free:** 3 uploads  
        **Pro:** $10/month unlimited
        """)
    
    st.markdown("*📖 More questions? See FAQs at the bottom of the page*")


def save_uploaded_file(uploaded_file) -> str:
    """Save uploaded file to temp location and return path"""
    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
        tmp.write(uploaded_file.getvalue())
        return tmp.name


def run_analysis(coa_path: str, gl_path: str, industry: str):
    """Run the full analysis pipeline"""
    from gl_analyzer import parse_gl_with_mapping, build_financial_statements
    
    # Parse CoA to create mapping
    account_map = parse_qbo_coa(coa_path)
    
    # Save mapping to temp file
    import json
    mapping_path = tempfile.mktemp(suffix='.json')
    with open(mapping_path, 'w') as f:
        json.dump({k: v.value for k, v in account_map.items()}, f)
    
    # Run analysis
    analysis = run_ga_analysis(gl_path, mapping_path, industry=industry)
    
    # Also build P&L for display
    from gl_analyzer import load_account_mapping
    type_map = load_account_mapping(mapping_path)
    accounts, transactions = parse_gl_with_mapping(gl_path, type_map)
    pnl_data, _ = build_financial_statements(accounts)
    
    # Cleanup
    os.unlink(mapping_path)
    
    return analysis, account_map, pnl_data, transactions


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


def detect_dayfirst(transactions: list) -> bool:
    """Detect if transaction dates use day-first format (DD/MM/YYYY)"""
    for txn in transactions[:50]:  # Check first 50
        date_str = str(txn.date if hasattr(txn, 'date') else txn.get('date', ''))
        if '/' in date_str:
            parts = date_str.split('/')
            if len(parts) >= 2 and parts[0].isdigit():
                first_num = int(parts[0])
                if first_num > 12:  # Must be a day
                    return True
    return False


def extract_months_from_transactions(transactions: list) -> list:
    """Extract unique months from transaction dates"""
    months = set()
    dayfirst = detect_dayfirst(transactions)
    
    for txn in transactions:
        try:
            date_str = txn.date if hasattr(txn, 'date') else txn.get('date', '')
            date_str = str(date_str).strip()
            
            # If already in YYYY-MM-DD format, extract directly
            if len(date_str) >= 10 and date_str[4] == '-' and date_str[7] == '-':
                month_key = date_str[:7]
                if 1 <= int(month_key.split('-')[1]) <= 12:
                    months.add(month_key)
                continue
            
            # Try pandas to parse with detected format
            try:
                parsed = pd.to_datetime(date_str, dayfirst=dayfirst)
                month_key = parsed.strftime("%Y-%m")
                months.add(month_key)
                continue
            except:
                pass
            
        except:
            pass
    return sorted(months)


def filter_transactions_by_month(transactions: list, month: str) -> list:
    """Filter transactions to a specific month (YYYY-MM format)"""
    filtered = []
    dayfirst = detect_dayfirst(transactions)
    
    for txn in transactions:
        try:
            date_str = txn.date if hasattr(txn, 'date') else txn.get('date', '')
            date_str = str(date_str).strip()
            
            # If already in YYYY-MM-DD format, match directly
            if len(date_str) >= 10 and date_str[4] == '-' and date_str[7] == '-':
                if date_str[:7] == month:
                    filtered.append(txn)
                continue
            
            # Use pandas for consistent date parsing with detected format
            try:
                parsed = pd.to_datetime(date_str, dayfirst=dayfirst)
                txn_month = parsed.strftime("%Y-%m")
                if txn_month == month:
                    filtered.append(txn)
            except:
                pass
        except:
            pass
    return filtered


def build_pnl_from_transactions(transactions: list, account_map: dict) -> dict:
    """Build P&L data from filtered transactions"""
    from collections import defaultdict
    
    pnl = {
        "Revenue": defaultdict(float),
        "Cost of Goods Sold": defaultdict(float),
        "Expenses": defaultdict(float),
        "Other Income": defaultdict(float),
        "Other Expense": defaultdict(float)
    }
    
    for txn in transactions:
        acct = txn.account if hasattr(txn, 'account') else txn.get('account', '')
        acct_type = txn.account_type if hasattr(txn, 'account_type') else txn.get('account_type')
        amount = txn.amount if hasattr(txn, 'amount') else txn.get('amount', 0)
        
        # Convert enum to string if needed
        type_str = acct_type.value if hasattr(acct_type, 'value') else str(acct_type)
        
        if type_str == "Revenue":
            pnl["Revenue"][acct] += amount
        elif type_str == "Cost of Goods Sold":
            pnl["Cost of Goods Sold"][acct] += amount
        elif type_str == "Expense":
            pnl["Expenses"][acct] += amount
        elif type_str == "Other Income":
            pnl["Other Income"][acct] += amount
        elif type_str == "Other Expense":
            pnl["Other Expense"][acct] += amount
    
    # Convert defaultdicts to regular dicts
    return {k: dict(v) for k, v in pnl.items()}


def calculate_pnl_totals(pnl_data: dict) -> dict:
    """Calculate P&L totals from pnl_data"""
    total_revenue = sum(abs(v) for v in pnl_data.get("Revenue", {}).values())
    total_cogs = sum(abs(v) for v in pnl_data.get("Cost of Goods Sold", {}).values())
    gross_profit = total_revenue - total_cogs
    total_expenses = sum(abs(v) for v in pnl_data.get("Expenses", {}).values())
    operating_income = gross_profit - total_expenses
    total_other_income = sum(abs(v) for v in pnl_data.get("Other Income", {}).values())
    total_other_expense = sum(abs(v) for v in pnl_data.get("Other Expense", {}).values())
    net_income = operating_income + total_other_income - total_other_expense
    
    return {
        "total_revenue": total_revenue,
        "total_cogs": total_cogs,
        "gross_profit": gross_profit,
        "gross_margin": (gross_profit / total_revenue * 100) if total_revenue else 0,
        "total_expenses": total_expenses,
        "operating_income": operating_income,
        "operating_margin": (operating_income / total_revenue * 100) if total_revenue else 0,
        "total_other_income": total_other_income,
        "total_other_expense": total_other_expense,
        "net_income": net_income,
        "net_margin": (net_income / total_revenue * 100) if total_revenue else 0
    }


def format_variance(current: float, prior: float) -> tuple:
    """Calculate and format variance"""
    if prior == 0:
        if current == 0:
            return 0, "—"
        return current, "New"
    
    variance = current - prior
    pct_change = (variance / abs(prior)) * 100
    
    return variance, f"{pct_change:+.1f}%"


def render_pnl_comparison(pnl_current: dict, pnl_prior: dict, label_current: str, label_prior: str):
    """Render side-by-side P&L comparison with variances"""
    st.header("📊 P&L Comparison")
    
    totals_current = calculate_pnl_totals(pnl_current)
    totals_prior = calculate_pnl_totals(pnl_prior)
    
    # Build comparison rows
    rows = []
    
    def add_section(section_name: str, current_data: dict, prior_data: dict, is_expense: bool = False):
        rows.append({
            "Account": f"**{section_name}**",
            label_prior: "",
            label_current: "",
            "Variance $": "",
            "Variance %": ""
        })
        
        # Get all accounts from both periods
        all_accounts = set(current_data.keys()) | set(prior_data.keys())
        
        # Sort by current amount (descending)
        sorted_accounts = sorted(all_accounts, key=lambda x: -abs(current_data.get(x, 0)))
        
        for acct in sorted_accounts:
            curr = abs(current_data.get(acct, 0))
            prior = abs(prior_data.get(acct, 0))
            var_amt, var_pct = format_variance(curr, prior)
            
            # Color code significant variances
            var_color = ""
            if isinstance(var_pct, str) and var_pct not in ["—", "New"]:
                pct_val = float(var_pct.replace("%", "").replace("+", ""))
                if is_expense:
                    # For expenses, increase is bad (red), decrease is good (green)
                    if pct_val > 10:
                        var_color = "🔴 "
                    elif pct_val < -10:
                        var_color = "🟢 "
                else:
                    # For revenue, increase is good (green), decrease is bad (red)
                    if pct_val > 10:
                        var_color = "🟢 "
                    elif pct_val < -10:
                        var_color = "🔴 "
            
            rows.append({
                "Account": f"    {acct}",
                label_prior: format_currency(prior) if prior else "—",
                label_current: format_currency(curr) if curr else "—",
                "Variance $": format_currency(var_amt) if var_amt else "—",
                "Variance %": f"{var_color}{var_pct}"
            })
    
    # Revenue
    add_section("REVENUE", pnl_current.get("Revenue", {}), pnl_prior.get("Revenue", {}), is_expense=False)
    rev_var, rev_pct = format_variance(totals_current["total_revenue"], totals_prior["total_revenue"])
    rows.append({
        "Account": "**Total Revenue**",
        label_prior: f"**{format_currency(totals_prior['total_revenue'])}**",
        label_current: f"**{format_currency(totals_current['total_revenue'])}**",
        "Variance $": f"**{format_currency(rev_var)}**",
        "Variance %": f"**{rev_pct}**"
    })
    rows.append({"Account": "", label_prior: "", label_current: "", "Variance $": "", "Variance %": ""})
    
    # COGS
    add_section("COST OF GOODS SOLD", pnl_current.get("Cost of Goods Sold", {}), pnl_prior.get("Cost of Goods Sold", {}), is_expense=True)
    cogs_var, cogs_pct = format_variance(totals_current["total_cogs"], totals_prior["total_cogs"])
    rows.append({
        "Account": "**Total COGS**",
        label_prior: f"**{format_currency(totals_prior['total_cogs'])}**",
        label_current: f"**{format_currency(totals_current['total_cogs'])}**",
        "Variance $": f"**{format_currency(cogs_var)}**",
        "Variance %": f"**{cogs_pct}**"
    })
    rows.append({"Account": "", label_prior: "", label_current: "", "Variance $": "", "Variance %": ""})
    
    # Gross Profit
    gp_var, gp_pct = format_variance(totals_current["gross_profit"], totals_prior["gross_profit"])
    rows.append({
        "Account": "**GROSS PROFIT**",
        label_prior: f"**{format_currency(totals_prior['gross_profit'])}** ({totals_prior['gross_margin']:.1f}%)",
        label_current: f"**{format_currency(totals_current['gross_profit'])}** ({totals_current['gross_margin']:.1f}%)",
        "Variance $": f"**{format_currency(gp_var)}**",
        "Variance %": f"**{gp_pct}**"
    })
    rows.append({"Account": "", label_prior: "", label_current: "", "Variance $": "", "Variance %": ""})
    
    # Expenses
    add_section("OPERATING EXPENSES", pnl_current.get("Expenses", {}), pnl_prior.get("Expenses", {}), is_expense=True)
    exp_var, exp_pct = format_variance(totals_current["total_expenses"], totals_prior["total_expenses"])
    rows.append({
        "Account": "**Total Operating Expenses**",
        label_prior: f"**{format_currency(totals_prior['total_expenses'])}**",
        label_current: f"**{format_currency(totals_current['total_expenses'])}**",
        "Variance $": f"**{format_currency(exp_var)}**",
        "Variance %": f"**{exp_pct}**"
    })
    rows.append({"Account": "", label_prior: "", label_current: "", "Variance $": "", "Variance %": ""})
    
    # Net Income
    ni_var, ni_pct = format_variance(totals_current["net_income"], totals_prior["net_income"])
    rows.append({
        "Account": "**NET INCOME**",
        label_prior: f"**{format_currency(totals_prior['net_income'])}** ({totals_prior['net_margin']:.1f}%)",
        label_current: f"**{format_currency(totals_current['net_income'])}** ({totals_current['net_margin']:.1f}%)",
        "Variance $": f"**{format_currency(ni_var)}**",
        "Variance %": f"**{ni_pct}**"
    })
    
    # Display
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, use_container_width=True, height=600)
    
    # KPIs Comparison Section
    st.subheader("📊 Key Performance Indicators")
    
    kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
    
    # Gross Margin comparison
    with kpi_col1:
        gm_change = totals_current["gross_margin"] - totals_prior["gross_margin"]
        st.metric("Gross Margin", f"{totals_current['gross_margin']:.1f}%", f"{gm_change:+.1f}pp")
        st.caption(f"Prior: {totals_prior['gross_margin']:.1f}%")
    
    # Net Margin comparison
    with kpi_col2:
        nm_change = totals_current["net_margin"] - totals_prior["net_margin"]
        st.metric("Net Margin", f"{totals_current['net_margin']:.1f}%", f"{nm_change:+.1f}pp")
        st.caption(f"Prior: {totals_prior['net_margin']:.1f}%")
    
    # OpEx Ratio comparison
    with kpi_col3:
        opex_curr = (totals_current["total_expenses"] / totals_current["total_revenue"] * 100) if totals_current["total_revenue"] else 0
        opex_prior = (totals_prior["total_expenses"] / totals_prior["total_revenue"] * 100) if totals_prior["total_revenue"] else 0
        opex_change = opex_curr - opex_prior
        st.metric("OpEx Ratio", f"{opex_curr:.1f}%", f"{opex_change:+.1f}pp", delta_color="inverse")
        st.caption(f"Prior: {opex_prior:.1f}%")
    
    # COGS Ratio comparison
    with kpi_col4:
        cogs_curr = (totals_current["total_cogs"] / totals_current["total_revenue"] * 100) if totals_current["total_revenue"] else 0
        cogs_prior = (totals_prior["total_cogs"] / totals_prior["total_revenue"] * 100) if totals_prior["total_revenue"] else 0
        cogs_change = cogs_curr - cogs_prior
        st.metric("COGS Ratio", f"{cogs_curr:.1f}%", f"{cogs_change:+.1f}pp", delta_color="inverse")
        st.caption(f"Prior: {cogs_prior:.1f}%")
    
    st.divider()
    
    # Variance Commentary with detailed drivers
    st.subheader("📝 Variance Analysis & Key Drivers")
    
    # Calculate all variances for detailed analysis
    all_variances = []
    
    # Revenue variances
    for acct in set(pnl_current.get("Revenue", {}).keys()) | set(pnl_prior.get("Revenue", {}).keys()):
        curr = abs(pnl_current.get("Revenue", {}).get(acct, 0))
        prior = abs(pnl_prior.get("Revenue", {}).get(acct, 0))
        var_amt = curr - prior
        var_pct = ((var_amt) / prior * 100) if prior > 0 else (100 if curr > 0 else 0)
        if abs(var_amt) > 50:
            all_variances.append(("Revenue", acct, prior, curr, var_amt, var_pct))
    
    # COGS variances
    for acct in set(pnl_current.get("Cost of Goods Sold", {}).keys()) | set(pnl_prior.get("Cost of Goods Sold", {}).keys()):
        curr = abs(pnl_current.get("Cost of Goods Sold", {}).get(acct, 0))
        prior = abs(pnl_prior.get("Cost of Goods Sold", {}).get(acct, 0))
        var_amt = curr - prior
        var_pct = ((var_amt) / prior * 100) if prior > 0 else (100 if curr > 0 else 0)
        if abs(var_amt) > 50:
            all_variances.append(("COGS", acct, prior, curr, var_amt, var_pct))
    
    # Expense variances
    for acct in set(pnl_current.get("Expenses", {}).keys()) | set(pnl_prior.get("Expenses", {}).keys()):
        curr = abs(pnl_current.get("Expenses", {}).get(acct, 0))
        prior = abs(pnl_prior.get("Expenses", {}).get(acct, 0))
        var_amt = curr - prior
        var_pct = ((var_amt) / prior * 100) if prior > 0 else (100 if curr > 0 else 0)
        if abs(var_amt) > 50:
            all_variances.append(("Expense", acct, prior, curr, var_amt, var_pct))
    
    # Sort by absolute variance amount
    all_variances.sort(key=lambda x: -abs(x[4]))
    
    # Net Income change analysis
    ni_change = totals_current["net_income"] - totals_prior["net_income"]
    ni_change_pct = (ni_change / abs(totals_prior["net_income"]) * 100) if totals_prior["net_income"] != 0 else 0
    
    if ni_change > 0:
        st.success(f"**Net Income improved by {format_currency(ni_change)} ({ni_change_pct:+.1f}%)**")
    elif ni_change < 0:
        st.error(f"**Net Income declined by {format_currency(abs(ni_change))} ({ni_change_pct:.1f}%)**")
    else:
        st.info("**Net Income unchanged between periods**")
    
    # Explain the drivers
    st.markdown("**Key drivers of the change:**")
    
    favorable = []
    unfavorable = []
    
    for cat, acct, prior, curr, var_amt, var_pct in all_variances[:10]:
        if cat == "Revenue":
            if var_amt > 0:
                favorable.append((acct, var_amt, var_pct, "revenue increase"))
            else:
                unfavorable.append((acct, var_amt, var_pct, "revenue decrease"))
        else:  # COGS or Expense
            if var_amt < 0:  # Decrease in cost is favorable
                favorable.append((acct, var_amt, var_pct, "cost reduction"))
            else:
                unfavorable.append((acct, var_amt, var_pct, "cost increase"))
    
    if favorable:
        st.markdown("**🟢 Favorable variances:**")
        for acct, var_amt, var_pct, reason in favorable[:5]:
            st.markdown(f"• **{acct}**: {format_currency(abs(var_amt))} {reason} ({abs(var_pct):.1f}%)")
    
    if unfavorable:
        st.markdown("**🔴 Unfavorable variances:**")
        for acct, var_amt, var_pct, reason in unfavorable[:5]:
            st.markdown(f"• **{acct}**: {format_currency(abs(var_amt))} {reason} ({abs(var_pct):.1f}%)")
    
    # Summary narrative
    st.divider()
    st.markdown("**📋 Executive Summary:**")
    
    summary_parts = []
    
    # Revenue narrative
    rev_change = totals_current["total_revenue"] - totals_prior["total_revenue"]
    if abs(rev_change) > 0:
        rev_dir = "increased" if rev_change > 0 else "decreased"
        rev_pct = (rev_change / totals_prior["total_revenue"] * 100) if totals_prior["total_revenue"] else 0
        summary_parts.append(f"Revenue {rev_dir} by {format_currency(abs(rev_change))} ({abs(rev_pct):.1f}%)")
    
    # Gross margin narrative
    if abs(gm_change) > 1:
        gm_dir = "improved" if gm_change > 0 else "declined"
        summary_parts.append(f"Gross margin {gm_dir} by {abs(gm_change):.1f} percentage points")
    
    # OpEx narrative
    exp_change = totals_current["total_expenses"] - totals_prior["total_expenses"]
    if abs(exp_change) > 0:
        exp_dir = "increased" if exp_change > 0 else "decreased"
        summary_parts.append(f"Operating expenses {exp_dir} by {format_currency(abs(exp_change))}")
    
    if summary_parts:
        st.markdown(". ".join(summary_parts) + ".")
    
    # Top driver explanation
    if all_variances:
        top_driver = all_variances[0]
        cat, acct, prior, curr, var_amt, var_pct = top_driver
        direction = "increase" if var_amt > 0 else "decrease"
        st.markdown(f"The largest single variance was **{acct}** ({cat}), which showed a {format_currency(abs(var_amt))} {direction} ({abs(var_pct):.1f}%) from {format_currency(prior)} to {format_currency(curr)}.")
    
    return totals_current, totals_prior


def render_pnl(pnl_data: dict, title: str = "📊 Profit & Loss Statement"):
    """Render a single-period P&L statement"""
    st.header(title)
    
    totals = calculate_pnl_totals(pnl_data)
    
    # Summary metrics at top - Row 1
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Revenue", format_currency(totals["total_revenue"]))
    with col2:
        st.metric("Gross Profit", format_currency(totals["gross_profit"]))
        st.caption(f"Gross Margin: {totals['gross_margin']:.1f}%")
    with col3:
        st.metric("Operating Expenses", format_currency(totals["total_expenses"]))
        expense_ratio = (totals["total_expenses"] / totals["total_revenue"] * 100) if totals["total_revenue"] else 0
        st.caption(f"OpEx Ratio: {expense_ratio:.1f}%")
    with col4:
        st.metric("Net Income", format_currency(totals["net_income"]))
        st.caption(f"Net Margin: {totals['net_margin']:.1f}%")
    
    # Additional KPIs - Row 2
    col5, col6, col7, col8 = st.columns(4)
    with col5:
        st.metric("COGS", format_currency(totals["total_cogs"]))
        cogs_ratio = (totals["total_cogs"] / totals["total_revenue"] * 100) if totals["total_revenue"] else 0
        st.caption(f"COGS Ratio: {cogs_ratio:.1f}%")
    with col6:
        operating_income = totals["gross_profit"] - totals["total_expenses"]
        st.metric("Operating Income", format_currency(operating_income))
        op_margin = (operating_income / totals["total_revenue"] * 100) if totals["total_revenue"] else 0
        st.caption(f"Operating Margin: {op_margin:.1f}%")
    with col7:
        other_net = totals.get("total_other_income", 0) - totals.get("total_other_expense", 0)
        st.metric("Other Income/Exp", format_currency(other_net))
    with col8:
        # Contribution margin (Revenue - COGS)
        contrib_margin = totals["gross_profit"]
        contrib_pct = (contrib_margin / totals["total_revenue"] * 100) if totals["total_revenue"] else 0
        st.metric("Contribution Margin", format_currency(contrib_margin))
        st.caption(f"Contribution %: {contrib_pct:.1f}%")
    
    st.divider()
    
    # Detailed P&L
    rows = []
    
    # Revenue
    rows.append({"Account": "**REVENUE**", "Amount": ""})
    for name, amt in sorted(pnl_data.get("Revenue", {}).items(), key=lambda x: -abs(x[1])):
        rows.append({"Account": f"    {name}", "Amount": format_currency(abs(amt))})
    rows.append({"Account": "**Total Revenue**", "Amount": f"**{format_currency(totals['total_revenue'])}**"})
    rows.append({"Account": "", "Amount": ""})
    
    # COGS
    if pnl_data.get("Cost of Goods Sold"):
        rows.append({"Account": "**COST OF GOODS SOLD**", "Amount": ""})
        for name, amt in sorted(pnl_data.get("Cost of Goods Sold", {}).items(), key=lambda x: -abs(x[1])):
            rows.append({"Account": f"    {name}", "Amount": format_currency(abs(amt))})
        rows.append({"Account": "**Total COGS**", "Amount": f"**{format_currency(totals['total_cogs'])}**"})
        rows.append({"Account": "", "Amount": ""})
    
    # Gross Profit
    rows.append({"Account": "**GROSS PROFIT**", "Amount": f"**{format_currency(totals['gross_profit'])}** ({totals['gross_margin']:.1f}%)"})
    rows.append({"Account": "", "Amount": ""})
    
    # Expenses
    rows.append({"Account": "**OPERATING EXPENSES**", "Amount": ""})
    for name, amt in sorted(pnl_data.get("Expenses", {}).items(), key=lambda x: -abs(x[1])):
        rows.append({"Account": f"    {name}", "Amount": format_currency(abs(amt))})
    rows.append({"Account": "**Total Operating Expenses**", "Amount": f"**{format_currency(totals['total_expenses'])}**"})
    rows.append({"Account": "", "Amount": ""})
    
    # Net Income
    rows.append({"Account": "**NET INCOME**", "Amount": f"**{format_currency(totals['net_income'])}** ({totals['net_margin']:.1f}%)"})
    
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, use_container_width=True, height=500)
    
    return totals


def render_analysis(analysis, is_demo=False, pnl_data=None, transactions=None, account_map=None, industry="default"):
    """Render analysis results - used for both real and demo data"""
    
    if is_demo:
        st.markdown('<span style="background: #dc2626; color: white; padding: 4px 12px; border-radius: 20px; font-size: 0.75rem; font-weight: 700;">SAMPLE ANALYSIS</span>', unsafe_allow_html=True)
        st.caption("This is example data showing what your analysis will look like")
    
    # Period selection UI (only if we have transactions)
    if transactions and not is_demo:
        st.header("📅 Period Selection")
        
        # Debug: Show sample transaction dates
        with st.expander("🔧 Debug: Transaction Data", expanded=False):
            st.write(f"**Total transactions:** {len(transactions)}")
            if transactions:
                dayfirst = detect_dayfirst(transactions)
                st.write(f"**Date format detected:** {'DD/MM/YYYY (day-first)' if dayfirst else 'MM/DD/YYYY (month-first)'}")
                
                sample_dates = [t.date for t in transactions[:10]]
                st.write(f"**Sample dates (first 10):** {sample_dates}")
                
                # Show transactions per month
                from collections import Counter
                month_counts = Counter()
                unparseable = []
                for t in transactions:
                    try:
                        d = str(t.date)
                        # Handle already-normalized dates
                        if len(d) >= 10 and d[4] == '-':
                            month_counts[d[:7]] += 1
                        else:
                            parsed = pd.to_datetime(t.date, dayfirst=dayfirst)
                            month_counts[parsed.strftime("%Y-%m")] += 1
                    except:
                        unparseable.append(t.date)
                
                st.write(f"**Transactions per month:**")
                for month, count in sorted(month_counts.items()):
                    st.write(f"  {month}: {count} transactions")
                
                if unparseable:
                    st.warning(f"**Unparseable dates ({len(unparseable)}):** {unparseable[:10]}")
        
        months = extract_months_from_transactions(transactions)
        
        if months:
            # Convert to readable format (with safe fallback)
            month_labels = {}
            for m in months:
                try:
                    month_labels[m] = pd.to_datetime(m).strftime("%B %Y")
                except:
                    month_labels[m] = m  # Use raw string as fallback
            
            col1, col2 = st.columns(2)
            
            with col1:
                view_mode = st.radio(
                    "View Mode",
                    ["Full Year", "Compare Two Months"],
                    horizontal=True
                )
            
            if view_mode == "Compare Two Months":
                col1, col2 = st.columns(2)
                with col1:
                    prior_month = st.selectbox(
                        "Prior Period",
                        options=months[:-1] if len(months) > 1 else months,
                        format_func=lambda x: month_labels.get(x, x),
                        index=max(0, len(months) - 2) if len(months) > 1 else 0
                    )
                with col2:
                    current_month = st.selectbox(
                        "Current Period", 
                        options=months,
                        format_func=lambda x: month_labels.get(x, x),
                        index=len(months) - 1
                    )
                
                # Filter transactions and build P&Ls
                txns_prior = filter_transactions_by_month(transactions, prior_month)
                txns_current = filter_transactions_by_month(transactions, current_month)
                
                # Debug: show transaction counts
                st.info(f"🔧 Debug: Prior ({prior_month}): {len(txns_prior)} txns | Current ({current_month}): {len(txns_current)} txns | Total: {len(transactions)}")
                
                pnl_prior = build_pnl_from_transactions(txns_prior, account_map)
                pnl_current = build_pnl_from_transactions(txns_current, account_map)
                
                st.divider()
                
                # Show comparison
                render_pnl_comparison(
                    pnl_current, 
                    pnl_prior,
                    month_labels.get(current_month, current_month),
                    month_labels.get(prior_month, prior_month)
                )
                
                st.divider()
            else:
                # Full year view
                if pnl_data:
                    render_pnl(pnl_data, "📊 Full Year P&L")
                    st.divider()
        else:
            # No month data, show full P&L
            if pnl_data:
                render_pnl(pnl_data)
                st.divider()
    elif pnl_data:
        # Demo mode or no transactions - just show P&L
        render_pnl(pnl_data)
        st.divider()
    
    # Summary metrics
    st.header("💰 Expense Analysis Summary")
    
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
    
    # Industry Benchmark Comparison
    benchmark = INDUSTRY_BENCHMARKS.get(industry, INDUSTRY_BENCHMARKS["default"])
    ga_pct = analysis.ga_as_pct_of_revenue
    
    if industry != "default":
        industry_label = industry.replace("_", " ").title()
        if ga_pct < benchmark["low"]:
            status = "below"
            status_color = "#f59e0b"  # warning - might be underinvesting
            status_icon = "📉"
            status_text = f"Below typical range — may indicate underinvestment in operations"
        elif ga_pct > benchmark["high"]:
            status = "above"
            status_color = "#dc2626"  # alert
            status_icon = "📈"
            status_text = f"Above typical range — review for cost reduction opportunities"
        else:
            status = "within"
            status_color = "#22c55e"  # good
            status_icon = "✓"
            status_text = f"Within healthy range for your industry"
        
        st.markdown(f"""
        <div style="background: rgba(23, 23, 23, 0.8); backdrop-filter: blur(20px); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 1.25rem 1.5rem; margin: 1rem 0;">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem;">
                <div>
                    <span style="color: #a3a3a3; font-size: 0.85rem;">Industry Benchmark: <strong style="color: white;">{industry_label}</strong></span>
                    <div style="margin-top: 0.5rem;">
                        <span style="color: {status_color}; font-weight: 600; font-size: 1.1rem;">{status_icon} Your OpEx: {ga_pct:.1f}%</span>
                        <span style="color: #737373; margin: 0 0.75rem;">|</span>
                        <span style="color: #a3a3a3;">Typical range: {benchmark['low']}% – {benchmark['high']}%</span>
                    </div>
                </div>
                <div style="color: #a3a3a3; font-size: 0.85rem; max-width: 300px;">{status_text}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    st.divider()
    
    # Tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📖 How to Use This Data", "🚨 Anomalies", "📊 Volatile", "✓ Consistent", "🏢 Vendors"])
    
    with tab1:
        st.subheader("Understanding Your Numbers")
        st.markdown("""
**What Each Metric Means:**

---

**Total Expenses**  
The sum of all operating expenses in your General Ledger for the period analyzed.  
*📈 Going up?* You're spending more — could be growth (good) or cost creep (review needed).  
*📉 Going down?* You're spending less — efficiency gains or possibly underinvesting.

---

**% of Revenue**  
How much of every dollar earned goes to operating expenses.  
*📈 Going up?* Expenses growing faster than revenue — margins shrinking. Time to review costs.  
*📉 Going down?* You're getting more efficient — each dollar of revenue costs less to earn.

---

**Fixed Costs**  
Expenses that stay roughly the same each month (rent, insurance, salaries).  
*Why it matters:* High fixed costs = less flexibility. If revenue drops, these costs don't.

---

**Unidentified Vendors**  
Transactions where we couldn't identify who was paid.  
*Why it matters:* Makes it harder to spot patterns or negotiate better rates. Consider cleaning up vendor names in QuickBooks.

---

**🚨 Anomalies Tab**  
Expenses that *should* be consistent (like rent or insurance) but aren't.  
*What to look for:* Unexpected spikes might be billing errors, rate increases, or one-time charges that got coded wrong.

---

**📊 Volatile Tab**  
Expenses that naturally vary month-to-month.  
*What to look for:* Big swings might reveal seasonal patterns or areas where spending isn't controlled.

---

**✓ Consistent Tab**  
Expenses that are predictable and stable.  
*What it means:* These are your "set and forget" costs — good for budgeting.
        """)
    
    with tab2:
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
                    st.line_chart(df.set_index("Month"), color="#dc2626")
                if cat.top_vendors and cat.top_vendors[0][0] != "Unknown":
                    st.caption(f"🏢 Top Vendor: {cat.top_vendors[0][0]}")
                st.markdown("---")
        else:
            st.success("✓ No anomalies detected!")
    
    with tab3:
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
                        st.line_chart(df.set_index("Month"), color="#f59e0b")
        else:
            st.success("✓ No highly volatile expenses found.")
    
    with tab4:
        consistent = [c for c in analysis.categories if c.is_consistent and not c.has_anomaly]
        if consistent:
            consistent_total = sum(c.total for c in consistent)
            st.success(f"✓ {len(consistent)} categories are stable ({format_currency(consistent_total)} total)")
            df = pd.DataFrame([{"Category": c.name, "Total": c.total, "CV": f"{c.coefficient_of_variation:.0%}", "Status": "✓ Stable" if c.coefficient_of_variation < 0.10 else "~ Mostly Stable"} for c in sorted(consistent, key=lambda x: -x.total)])
            st.dataframe(df, column_config={"Total": st.column_config.NumberColumn(format="$%.2f")}, hide_index=True, use_container_width=True)
        else:
            st.info("No consistently stable expenses identified.")
    
    with tab5:
        st.subheader("Top Vendors by Spend")
        vendors_data = [{"Vendor": v.name, "Total Spend": v.total_spend, "Transactions": v.transaction_count, "Avg Transaction": v.avg_transaction, "Recurring": "🔄 Yes" if v.is_recurring else "No"} for v in analysis.top_vendors[:20] if v.name != "Unknown"]
        if vendors_data:
            df = pd.DataFrame(vendors_data)
            st.dataframe(df, column_config={"Total Spend": st.column_config.NumberColumn(format="$%.2f"), "Avg Transaction": st.column_config.NumberColumn(format="$%.2f")}, hide_index=True, use_container_width=True)
        if analysis.unknown_vendors_total > 0:
            st.error(f"⚠️ {format_currency(analysis.unknown_vendors_total)} in expenses have no vendor identified ({analysis.unknown_vendors_count} transactions)")
            
            # Show unknown vendor transactions if we have transaction data
            if transactions:
                unknown_txns = [t for t in transactions if not t.vendor or t.vendor.strip() == "" or t.vendor.strip().lower() == "unknown"]
                if unknown_txns:
                    with st.expander(f"📋 View {len(unknown_txns)} Unidentified Transactions", expanded=False):
                        st.caption("These transactions have no vendor name — consider updating them in QuickBooks for better tracking.")
                        unknown_data = [{
                            "Date": t.date,
                            "Account": t.account,
                            "Description": t.description[:50] + "..." if len(t.description) > 50 else t.description,
                            "Amount": t.amount
                        } for t in sorted(unknown_txns, key=lambda x: -abs(x.amount))[:100]]  # Top 100 by amount
                        df = pd.DataFrame(unknown_data)
                        st.dataframe(
                            df, 
                            column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")}, 
                            hide_index=True, 
                            use_container_width=True
                        )
                        if len(unknown_txns) > 100:
                            st.caption(f"Showing top 100 of {len(unknown_txns)} transactions by amount")
    
    # Monthly trend
    st.divider()
    st.header("📅 Monthly Expense Trend")
    if analysis.monthly_totals:
        df = pd.DataFrame([{"Month": k, "Total Expenses": v} for k, v in sorted(analysis.monthly_totals.items())])
        st.line_chart(df.set_index("Month"), color="#dc2626")


# Main content - Show landing page if no analysis yet
if 'analysis' not in st.session_state:
    
    # Demo Preview Section
    st.header("📈 See What You'll Get")
    st.markdown("Here's an example analysis from a sample company:")
    
    demo_analysis = get_demo_analysis()
    render_analysis(demo_analysis, is_demo=True)
    
    st.divider()
    
    # How-To Guides Section (collapsed by default)
    with st.expander("🎬 How to Export Your Data", expanded=False):
        st.markdown("Follow these step-by-step guides to export your data from QuickBooks Online")
        
        exp_col1, exp_col2 = st.columns(2)
        with exp_col1:
            st.markdown("""
            **📋 Export Chart of Accounts**
            1. Log into QuickBooks Online
            2. Click the **Settings** gear icon (top right)
            3. Select **Chart of Accounts**
            4. Click **Run Report** button (top right)
            5. Click **Export** dropdown → **Export to Excel**
            6. Save the .xlsx file to your computer
            
            *⏱️ This only needs to be done once per company*
            """)
        with exp_col2:
            st.markdown("""
            **📊 Export General Ledger**
            1. Go to **Reports** in the left menu
            2. Search for **"General Ledger"**
            3. Set your **date range** (e.g., This Fiscal Year)
            4. Click **Run Report**
            5. Click **Export** dropdown → **Export to Excel**
            6. Save the .xlsx file to your computer
            
            *💡 Export for any period you want to analyze*
            """)
    
    # FAQ Section (collapsed by default)
    with st.expander("❓ Frequently Asked Questions", expanded=False):
        st.markdown("""
**How much does it cost?**

• **Free Tier** — 3 free uploads to try the tool
• **Pro Plan** — $10/month for unlimited uploads

---

**Are my documents saved somewhere when I upload them for analysis?**

Your files are temporarily written to the server during analysis, then deleted when your session ends or the server restarts. We don't store your documents in any database or permanent storage. The servers are ephemeral (wiped regularly), and your data isn't retained after analysis.

---

**How safe is my data?**

• Files exist only temporarily during your session
• No permanent storage or database retention
• Servers are ephemeral and wiped regularly
• Read-only analysis — can't modify your QuickBooks
• All connections encrypted via HTTPS

---

**What file formats are supported?**

• Excel files (.xlsx) exported from QuickBooks Online
• Chart of Accounts and General Ledger reports

---

**Can I cancel Pro anytime?**

Yes! Month-to-month, no contracts. Cancel anytime via email or Stripe portal.

---

**Where do the industry benchmarks come from?**

Our industry benchmarks are compiled from multiple sources including IBISWorld industry reports, RMA Annual Statement Studies, BizMiner industry financial profiles, and aggregated public company financial data. The ranges represent typical operating expense ratios for small-to-medium businesses in each industry. These are general guidelines — your specific situation may vary based on business model, growth stage, and regional factors.
        """)
    
    st.divider()
    
    # Call to action
    if user:
        st.markdown("""
        <div class="cta-section">
            <h3>Ready to analyze your expenses?</h3>
            <p>Upload your Chart of Accounts and General Ledger files using the sidebar</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="cta-section">
            <h3>Try it free — 3 uploads included</h3>
            <p>Sign in with your email above to get started. No credit card required.</p>
        </div>
        """, unsafe_allow_html=True)


# Handle analysis
if analyze_btn and coa_file and gl_file and user:
    # Check if user can analyze (paywall)
    if not can_analyze(user):
        render_paywall()
        st.stop()
    
    with st.spinner("Analyzing expenses..."):
        try:
            # Save uploaded files
            coa_path = save_uploaded_file(coa_file)
            gl_path = save_uploaded_file(gl_file)
            
            # Run analysis
            analysis, account_map, pnl_data, transactions = run_analysis(coa_path, gl_path, industry)
            
            # Cleanup temp files
            os.unlink(coa_path)
            os.unlink(gl_path)
            
            # Increment usage (only for non-pro users)
            if not user.get("is_pro"):
                increment_usage(user["id"])
                st.session_state.user["analyses_used"] = user.get("analyses_used", 0) + 1
            
            # Store in session state
            st.session_state['analysis'] = analysis
            st.session_state['account_map'] = account_map
            st.session_state['pnl_data'] = pnl_data
            st.session_state['transactions'] = transactions
            st.session_state['industry'] = industry
            
            st.rerun()
            
        except Exception as e:
            st.error(f"Error during analysis: {str(e)}")
            st.stop()

# Display results if we have them
if 'analysis' in st.session_state:
    analysis = st.session_state['analysis']
    pnl_data = st.session_state.get('pnl_data')
    transactions = st.session_state.get('transactions', [])
    account_map = st.session_state.get('account_map', {})
    selected_industry = st.session_state.get('industry', 'default')
    
    # Clear analysis button
    if st.sidebar.button("🔄 New Analysis", use_container_width=True):
        del st.session_state['analysis']
        del st.session_state['account_map']
        if 'pnl_data' in st.session_state:
            del st.session_state['pnl_data']
        if 'transactions' in st.session_state:
            del st.session_state['transactions']
        if 'industry' in st.session_state:
            del st.session_state['industry']
        st.rerun()
    
    render_analysis(analysis, is_demo=False, pnl_data=pnl_data, transactions=transactions, account_map=account_map, industry=selected_industry)
    
    # Show upgrade CTA for free users
    if user and not user.get("is_pro"):
        render_upgrade_cta(user)

# Logout button in sidebar
if user:
    st.sidebar.divider()
    if st.sidebar.button("Logout", use_container_width=True):
        del st.session_state['user']
        if 'analysis' in st.session_state:
            del st.session_state['analysis']
        if 'account_map' in st.session_state:
            del st.session_state['account_map']
        st.rerun()
