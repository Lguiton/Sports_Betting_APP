import streamlit as st
import requests
import uuid
import pandas as pd
import numpy as np

# Define the FastAPI endpoint
API_URL = "http://localhost:8000/chat/sports"

# SaaS Dashboard Page Config with Wide Layout
st.set_page_config(page_title="Quant Sports Terminal", page_icon="📈", layout="wide")

# ==========================================
# 🎨 CUSTOM CSS: NEUMORPHIC Dashboard Styling
# ==========================================
# Global styles: dark theme, rounded corners, shadows, Glassmorphism panels
st.markdown("""
<style>
    /* Global Styles */
    :root {
        --background-color: #0d1117;
        --panel-background: #161b22;
        --sidebar-background: #11141a;
        --text-color: #e6edf3;
        --primary-color: #2E86C1;
        --shadow: 10px 10px 20px #080a0e, -10px -10px 20px #121820;
    }
    
    body {
        background-color: var(--background-color);
        color: var(--text-color);
        font-family: 'Inter', sans-serif;
    }

    /* Target standard st.container to style all panels */
    div.stContainer {
        background-color: var(--panel-background);
        padding: 2rem;
        border-radius: 20px;
        box-shadow: var(--shadow);
        border: 1px solid rgba(255, 255, 255, 0.05); /* subtle edge */
        margin-bottom: 2rem;
    }

    /* Style the wide background image area */
    .wide-background-container {
        display: flex;
        flex-direction: row;
        width: 100%;
        background-image: url('https://user-images.githubusercontent.com/1324225/209930730-a92c340a-d830-47b8-8926-25f0e37b2d5a.png'); /* stylized city sunset */
        background-size: cover;
        background-position: center;
        border-radius: 20px;
        position: relative;
    }
    
    .floating-panel {
        position: absolute;
        top: 20px;
        left: 20px;
        width: calc(100% - 40px);
        background-color: rgba(22, 27, 34, 0.9); /* high opacity glass */
        padding: 20px;
        border-radius: 20px;
        z-index: 10;
        box-shadow: var(--shadow);
    }
    
    /* Right Side Panels: Mountain and Plant views with numbers */
    .right-side-panel {
        background-size: cover;
        background-position: center;
        border-radius: 20px;
        height: 250px;
        margin-bottom: 2rem;
        position: relative;
        box-shadow: var(--shadow);
    }
    
    .mountain-panel { background-image: url('https://user-images.githubusercontent.com/1324225/209930732-f3b7305a-526d-4952-b9b2-302a2a0a38b1.png'); }
    .plant-panel { background-image: url('https://user-images.githubusercontent.com/1324225/209930734-7389c922-3591-4d39-813c-747f7d3a2b0e.png'); }

    /* Performance Text Overlays */
    .panel-performance {
        position: absolute;
        top: 20px;
        left: 20px;
        color: white;
        font-weight: bold;
    }

    /* Stylized Sidebar Structure */
    .stSidebar {
        background-color: var(--sidebar-background);
        border-right: 1px solid rgba(255, 255, 255, 0.05);
    }
    
    .sidebar-profile {
        display: flex;
        align-items: center;
        gap: 15px;
        margin-bottom: 1rem;
        border-radius: 20px;
        padding: 10px;
        background: rgba(46, 134, 193, 0.1);
    }
    
    .profile-icon {
        border-radius: 50%;
        background-color: #2a3441;
        width: 50px;
        height: 50px;
        display: flex;
        justify-content: center;
        align-items: center;
    }
    
    .sidebar-nav-item {
        margin-bottom: 0.5rem;
        border-radius: 10px;
        padding: 10px;
        display: flex;
        align-items: center;
        gap: 10px;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 🎛️ SIDEBAR: STATE MANAGEMENT (RECREATED STRUCTURALLY)
# ==========================================
with st.sidebar:
    st.markdown("<div class='stContainer'>", unsafe_allow_html=True)
    st.title("⚙️ Terminal Settings")
    
    # Structural Profile and Navigation Links (Translated)
    st.markdown("""
    <div class='sidebar-profile'>
        <div class='profile-icon'>D</div>
        <div>
            <div>Dashboard</div>
            <div style='color: grey; font-size: 12px;'>User: Guito</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
    <div class='sidebar-nav-item'><div class='profile-icon'>E</div>EV Edge Finder</div>
    <div class='sidebar-nav-item'><div class='profile-icon'>R</div>Risk Portfolio</div>
    <div class='sidebar-nav-item'><div class='profile-icon'>Q</div>Quant Models</div>
    <div class='sidebar-nav-item'><div class='profile-icon'>T</div>Sports Tutor</div>
    """, unsafe_allow_html=True)
    
    st.divider()
    
    bankroll = st.number_input("Starting Bankroll ($)", min_value=100, value=1000, step=100)
    risk_tolerance = st.selectbox("Risk Strategy", ["Conservative", "Moderate", "Aggressive"])
    
    st.divider()
    st.caption("Session ID")
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = str(uuid.uuid4())[:8]
    st.code(st.session_state.thread_id)
    
    if st.button("Clear Conversation"):
        st.session_state.messages = []
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

# ==========================================
# 📊 MAIN DASHBOARD: BI ANALYTICS (OVERHAULED STRUCTURE)
# ==========================================
st.title("📈 Quant Sports Betting Dashboard")

# Top KPI Metric Cards (Moved to top of central area)
st.markdown("<div class='stContainer'>", unsafe_allow_html=True)
col1, col2, col3 = st.columns(3)
with col1:
    st.metric(label="Active Bankroll", value=f"${bankroll:,.2f}", delta="Ready to deploy")
with col2:
    st.metric(label="Active Risk Profile", value=risk_tolerance)
with col3:
    st.metric(label="Agent Status", value="Online", delta="Connected")
st.markdown("</div>", unsafe_allow_html=True)


# Main BI Visualizations and Agent Control Center
# Structure based on reference: Large central floating panel + right performance panels
main_col1, main_col2, main_col3 = st.columns([2, 2, 1])

with main_col1: # Left Central Area: Variance and Detailed Stats
    st.markdown("<div class='stContainer'>", unsafe_allow_html=True)
    st.subheader("Simulated 30-Day Variance Projection")
    st.caption("Visualizing expected volatility based on selected risk strategy.")
    
    # Generate random walk to visualize risk volatility (reuse logic)
    np.random.seed(42)
    volatility = {"Conservative": 0.02, "Moderate": 0.05, "Aggressive": 0.10}[risk_tolerance]
    days = pd.date_range(start=pd.Timestamp.today(), periods=30)
    returns = np.random.normal(0.001, volatility, 30)
    cumulative_returns = bankroll * (1 + returns).cumprod()
    
    chart_data = pd.DataFrame({"Projected Bankroll": cumulative_returns}, index=days)
    # Area Chart placement from reference
    st.area_chart(chart_data, color="#2E86C1")
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Detailed Stats panel (Middle Left of reference)
    st.markdown("<div class='stContainer'>", unsafe_allow_html=True)
    st.subheader("Detailed Performance Stats")
    # Structural numbers based on reference (conceptual data points)
    st.markdown("""
        <div>Active Units: 4.19</div>
        <div>Model Coverage: 74%</div>
        <div>Tutor Session Time: 3:00</div>
        <div>Total Edges Found: 490</div>
    """, unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

with main_col2: # Middle Central Area: EV Edge Finder (Wide Floating Panel)
    st.markdown("<div class='stContainer'>", unsafe_allow_html=True)
    
    # Recreate the main Wide-Format Background Area from reference
    st.markdown("<div class='wide-background-container'>", unsafe_allow_html=True)
    # This empty div creates the background. The floating panels go on top.
    
    # Top Left Panel (EV edge)
    st.markdown("""
    <div class='floating-panel'>
        <div style='font-size: 1.5rem;'>📈 Market Conversion</div>
        <div>Implied Prob. - BLZMANN: 49.0%</div>
        <div>Decimal Odds - CAGT: +110</div>
        <div style='font-size: 1.2rem; margin-top: 10px;'>Recommended EV%: 1.09%</div>
    </div>
    """, unsafe_allow_html=True)
    
    # Top Mid Panels (conceptual statistics)
    # Structure of 1, 099 mapped to edge count and probability delta.
    st.markdown("""
    <div style='position: absolute; top: 150px; left: 20px; color: white;'>
        <div>Edges Found: 1</div>
        <div>Implied Delta: 0.99</div>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("</div>", unsafe_allow_html=True) # End of wide-background-container
    
    # Lower Central panels from reference (detailed stats)
    st.markdown("<div style='margin-top: 2rem;'>", unsafe_allow_html=True)
    # Map numbers based on reference structure
    st.markdown("""
        <div>Edges Identified: 37</div>
        <div>Units Recommended: 6.06</div>
        <div>Variance Delta: 1.0</div>
    """, unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


with main_col3: # Right Side Area: Performance Metrics and Agent Command Center
    
    # Top Panel: Mountain scene, metrics from 29, 11:19 mapping
    st.markdown("<div class='right-side-panel mountain-panel'>", unsafe_allow_html=True)
    st.markdown("<div class='panel-performance'>", unsafe_allow_html=True)
    # Structural Mapping from 29 and 11:19
    st.markdown("""
        <div>PNL: $29</div>
        <div>Monthly Performance: +11.19%</div>
    """, unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Bottom Panel: Plant scene, Agent Command Center (the chat window)
    st.markdown("<div class='right-side-panel plant-panel'>", unsafe_allow_html=True)
    st.markdown("<div class='panel-performance'>", unsafe_allow_html=True)
    # Structured Mapping from stylized performance
    st.markdown("""
        <div>Active Unit size: $25.00</div>
        <div>Strategy Confidence: 99.1%</div>
    """, unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    
    # 💬 AGENT COMMAND CENTER (Re-integrating the actual chat)
    # Must be placed OUTSIDE the plant panel container to function correctly in standard Streamlit
    st.markdown("<div class='stContainer'>", unsafe_allow_html=True)
    st.subheader("Agent Command Center")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Display chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input block
    if prompt := st.chat_input("E.g., What is my recommended unit size based on my bankroll?"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            message_placeholder.markdown("*(Analyzing market data...)*")
            
            try:
                # Full Stack connection: Passing UI state to the Backend API
                payload = {
                    "message": prompt,
                    "thread_id": st.session_state.thread_id,
                    "bankroll": bankroll,
                    "risk_profile": risk_tolerance
                }
                
                response = requests.post(API_URL, json=payload)
                response.raise_for_status() 
                
                answer = response.json().get("response", "Error: No response generated.")
                message_placeholder.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
                
            except requests.exceptions.RequestException as e:
                error_msg = f"Error connecting to backend: {e}"
                message_placeholder.markdown(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
    st.markdown("</div>", unsafe_allow_html=True)
