"""Streamlit dashboard for the AI Investment Agent.

Run with:
    streamlit run src/dashboard/app.py
"""

import streamlit as st
import pandas as pd

from src.db.operations import init_db
from src.dashboard.data_loader import (
    load_portfolio_summary,
    load_ticker_detail,
    load_risk_report,
)
from src.config import WATCHLIST, WATCH_ONLY

# --- Page Config ---

st.set_page_config(
    page_title="AI Investment Agent",
    page_icon="📊",
    layout="wide",
)

# Initialize DB on first load
init_db()


# --- Sidebar Navigation ---

st.sidebar.title("AI Investment Agent")

all_tickers = list(WATCHLIST.keys()) + list(WATCH_ONLY.keys())
view = st.sidebar.radio("View", ["Portfolio Overview", "Stock Detail"])

selected_ticker = None
if view == "Stock Detail":
    selected_ticker = st.sidebar.selectbox("Select Ticker", all_tickers)


# ============================================================
# PORTFOLIO OVERVIEW
# ============================================================

if view == "Portfolio Overview":
    st.title("Portfolio Overview")

    # --- Signal Summary Table ---
    st.header("Signal Summary")

    summaries = load_portfolio_summary()

    if not summaries:
        st.info("No data yet. Run the orchestrated pipeline first: "
                "`python -m src.agents.runner --all --orchestrate`")
    else:
        # Split into active and watch-only
        active = [s for s in summaries if s["tier"] > 0]
        watch_only = [s for s in summaries if s["tier"] == 0]

        if active:
            # Build table data
            table_data = []
            for s in active:
                table_data.append({
                    "Ticker": s["ticker"],
                    "Name": s["name"],
                    "Layer": s["layer"],
                    "Tier": s["tier"],
                    "Signal": s["signal"].upper() if s["signal"] else "—",
                    "Confidence": f"{s['confidence']:.0%}" if s["confidence"] is not None else "—",
                    "Recommendation": (s["recommendation"] or "—")[:80],
                    "Date": s["report_date"] or "—",
                })

            df = pd.DataFrame(table_data)
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Ticker": st.column_config.TextColumn(width="small"),
                    "Tier": st.column_config.NumberColumn(width="small"),
                    "Signal": st.column_config.TextColumn(width="small"),
                    "Confidence": st.column_config.TextColumn(width="small"),
                    "Recommendation": st.column_config.TextColumn(width="large"),
                },
            )

            # Signal distribution
            signals = [s["signal"] for s in active if s["signal"]]
            if signals:
                col1, col2, col3 = st.columns(3)
                bullish_count = sum(1 for s in signals if s == "bullish")
                bearish_count = sum(1 for s in signals if s == "bearish")
                neutral_count = sum(1 for s in signals if s == "neutral")
                col1.metric("Bullish", bullish_count)
                col2.metric("Neutral", neutral_count)
                col3.metric("Bearish", bearish_count)

        if watch_only:
            st.subheader("Watch Only")
            watch_data = []
            for s in watch_only:
                watch_data.append({
                    "Ticker": s["ticker"],
                    "Name": s["name"],
                    "Layer": s["layer"],
                    "Signal": s["signal"].upper() if s["signal"] else "—",
                    "Confidence": f"{s['confidence']:.0%}" if s["confidence"] is not None else "—",
                })
            st.dataframe(pd.DataFrame(watch_data), use_container_width=True, hide_index=True)

    # --- Risk Report ---
    st.header("Portfolio Risk")

    risk = load_risk_report()

    if risk is None:
        st.info("No risk report yet. Run: `python -m src.agents.runner --risk`")
    else:
        # Risk level + summary
        col1, col2 = st.columns([1, 3])
        with col1:
            st.metric("Risk Level", risk["overall_risk_level"].upper())
        with col2:
            st.write(risk["risk_summary"])

        # Sector exposure chart
        if risk["sector_exposure"]:
            st.subheader("Sector Exposure")
            exposure_df = pd.DataFrame(
                [{"Sector": k, "Weight": v} for k, v in risk["sector_exposure"].items()]
            ).sort_values("Weight", ascending=True)

            st.bar_chart(
                exposure_df.set_index("Sector"),
                horizontal=True,
            )

        # Warnings and flags
        warn_col, corr_col = st.columns(2)

        with warn_col:
            if risk["concentration_warnings"]:
                st.subheader("Concentration Warnings")
                for w in risk["concentration_warnings"]:
                    st.warning(w)

        with corr_col:
            if risk["correlation_flags"]:
                st.subheader("Correlation Flags")
                for flag in risk["correlation_flags"]:
                    st.warning(flag)

        # Position sizing
        if risk["position_sizing"]:
            st.subheader("Position Sizing")
            sizing_data = []
            for ticker, sizing in sorted(risk["position_sizing"].items()):
                alloc = sizing.get("max_allocation")
                reason = sizing.get("reason", "")
                sizing_data.append({
                    "Ticker": ticker,
                    "Max Allocation": f"{alloc:.0%}" if isinstance(alloc, (int, float)) else str(alloc),
                    "Reason": reason,
                })
            st.dataframe(pd.DataFrame(sizing_data), use_container_width=True, hide_index=True)

        # Recommendations
        if risk["recommendations"]:
            st.subheader("Recommendations")
            for r in risk["recommendations"]:
                st.write(f"- {r}")

        st.caption(f"Report date: {risk['report_date']}")


