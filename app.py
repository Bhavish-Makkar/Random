import streamlit as st
import requests
 
# ─── CONFIG (HIDDEN) ─────────────────────────────────────────────
TENANT_ID = 
CLIENT_ID = ""
CLIENT_SECRET = 
 
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
 
AGENT_URL ="https://ai-foundry-ops-dev.services.ai.azure.com/api/projects/proj-ops-dev/applications/CREW-RAG/protocols/openai/responses?api-version=2025-11-15-preview"
 
# ─── SESSION STATE INIT ──────────────────────────────────────────
if "access_token" not in st.session_state:
    st.session_state.access_token = None
 
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
def extract_assistant_text(response_json: dict) -> str:
    """
    Extract ONLY the final assistant message text
    from Azure AI Foundry Responses API output.
    """
    for item in response_json.get("output", []):
        if item.get("type") == "message" and item.get("role") == "assistant":
            for block in item.get("content", []):
                if block.get("type") == "output_text":
                    return block.get("text", "").strip()

    return "⚠️ No valid response returned by agent."
# ─── TITLE ───────────────────────────────────────────────────────
st.title("✈️ CREW-RAG AI Assistant")
 
# ─── AUTH BUTTON ─────────────────────────────────────────────────
if st.button("🔐 Authenticate"):
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials",
        "scope": "https://ai.azure.com/.default"
    }


    try:
        resp = requests.post(TOKEN_URL, data=data)
        resp.raise_for_status()
 
        st.session_state.access_token = resp.json()["access_token"]
        st.success("✅ Authenticated Successfully!")
 
    except Exception as e:
        st.error(f"❌ Auth Failed: {e}")
 
# ─── CHAT DISPLAY ────────────────────────────────────────────────
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
 
# ─── CHAT INPUT ──────────────────────────────────────────────────
user_input = st.chat_input("Type your message...")
 
if user_input:
    # 1. Show user message
    st.session_state.chat_history.append({
        "role": "user",
        "content": user_input
    })
 
    # 2. Call agent
    if st.session_state.access_token:
        headers = {
            "Authorization": f"Bearer {st.session_state.access_token}",
            "Content-Type": "application/json"
        }
 
        payload = {
            "input": user_input
        }
 
        try:
            
            response = requests.post(AGENT_URL, headers=headers, json=payload)
            response.raise_for_status()

            response_json = response.json()
            bot_reply = extract_assistant_text(response_json)

            
        except Exception as e:
            bot_reply = f"Error: {e}"
 
    else:
        bot_reply = "⚠️ Please authenticate first."
 
    # 3. Show bot reply
    st.session_state.chat_history.append({
        "role": "assistant",
        "content": bot_reply
    })
 
    # 4. Rerun to clear input automatically
    st.rerun()
