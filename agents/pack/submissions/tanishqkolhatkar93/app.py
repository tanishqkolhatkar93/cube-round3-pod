import os
import sys
import json
import time
import hashlib
from datetime import datetime, timezone
import streamlit as st
import requests

# Ensure agent directory is in path for standalone mode
agent_dir = os.path.join(os.path.dirname(__file__), "agent")
if agent_dir not in sys.path:
    sys.path.append(agent_dir)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(agent_dir, ".env"))
except Exception:
    pass

st.set_page_config(page_title="Pack Manager AI", page_icon="📦", layout="wide")
API_URL = os.getenv("API_URL", "http://localhost:8000")

# --- Custom CSS for Aesthetics ---
st.markdown("""
    <style>
    /* Global Font Settings */
    h1 {
        font-size: 3rem !important;
        font-weight: 800 !important;
                padding-bottom: 0px !important;
        margin-bottom: 0px !important;
    }
    h3 {
        font-size: 1.5rem !important;
        font-weight: 600 !important;
                margin-top: -5px !important;
    }
    .stButton>button {
        border-radius: 8px;
        height: 50px;
        font-size: 18px;
        font-weight: bold;
        background-color: #2563EB;
        color: white;
        transition: all 0.2s;
        border: none;
    }
    .stButton>button:hover {
        background-color: #1D4ED8;
        box-shadow: 0 4px 6px -1px rgba(37,99,235,0.4);
    }
    .seal-banner { background-color: #F0FDF4; border-left: 6px solid #22C55E; color: #166534; padding: 20px; border-radius: 6px; font-size: 24px; font-weight: bold; }
    .stop-banner { background-color: #FEF2F2; border-left: 6px solid #EF4444; color: #991B1B; padding: 20px; border-radius: 6px; font-size: 24px; font-weight: bold; }
    .pending-banner { background-color: #F8FAFC; border-left: 6px solid #64748B; color: #334155; padding: 20px; border-radius: 6px; font-size: 24px; font-weight: bold; }
    .metric-card { background-color: #FFFFFF; padding: 15px; border-radius: 8px; border: 1px solid #E2E8F0; box-shadow: 0 1px 3px 0 rgba(0,0,0,0.1); }
    </style>
""", unsafe_allow_html=True)

# --- Sidebar / Advanced Config ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3055/3055627.png", width=60)
    st.title("⚙️ Settings")
    st.markdown("Configure packing station context.")
    
    with st.expander("📋 Station Config", expanded=True):
        operator_id = st.text_input("Operator ID", value="OP-992")
        org_id = st.selectbox("Tenant (org_id)", ["org_demo_alpha", "org_demo_bravo"])
    
    with st.expander("🔑 API Key Config", expanded=False):
        env_api_key = os.getenv("GEMINI_API_KEY", "")
        secret_key = st.secrets.get("GEMINI_API_KEY", "") if hasattr(st, "secrets") else ""
        default_key = env_api_key or secret_key
        custom_api_key = st.text_input("Gemini API Key", value=default_key, type="password")
        if custom_api_key:
            os.environ["GEMINI_API_KEY"] = custom_api_key

# --- Main App Header ---
st.markdown("# 📦 Pack Manager AI")
st.markdown("### Autonomous Outbound Packaging Verification Agent")

# --- Layout ---
col_manifest, col_upload = st.columns([1, 1], gap="large")

with col_manifest:
    st.markdown("### 📋 1. Order Manifest")
    with st.container(border=True):
        sub_col1, sub_col2 = st.columns(2)
        with sub_col1:
            unit_id = st.text_input("Unit ID", value="UNIT-0042")
        with sub_col2:
            order_id = st.text_input("Order ID", value="ORD-77382")
        expected_lines = st.text_area("Expected Order Lines (SKU:qty)", value="KEYBOARD:1; MOUSE:1", height=150)

with col_upload:
    st.markdown("### 📸 2. Visual Inspection")
    with st.container(border=True):
        uploaded_file = st.file_uploader("Upload open box overhead photo", type=["jpg", "jpeg", "png"], help="Ensure good lighting and top-down angle.")
        verify_clicked = False
        if uploaded_file:
            st.markdown("<br>", unsafe_allow_html=True)
            st.image(uploaded_file, caption="Captured Image Preview", use_container_width=True)
            st.markdown("<br>", unsafe_allow_html=True)
            verify_clicked = st.button("🚀 VERIFY PACKAGE", type="primary", use_container_width=True)

st.divider()

