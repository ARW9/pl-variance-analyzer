"""
Authentication and payment handling
"""
import streamlit as st
from supabase import create_client
import stripe
import resend
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

def generate_verification_code() -> str:
    """Generate a 6-digit verification code"""
    import random
    return str(random.randint(100000, 999999))

def send_verification_email(email: str, code: str) -> bool:
    """Send verification code via email using Resend"""
    try:
        # Store code in database for verification
        try:
            supabase = get_supabase()
            supabase.table("pending_verifications").upsert({
                "email": email,
                "code": code,
            }).execute()
        except Exception:
            pass
        
        # Send email via Resend
        resend.api_key = st.secrets["resend"]["api_key"]
        resend.Emails.send({
            "from": "P&L Analyzer <onboarding@resend.dev>",
            "to": email,
            "subject": "Your verification code",
            "html": f"""
                <div style="font-family: sans-serif; max-width: 400px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #dc2626;">P&L Variance Analyzer</h2>
                    <p>Your verification code is:</p>
                    <p style="font-size: 32px; font-weight: bold; letter-spacing: 4px; color: #171717;">{code}</p>
                    <p style="color: #666; font-size: 14px;">This code expires in 10 minutes.</p>
                </div>
            """
        })
        return True
    except Exception as e:
        st.error(f"Failed to send email: {e}")
        return False

def verify_code(email: str, code: str) -> bool:
    """Verify the code matches what was sent"""
    try:
        supabase = get_supabase()
        result = supabase.table("pending_verifications").select("code").eq("email", email).execute()
        
        if result.data and result.data[0]["code"] == code:
            # Delete the used code
            supabase.table("pending_verifications").delete().eq("email", email).execute()
            return True
        return False
    except:
        return False

def get_or_create_user(email: str) -> dict:
    """Get existing user or create new one (only called after verification)"""
    supabase = get_supabase()
    
    # Try to get existing user
    result = supabase.table("users").select("*").eq("email", email).execute()
    
    if result.data:
        return result.data[0]
    
    # Create new user (email already verified at this point)
    new_user = supabase.table("users").insert({
        "email": email,
        "email_verified": True
    }).execute()
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
    try:
        init_stripe()
    except Exception as e:
        raise Exception("Stripe not configured. Please contact support to upgrade.")
    
    try:
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
                        "description": "Unlimited uploads per month",
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
    except Exception as e:
        raise Exception(f"Payment setup error: {str(e)}")

def upgrade_to_pro(user_id: str):
    """Mark user as pro"""
    supabase = get_supabase()
    supabase.table("users").update({"is_pro": True}).eq("id", user_id).execute()

def render_auth_ui():
    """Render login/signup UI with email verification, returns user dict if logged in"""
    
    # Check URL params for logout
    params = st.query_params
    if params.get("logout") == "true":
        for key in ["user", "pending_email", "verification_code"]:
            if key in st.session_state:
                del st.session_state[key]
        st.query_params.clear()
        st.rerun()
    
    # Check if already logged in
    if "user" in st.session_state and st.session_state.user:
        return st.session_state.user
    
    # Check for successful payment
    params = st.query_params
    if params.get("success") == "true" and "user" in st.session_state:
        upgrade_to_pro(st.session_state.user["id"])
        st.session_state.user["is_pro"] = True
        st.success("🎉 Welcome to Pro! You now have unlimited uploads.")
        st.query_params.clear()
    
    # Check if we're in verification mode
    if "pending_email" in st.session_state:
        email = st.session_state.pending_email
        st.markdown("### ✉️ Check your email")
        st.markdown(f"We sent a verification code to **{email}**")
        
        col1, col2 = st.columns([3, 1])
        with col1:
            code_input = st.text_input("Enter 6-digit code", placeholder="123456", max_chars=6, label_visibility="collapsed")
        with col2:
            verify_btn = st.button("Verify", type="primary", use_container_width=True)
        
        col3, col4 = st.columns(2)
        with col3:
            if st.button("← Change email"):
                del st.session_state.pending_email
                if "verification_code" in st.session_state:
                    del st.session_state.verification_code
                st.rerun()
        with col4:
            if st.button("Resend code"):
                code = generate_verification_code()
                st.session_state.verification_code = code  # For dev mode
                send_verification_email(email, code)
                st.success("New code sent!")
        
        if verify_btn and code_input:
            # Check against stored code (dev mode) or database
            stored_code = st.session_state.get("verification_code")
            if stored_code and code_input == stored_code:
                # Verification successful
                user = get_or_create_user(email)
                st.session_state.user = user
                del st.session_state.pending_email
                del st.session_state.verification_code
                st.rerun()
            elif verify_code(email, code_input):
                # Database verification successful
                user = get_or_create_user(email)
                st.session_state.user = user
                del st.session_state.pending_email
                st.rerun()
            else:
                st.error("Invalid code. Please try again.")
        
        return None
    
    # Initial email entry form
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
        
        # Generate and send verification code
        code = generate_verification_code()
        st.session_state.pending_email = email
        st.session_state.verification_code = code  # For dev mode - remove in production
        send_verification_email(email, code)
        st.rerun()
    
    return None

def render_usage_banner(user: dict):
    """Show usage status banner"""
    if user.get("is_pro"):
        st.success("⭐ **Pro Account** — Unlimited uploads")
    else:
        remaining = remaining_free(user)
        if remaining > 0:
            st.info(f"📊 **Free tier** — {remaining} of {FREE_ANALYSES} uploads remaining")
        else:
            st.warning("⚠️ **Free tier exhausted** — Upgrade to Pro for unlimited uploads")

def render_upgrade_cta(user: dict):
    """Show upgrade call-to-action"""
    if user.get("is_pro"):
        return
    
    st.markdown("---")
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("### 🚀 Upgrade to Pro")
        st.markdown("**$10/month** — Unlimited uploads, priority support")
    
    with col2:
        if st.button("Upgrade Now", type="primary", use_container_width=True):
            try:
                checkout_url = create_checkout_session(user["email"], user["id"])
                st.components.v1.html(f'<script>window.open("{checkout_url}", "_blank");</script>', height=0)
            except Exception as e:
                st.error(f"Error creating checkout: {str(e)}")

def render_paywall():
    """Show paywall when free tier exhausted"""
    st.error("## 🔒 Free Analyses Used")
    st.markdown("""
    You've used all **3 free uploads**. 
    
    Upgrade to **Pro** for unlimited uploads at just **$10/month**.
    """)
    
    if st.button("🚀 Upgrade to Pro — $10/month", type="primary"):
        user = st.session_state.user
        try:
            checkout_url = create_checkout_session(user["email"], user["id"])
            st.components.v1.html(f'<script>window.open("{checkout_url}", "_blank");</script>', height=0)
        except Exception as e:
            st.error(f"Error: {str(e)}")
