from __future__ import annotations

import time
from datetime import datetime

import pandas as pd
import streamlit as st

from trip_planner.config import AI_PRESETS
from trip_planner.llm import LLMError, OpenAICompatibleLLM
from trip_planner.tripdb import TripDatabase, TripRepository
from trip_planner.ui_config import get_llm_config, persist_llm_config
from trip_planner.ui_nav import render_nav


st.set_page_config(
    page_title="后台 · 行程管家",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="expanded",
)
render_nav()
st.title("后台")
st.caption("模型、密钥、数据库、调用记录、攻略引用都集中在这里。")

cfg = get_llm_config(st)
provider = st.selectbox(
    "模型提供方",
    list(AI_PRESETS),
    index=list(AI_PRESETS).index(cfg.get("provider", "deepseek"))
    if cfg.get("provider") in AI_PRESETS
    else 0,
    format_func=lambda x: AI_PRESETS[x]["label"],
)
preset = AI_PRESETS[provider]

if provider == cfg.get("provider"):
    default_key = cfg.get("api_key", "")
    default_base = cfg.get("base_url", preset["base_url"])
    default_model = cfg.get("model", preset["models"][0] if preset["models"] else "")
else:
    default_key = st.session_state.get(f"key_{provider}", "")
    default_base = st.session_state.get(f"base_{provider}", preset["base_url"])
    default_model = st.session_state.get(
        f"model_{provider}", preset["models"][0] if preset["models"] else ""
    )

api_key = st.text_input("接口密钥", value=default_key, type="password", key=f"key_{provider}")
base_url = st.text_input("接口地址", value=default_base, key=f"base_{provider}")
if preset["models"]:
    model_options = preset["models"]
    index = model_options.index(default_model) if default_model in model_options else 0
    model = st.selectbox("模型", model_options, index=index, key=f"model_{provider}")
else:
    model = st.text_input("模型", value=default_model, key=f"model_{provider}")

active_config = {
    "provider": provider,
    "label": preset["label"],
    "base_url": base_url.strip(),
    "model": model.strip(),
    "api_key": api_key.strip(),
}
st.session_state.llm_config = active_config
st.caption(f"当前生效：{preset['label']} / {model}")

col1, col2 = st.columns(2)
with col1:
    if st.button("保存配置", type="primary", use_container_width=True):
        st.session_state.llm_config = active_config
        persist_llm_config(active_config)
        st.success("已保存到本地 .env，重启后仍然有效。")
with col2:
    if st.button("测试真实调用", use_container_width=True):
        if not api_key.strip():
            st.error("没有密钥，无法测试。")
        else:
            started = time.perf_counter()
            ok = False
            answer = ""
            error = ""
            try:
                llm = OpenAICompatibleLLM(
                    api_key=api_key.strip(),
                    base_url=base_url.strip(),
                    model=model.strip(),
                )
                answer = llm.complete(
                    "你是连接测试助手。",
                    "只回复四个字：连接成功",
                )
                ok = True
            except LLMError as exc:
                error = str(exc)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            latency = time.perf_counter() - started
            st.session_state.last_model_test = {
                "ok": ok,
                "latency": latency,
                "response": answer[:500],
                "error": error[:500],
                "provider": preset["label"],
                "model": model,
                "at": datetime.now().isoformat(timespec="seconds"),
            }
            st.session_state.llm_config = active_config
            persist_llm_config(active_config)

if st.button("保存并使用", use_container_width=True):
    st.session_state.llm_config = active_config
    persist_llm_config(active_config)
    st.switch_page("app.py")

test = st.session_state.get("last_model_test")
if test:
    st.divider()
    st.subheader("最近一次真实调用")
    if test["ok"]:
        st.success(f"成功 · {test['provider']} / {test['model']} · {test['latency']:.2f} 秒")
        st.code(test["response"] or "(空响应)")
    else:
        st.error(f"失败 · {test['provider']} / {test['model']} · {test['latency']:.2f} 秒")
        st.code(test["error"] or "未知错误")
    st.caption(f"调用时间：{test['at']}")

st.divider()
st.subheader("数据与调用")
plan = st.session_state.get("plan")
if plan is None:
    st.info("还没有生成计划。先在行程管家生成一个，再回来查看数据库和调用记录。")
else:
    tab_db, tab_trace, tab_guide = st.tabs(["数据库", "调用记录", "攻略引用"])
    with tab_db:
        if plan.db_path:
            st.code(plan.db_path, language="text")
            try:
                repo = TripRepository()
                st.write("表：" + "、".join(f"`{name}`" for name in repo.schema(plan.trip_id)))
                db = TripDatabase(plan.db_path)
                try:
                    versions = pd.DataFrame(db.versions()).rename(
                        columns={
                            "version": "版本",
                            "created_at": "时间",
                            "reason": "原因",
                        }
                    )
                    st.dataframe(versions, hide_index=True, use_container_width=True)
                finally:
                    db.close()
            except Exception as exc:
                st.caption(f"读取失败：{exc}")
        else:
            st.caption("当前计划未保存。")
    with tab_trace:
        if plan.trace:
            trace = pd.DataFrame(plan.trace).rename(
                columns={
                    "step": "步骤",
                    "tool": "工具",
                    "detail": "详情",
                    "ok": "状态",
                }
            )
            if "步骤" in trace:
                trace["步骤"] = trace["步骤"].map(
                    {
                        "request": "需求",
                        "parse": "解析",
                        "build": "生成",
                        "narrate": "说明",
                        "save": "保存",
                        "hotel": "酒店",
                    }
                ).fillna(trace["步骤"])
            if "工具" in trace:
                trace["工具"] = trace["工具"].map(
                    {
                        "TripPlanner": "行程规划器",
                        "SQLite": "数据库",
                        "llm": "大模型",
                        "HotelProvider": "酒店搜索",
                        "form": "表单",
                        "rule": "规则",
                    }
                ).fillna(trace["工具"])
            if "状态" in trace:
                trace["状态"] = trace["状态"].map({True: "成功", False: "失败"})
            st.dataframe(trace, hide_index=True, use_container_width=True)
        else:
            st.caption("没有调用记录。")
    with tab_guide:
        if plan.citations:
            for citation in plan.citations:
                st.markdown(
                    f"**《{citation['doc_name']}》 · {citation['heading']}**\n\n"
                    f"{citation['snippet']}"
                )
        else:
            st.caption("没有攻略引用。")

st.divider()
st.caption("密钥不写入仓库；需要重启后保留时，用桌面的密钥设置脚本写入 .env。")
