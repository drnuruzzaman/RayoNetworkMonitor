import os, sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
DB_PATH = Path(os.getenv("DB_PATH", "data/monitor.db"))
st.set_page_config(page_title="Home Network Monitor", layout="wide")
st.title("Home Network Monitor")
st.caption("DNS activity observed by AdGuard Home. Domains are not exact URLs or proof of time spent in an app.")

if not DB_PATH.exists():
    st.warning("No database yet. Start monitor.py and wait for DNS events.")
    st.stop()

con = sqlite3.connect(DB_PATH)
df = pd.read_sql_query("SELECT * FROM events ORDER BY event_time DESC", con)
con.close()
if df.empty:
    st.info("No DNS events collected yet. Confirm that devices use AdGuard Home for DNS.")
    st.stop()

df["event_time"] = pd.to_datetime(df["event_time"], utc=True, errors="coerce")
days = st.sidebar.selectbox("Reporting period", [1, 7, 14, 30], index=1)
cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
view = df[df.event_time >= cutoff].copy()
devices = sorted(view.device_name.dropna().unique().tolist())
chosen = st.sidebar.multiselect("Devices", devices, default=devices)
view = view[view.device_name.isin(chosen)]

total = len(view)
blocked = int(view.blocked.sum()) if total else 0
a,b,c,d = st.columns(4)
a.metric("DNS queries", f"{total:,}")
b.metric("Blocked queries", f"{blocked:,}")
c.metric("Devices seen", view.client_ip.nunique())
d.metric("Unique domains", view.domain.nunique())

left,right = st.columns(2)
with left:
    st.subheader("Queries by device")
    if total:
        g = view.groupby("device_name").size().reset_index(name="queries")
        st.plotly_chart(px.bar(g, x="device_name", y="queries"), use_container_width=True)
with right:
    st.subheader("Domain categories")
    if total:
        g = view.groupby("category").size().reset_index(name="queries")
        st.plotly_chart(px.pie(g, names="category", values="queries"), use_container_width=True)

st.subheader("Most requested domains")
top = view.groupby(["device_name","domain","category"]).size().reset_index(name="queries")
top = top.sort_values("queries", ascending=False).head(30)
st.dataframe(top, use_container_width=True, hide_index=True)

st.subheader("Blocked requests")
blocked_df = view[view.blocked == 1][["event_time","device_name","domain","reason"]].head(100)
st.dataframe(blocked_df, use_container_width=True, hide_index=True)

st.download_button("Download filtered events as CSV",
    view.drop(columns=["raw_json"], errors="ignore").to_csv(index=False).encode(),
    file_name=f"home-network-{days}d.csv", mime="text/csv")
