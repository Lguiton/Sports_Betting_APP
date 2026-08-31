# app_ui.py
import streamlit as st
import requests

st.set_page_config(
    page_title="Sports Analytics & Betting Agent",
    page_icon="🎲",
    layout="wide"
)

API_URL = "http://localhost:8000/chat/sports"

st.sidebar.title("🎲 Sports Analytics Settings")
st.sidebar.markdown("""
**Core Capabilities:**
- **Odds Math:** American/Decimal conversion & vig removal.
- **Expected Value ($EV$):** Identifying market mispricings.
- **Bankroll Staking:** Fractional Kelly Criterion & unit sizing.
- **Predictive Models:** Poisson regression, Elo ratings, and Python scripts.
""")

if "messages" not in st.session_state:
    st.session_state.messages = []

if "thread_id" not in st.session_state:
    st.session_state.thread_id = "sports_session_1"

if st.sidebar.button("Clear Chat History"):
    st.session_state.messages = []
    st.rerun()

st.title("🎲 Sports Betting Analytics & Handicapping AI Agent")
st.caption("Evaluate lines, review handicapping models, calculate +EV, and master sports analytics.")

# Render chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# User Input
if prompt := st.chat_input("Ask a sports math question or paste a bet/model code..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Analyzing odds, $EV$, and market metrics..."):
            try:
                payload = {
                    "message": prompt,
                    "thread_id": st.session_state.thread_id
                }
                response = requests.post(API_URL, json=payload, timeout=60)
                
                if response.status_code == 200:
                    data = response.json()
                    bot_reply = data["response"]
                    st.markdown(bot_reply)
                    st.session_state.messages.append({"role": "assistant", "content": bot_reply})
                else:
                    st.error(f"❌ **Error {response.status_code}:** Unable to reach API backend.")
            except requests.exceptions.ConnectionError:
                st.error("🔌 **Connection Error:** Ensure `python app.py` is running on port 8000.")