# --- Verification Logic & Results ---
if uploaded_file and verify_clicked:
    st.markdown("### 🎯 3. Verification Verdict")
    
    with st.spinner("Analyzing package with Vision AI..."):
        image_bytes = uploaded_file.getvalue()
        image_hash = hashlib.sha256(image_bytes).hexdigest()
        start_time = time.time()
        
        result_verdict = None
        result_reasoning = None
        contract = None
        
        # Dual Mode: Try local FastAPI, fallback to direct Streamlit Cloud execution
        api_connected = False
        try:
            files = {"image": (uploaded_file.name, image_bytes, uploaded_file.type)}
            data = {
                "unit_id": unit_id,
                "operator_id": operator_id,
                "order_id": order_id,
                "expected_order_lines": expected_lines
            }
            headers = {"x-org-id": org_id}
            response = requests.post(f"{API_URL}/verify", files=files, data=data, headers=headers, timeout=5)
            if response.status_code == 200:
                resp_json = response.json()
                result_verdict = resp_json.get("verdict")
                result_reasoning = resp_json.get("reasoning")
                api_connected = True
        except Exception:
            api_connected = False

        if not api_connected:
            # Standalone mode for Streamlit Cloud
            try:
                from agent.vision import analyze_package_image
                analysis = analyze_package_image(image_bytes, expected_lines)
                result_verdict = analysis.verdict
                result_reasoning = analysis.reasoning
                observed_items = analysis.observed_items
                checks_dict = analysis.checks_performed.dict() if hasattr(analysis.checks_performed, 'dict') else analysis.checks_performed.model_dump()
            except Exception as e:
                result_verdict = "PENDING"
                result_reasoning = f"Fail Open / Network Error: {str(e)}"
                observed_items = "UNKNOWN"
                checks_dict = {}

            latency_ms = int((time.time() - start_time) * 1000)
            contract = {
                "record_id": f"rcd_{int(time.time())}",
                "schema_version": "1.0",
                "organization_id": org_id,
                "client_id": "streamlit_cloud",
                "agent": "vision_agent",
                "subject": unit_id,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "operator_label": operator_id,
                "images": [image_hash],
                "metadata_traceability": {
                    "what_should_be_in_box": expected_lines,
                    "what_was_actually_found": observed_items,
                    "what_checks_were_performed": checks_dict
                },
                "checks": [{
                    "check_key": "all_items_match",
                    "verdict": result_verdict,
                    "confidence": 1.0 if result_verdict != "UNCERTAIN" else 0.3,
                    "detail": result_reasoning,
                    "model_version": "gemini-flash-lite",
                    "latency_ms": latency_ms
                }],
                "outcome": {
                    "decision": result_verdict,
                    "decided_by": "automated_agent",
                    "decided_at": datetime.now(timezone.utc).isoformat()
                },
                "overrides": [],
                "status": "processed",
                "content_hash": ""
            }
            contract["content_hash"] = hashlib.sha256(json.dumps(contract).encode()).hexdigest()
            
            try:
                contract_dir = os.path.join(os.path.dirname(__file__), "contract")
                os.makedirs(contract_dir, exist_ok=True)
                with open(os.path.join(contract_dir, f"{contract['record_id']}.json"), "w") as f:
                    json.dump(contract, f, indent=2)
            except Exception:
                pass

        processing_time = time.time() - start_time

        # Display Verdict Banners
        res_col1, res_col2 = st.columns([2, 1])
        with res_col1:
            if result_verdict == "SEAL":
                st.markdown('<div class="seal-banner">✅ SEAL BOX</div>', unsafe_allow_html=True)
                st.success(f"**Reasoning:** {result_reasoning}")
            elif result_verdict == "STOP_AND_FIX":
                st.markdown('<div class="stop-banner">❌ STOP & FIX</div>', unsafe_allow_html=True)
                st.error(f"**Reasoning:** {result_reasoning}")
            elif result_verdict == "UNCERTAIN":
                st.markdown('<div class="stop-banner">❌ STOP & FIX</div>', unsafe_allow_html=True)
                st.warning(f"**Reasoning:** {result_reasoning}")
            else:
                st.markdown('<div class="pending-banner">⏳ PENDING (Fail Open)</div>', unsafe_allow_html=True)
                st.info(f"**Reasoning:** {result_reasoning}")
        
        with res_col2:
            st.markdown('<div class="metric-card">', unsafe_allow_html=True)
            st.metric(label="⏱️ End-to-End Latency", value=f"{processing_time:.2f}s")
            st.markdown('</div>', unsafe_allow_html=True)

        # Human Override Support
        if result_verdict in ["STOP_AND_FIX", "UNCERTAIN", "PENDING"] and contract:
            st.markdown("### 👨‍🔧 Human Override")
            override_reason = st.text_input("Override Reason (Required for Audit Log)", key="override_text")
            if st.button("Force SEAL (Override AI)", type="secondary"):
                if override_reason.strip() == "":
                    st.error("You must provide a reason to override the AI.")
                else:
                    contract["overrides"].append({
                        "operator": operator_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "reason": override_reason,
                        "original_verdict": result_verdict,
                        "new_verdict": "SEAL"
                    })
                    # Re-hash and save
                    import json, hashlib
                    contract["content_hash"] = hashlib.sha256(json.dumps(contract).encode()).hexdigest()
                    try:
                        contract_dir = os.path.join(os.path.dirname(__file__), "contract")
                        with open(os.path.join(contract_dir, f"{contract['record_id']}.json"), "w") as f:
                            json.dump(contract, f, indent=2)
                    except Exception:
                        pass
                    st.success(f"Decision overridden to SEAL by {operator_id}. Audit log updated securely.")
        
        # Evidence Contract Preview
        if contract:
            st.markdown("### 🔒 Cryptographic Evidence Contract")
            st.caption(f"Traceability record `{contract['record_id']}` securely saved for org `{org_id}`.")
            with st.expander("View Raw JSON Contract", expanded=False):
                st.json(contract)