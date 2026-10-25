from __future__ import annotations

import pandas as pd
import streamlit as st

from trip_planner.tripdb import TripRepository
from trip_planner.ui_nav import render_nav


st.set_page_config(
    page_title="计划仓库 · 行程管家",
    page_icon="🗂️",
    layout="wide",
    initial_sidebar_state="expanded",
)
render_nav()
st.title("计划仓库")
st.caption("每次生成的计划都会自动保存在独立 SQLite 中；这里可以打开历史计划。")

repo = TripRepository()
trips = repo.list_trips()

if not trips:
    st.info("还没有保存的计划。先回主页面生成一个。")
    st.page_link("app.py", label="返回生成行程", icon="🧭")
    st.stop()

rows = [
    {
        "城市": item["city"],
        "出发日期": item["start_date"],
        "天数": item["days"],
        "预算": item["budget"],
        "预估": item["total_cost"],
        "酒店": item.get("hotel_name") or "未选",
        "trip_id": item["trip_id"],
    }
    for item in trips
]
st.dataframe(pd.DataFrame(rows).drop(columns=["trip_id"]), hide_index=True, use_container_width=True)

for item in trips:
    with st.container(border=True):
        left, mid, right = st.columns([3, 2, 1])
        with left:
            st.markdown(
                f"**{item['city']} · {item['start_date']} · {item['days']} 天**"
            )
            st.caption(item.get("summary") or "")
            st.caption(f"`{item['trip_id']}`")
        with mid:
            st.metric("预估 / 预算", f"{item['total_cost']:.0f} / {item['budget']:.0f} 元")
        with right:
            if st.button("打开", key=f"open_{item['trip_id']}", use_container_width=True):
                plan = repo.load(item["trip_id"])
                if plan is None:
                    st.error("读取失败。")
                else:
                    st.session_state.plan = plan
                    st.session_state.judge = None
                    st.switch_page("app.py")
            if st.button("删除", key=f"delete_{item['trip_id']}", use_container_width=True):
                repo.delete(item["trip_id"])
                st.rerun()

st.divider()