# ============================================================
# STOCK DETAIL VIEW
# ============================================================

elif view == "Stock Detail" and selected_ticker:
    detail = load_ticker_detail(selected_ticker)

    # Header
    tier_label = f"Tier {detail['tier']}" if detail["tier"] > 0 else "Watch Only"
    st.title(f"{detail['ticker']} — {detail['name']}")
    st.caption(f"{detail['layer']} | {tier_label}")

    # Price info
    if detail["price"]:
        p = detail["price"]
        price_cols = st.columns(4)
        price_cols[0].metric("Latest Close", f"${p['latest_close']:.2f}")
        if p["high_52w"]:
            price_cols[1].metric("52W High", f"${p['high_52w']:.2f}")
        if p["low_52w"]:
            price_cols[2].metric("52W Low", f"${p['low_52w']:.2f}")
        if p["high_52w"] and p["low_52w"] and p["high_52w"] != p["low_52w"]:
            range_pct = (p["latest_close"] - p["low_52w"]) / (p["high_52w"] - p["low_52w"])
            price_cols[3].metric("52W Range Position", f"{range_pct:.0%}")

    # --- Synthesis Signal ---
    st.header("Synthesis")

    if detail["synthesis"] is None:
        st.info(f"No synthesis report for {selected_ticker}. Run: "
                f"`python -m src.agents.runner {selected_ticker} --orchestrate`")
    else:
        synth = detail["synthesis"]

        # Signal card
        sig_col, conf_col, agree_col = st.columns(3)
        sig_col.metric("Signal", synth["overall_signal"].upper() if synth["overall_signal"] else "—")
        conf_col.metric("Confidence", f"{synth['overall_confidence']:.0%}" if synth["overall_confidence"] is not None else "—")
        agree_col.metric("Agreement", synth["analyst_agreement"] or "—")

        # Recommendation
        st.subheader("Recommendation")
        st.write(synth["recommendation"])

        # Bull / Bear
        bull_col, bear_col = st.columns(2)
        with bull_col:
            st.subheader("Bull Case")
            st.write(synth["bull_case_summary"])
        with bear_col:
            st.subheader("Bear Case")
            st.write(synth["bear_case_summary"])

        # Thesis change alert
        if synth["thesis_changed_since_last"]:
            st.error("THESIS CHANGE DETECTED — review the latest analysis carefully.")

        # Disagreements
        if synth["disagreement_flags"]:
            st.subheader("Disagreements")
            for d in synth["disagreement_flags"]:
                st.warning(d)

        # Watch items
        if synth["key_watch_items"]:
            st.subheader("Key Watch Items")
            for item in synth["key_watch_items"]:
                st.write(f"- {item}")

        st.caption(f"Report date: {synth['report_date']}")

    # --- Analyst Breakdown ---
    st.header("Analyst Reports")

    if not detail["analysts"]:
        st.info("No analyst reports available.")
    else:
        for analyst in detail["analysts"]:
            agent_label = analyst["agent"].replace("_", " ").title()
            with st.expander(
                f"{agent_label} — {analyst['signal'].upper()} ({analyst['confidence']:.0%})",
                expanded=False,
            ):
                st.write(f"**Thesis:** {analyst['thesis']}")

                a_bull_col, a_bear_col = st.columns(2)
                with a_bull_col:
                    st.write(f"**Bull Case:** {analyst['bull_case']}")
                with a_bear_col:
                    st.write(f"**Bear Case:** {analyst['bear_case']}")

                if analyst["risks"]:
                    st.write("**Risks:**")
                    for risk in analyst["risks"]:
                        st.write(f"- {risk}")

                if analyst["key_metrics"]:
                    st.write("**Key Metrics:**")
                    metrics_cols = st.columns(min(len(analyst["key_metrics"]), 4))
                    for i, (k, v) in enumerate(analyst["key_metrics"].items()):
                        col = metrics_cols[i % len(metrics_cols)]
                        display_val = f"{v:.2f}" if isinstance(v, float) else str(v)
                        col.metric(k.replace("_", " ").title(), display_val)

                st.caption(f"Report date: {analyst['report_date']}")
