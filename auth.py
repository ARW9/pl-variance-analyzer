"""
Authentication and payment handling
"""
import streamlit as st
from supabase import create_client
import stripe
import re

# Initialize clients
@st.cache_resource
def get_supabase():
    return create_client(
        st.secrets["supabase"]["url"],
        st.secrets["supabase"]["key"]
    )

def init_stripe():
    stripe.api_key = st.secrets["stripe"]["secret_key"]

# Constants
FREE_ANALYSES = 3
PRO_PRICE = 1000  # $10.00 in cents

def is_valid_email(email: str) -> bool:
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def get_or_create_user(email: str) -> dict:
    """Get existing user or create new one"""
    supabase = get_supabase()
    
    # Try to get existing user
    result = supabase.table("users").select("*").eq("email", email).execute()
    
    if result.data:
        return result.data[0]
    
    # Create new user
    new_user = supabase.table("users").insert({"email": email}).execute()
    return new_user.data[0]

def increment_usage(user_id: str) -> dict:
    """Increment analyses_used counter"""
    supabase = get_supabase()
    
    # Get current count
    result = supabase.table("users").select("analyses_used").eq("id", user_id).execute()
    current = result.data[0]["analyses_used"]
    
    # Increment
    updated = supabase.table("users").update(
        {"analyses_used": current + 1}
    ).eq("id", user_id).execute()
    
    return updated.data[0]

def get_usage(user_id: str) -> int:
    """Get current usage count"""
    supabase = get_supabase()
    result = supabase.table("users").select("analyses_used").eq("id", user_id).execute()
    return result.data[0]["analyses_used"] if result.data else 0

def can_analyze(user: dict) -> bool:
    """Check if user can perform analysis"""
    if user.get("is_pro"):
        return True
    return user.get("analyses_used", 0) < FREE_ANALYSES

def remaining_free(user: dict) -> int:
    """Get remaining free analyses"""
    if user.get("is_pro"):
        return float('inf')
    return max(0, FREE_ANALYSES - user.get("analyses_used", 0))

def create_checkout_session(user_email: str, user_id: str) -> str:
    """Create Stripe checkout session"""
    init_stripe()
    
    # Get or create Stripe customer
    supabase = get_supabase()
    user = supabase.table("users").select("stripe_customer_id").eq("id", user_id).execute()
    
    customer_id = user.data[0].get("stripe_customer_id") if user.data else None
    
    if not customer_id:
        customer = stripe.Customer.create(email=user_email)
        customer_id = customer.id
        supabase.table("users").update(
            {"stripe_customer_id": customer_id}
        ).eq("id", user_id).execute()
    
    # Create checkout session
    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": "P&L Variance Analyzer Pro",
                    "description": "Unlimited analyses per month",
                },
                "unit_amount": PRO_PRICE,
                "recurring": {"interval": "month"},
            },
            "quantity": 1,
        }],
        mode="subscription",
        success_url=st.secrets.get("app_url", "https://pl-variance-analyzer.streamlit.app") + "?success=true",
        cancel_url=st.secrets.get("app_url", "https://pl-variance-analyzer.streamlit.app") + "?canceled=true",
        metadata={"user_id": user_id},
    )
    
    return session.url

def upgrade_to_pro(user_id: str):
    """Mark user as pro"""
    supabase = get_supabase()
    supabase.table("users").update({"is_pro": True}).eq("id", user_id).execute()

def render_auth_ui():
    """Render login/signup UI, returns user dict if logged in"""
    
    # Check if already logged in
    if "user" in st.session_state and st.session_state.user:
        return st.session_state.user
    
    # Check for successful payment
    params = st.query_params
    if params.get("success") == "true" and "user" in st.session_state:
        upgrade_to_pro(st.session_state.user["id"])
        st.session_state.user["is_pro"] = True
        st.success("🎉 Welcome to Pro! You now have unlimited analyses.")
        st.query_params.clear()
    
    # Login form
    st.markdown("### 🔐 Sign in to continue")
    st.markdown("Enter your email to start analyzing your P&L data")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        email = st.text_input("Email address", placeholder="you@company.com", label_visibility="collapsed")
    with col2:
        login_btn = st.button("Continue", type="primary", use_container_width=True)
    
    if login_btn and email:
        if not is_valid_email(email):
            st.error("Please enter a valid email address")
            return None
        
        user = get_or_create_user(email)
        st.session_state.user = user
        st.rerun()
    
    return None

def render_usage_banner(user: dict):
    """Show usage status banner"""
    if user.get("is_pro"):
        st.success("⭐ **Pro Account** — Unlimited analyses")
    else:
        remaining = remaining_free(user)
        if remaining > 0:
            st.info(f"📊 **Free tier** — {remaining} of {FREE_ANALYSES} analyses remaining")
        else:
            st.warning("⚠️ **Free tier exhausted** — Upgrade to Pro for unlimited analyses")

def render_upgrade_cta(user: dict):
    """Show upgrade call-to-action"""
    if user.get("is_pro"):
        return
    
    st.markdown("---")
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("### 🚀 Upgrade to Pro")
        st.markdown("**$10/month** — Unlimited analyses, priority support")
    
    with col2:
        if st.button("Upgrade Now", type="primary", use_container_width=True):
            try:
                checkout_url = create_checkout_session(user["email"], user["id"])
                st.markdown(f'<meta http-equiv="refresh" content="0;url={checkout_url}">', unsafe_allow_html=True)
                st.info("Redirecting to checkout...")
            except Exception as e:
                st.error(f"Error creating checkout: {str(e)}")

def render_paywall():
    """Show paywall when free tier exhausted"""
    st.error("## 🔒 Free Analyses Used")
    st.markdown("""
    You've used all **3 free analyses**. 
    
    Upgrade to **Pro** for unlimited analyses at just **$10/month**.
    """)
    
    if st.button("🚀 Upgrade to Pro — $10/month", type="primary"):
        user = st.session_state.user
        try:
            checkout_url = create_checkout_session(user["email"], user["id"])
            st.markdown(f'<meta http-equiv="refresh" content="0;url={checkout_url}">', unsafe_allow_html=True)
            st.info("Redirecting to checkout...")
        except Exception as e:
            st.error(f"Error: {str(e)}")
