import streamlit as st
import requests
from datetime import datetime
 
# ─── Page Config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CREW-RAG | IndiGo AI Assistant",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded",
)
 
# ─── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&display=swap%27);
 
    html, body, [class*="css"] {
        font-family: 'DM Sans', sans-serif;
    }
 
    .stApp {
        background: #0a0e1a;
        color: #e8eaf0;
    }
 
    [data-testid="stSidebar"] {
        background: #0f1422 !important;
        border-right: 1px solid #1e2538;
    }
 
    .main-header {
        font-family: 'Syne', sans-serif;
        font-size: 2rem;
        font-weight: 800;
        background: linear-gradient(135deg, #00c6ff, #0072ff, #7b2ff7);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
 
    .sub-header {
        font-size: 0.85rem;
        color: #5a6380;
        text-transform: uppercase;
        letter-spacing: 1.5px;
    }
 
    .user-msg {
        background: linear-gradient(135deg, #1a2040, #1e2a50);
        border-radius: 16px 16px 4px 16px;
        padding: 14px;
        margin: 8px 0 8px 20%;
        color: #c8d0e8;
    }
 
    .agent-msg {
        background: linear-gradient(135deg, #111827, #161e30);
        border-left: 3px solid #0072ff;
        border-radius: 4px 16px 16px 16px;
        padding: 14px;
        margin: 8px 10% 8px 0;
        color: #d4d8e8;
    }
 
    .msg-label {
        font-size: 0.7rem;
        font-weight: 700;
        text-transform: uppercase;
        margin-bottom: 6px;
        letter-spacing: 1.5px;
    }
 
    .msg-time {
        font-size: 0.65rem;
        color: #3a4060;
        margin-top: 6px;
        text-align: right;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
 
# ─── Auth & API Helpers ─────────────────────────────────────────────────────────
def get_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
        "scope": "https://ai.azure.com/.default",
    }
    response = requests.post(url, data=data)
    response.raise_for_status()
    return response.json()["access_token"]
 
 
def call_agent(token: str, endpoint: str, user_input: str) -> str:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
 
    payload = {"input": user_input}
    resp = requests.post(endpoint, headers=headers, json=payload)
    resp.raise_for_status()
 
    result = resp.json()
 
    # ✅ Responses API → assistant text lives in result["output"]
    output_items = result.get("output", [])
 
    for item in output_items:
        if item.get("type") == "message" and item.get("role") == "assistant":
            for block in item.get("content", []):
                if block.get("type") == "output_text":
                    return block.get("text", "").strip()
 
    return "⚠️ No valid response returned by agent."
 
 
 
# ─── Session State ─────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
 
if "token" not in st.session_state:
    st.session_state.token = None
 
if "total_queries" not in st.session_state:
    st.session_state.total_queries = 0
 
# ─── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ✈️ CREW‑RAG")
    st.markdown("**Azure AI Foundry Agent**")
 
    tenant_id = st.text_input("Tenant ID")
    client_id = st.text_input("Client ID")
    client_secret = st.text_input("Client Secret", type="password")
    endpoint = st.text_input("Agent Endpoint URL")
 
    if st.button("🔐 Authenticate", use_container_width=True):
        try:
            st.session_state.token = get_token(
                tenant_id, client_id, client_secret
            )
            st.success("Authenticated")
        except Exception as e:
            st.error(e)
 
    if st.button("🗑 Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
 
# ─── Main Content ──────────────────────────────────────────────────────────────
st.markdown('<div class="main-header">CREW‑RAG Agent</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">IndiGo · Azure AI Foundry · Flight Operations</div>', unsafe_allow_html=True)
st.markdown("---")
 
# Chat History
for msg in st.session_state.messages:
    html = f"""
    <div class="{ 'user-msg' if msg['role']=='user' else 'agent-msg' }">
        <div class="msg-label">{ 'You' if msg['role']=='user' else '✈ CREW‑RAG' }</div>
        {msg['content']}
        <div class="msg-time">{msg['time']}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)
 
# Input
 
def clear_input():
    st.session_state.user_input = ""
 
user_input = st.text_area(
    "Message",
    placeholder="Ask CREW‑RAG about flight ops, crew duty, DGCA...",
    height=80,
    label_visibility="collapsed",
    key="user_input",
)
 
 
if st.button("Send ➤") and user_input.strip():
    if not st.session_state.token:
        st.error("⚠ Authenticate first")
    else:
        now = datetime.now().strftime("%H:%M")
 
        # Add user message
        st.session_state.messages.append({
            "role": "user",
            "content": user_input.strip(),
            "time": now,
        })
 
        with st.spinner("CREW‑RAG is thinking..."):
            response = call_agent(
                token=st.session_state.token,
                endpoint=endpoint,
                user_input=user_input.strip(),
            )
 
        formatted = response.replace("\n", "<br>")
 
        # Add assistant message
        st.session_state.messages.append({
            "role": "assistant",
            "content": formatted,
            "time": now,
        })
 
        st.session_state.total_queries += 1
 
        # ✅ CLEAR INPUT BOX
        clear_input()
 
        # ✅ RERUN UI
        st.rerun()
