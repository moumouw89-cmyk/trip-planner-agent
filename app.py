"""行程管家 Streamlit UI."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from trip_planner.agent import TripAgent
from trip_planner.config import (
    AMAP_API_KEY,
    BAIDU_AK,
    HOTEL_LABELS,
    MAP_LABELS,
    PACE_LABELS,
    REPORTS_DIR,
)
from trip_planner.export import write_exports
from trip_planner.hotel import get_hotel_provider
from trip_planner.judge import ItineraryJudge
from trip_planner.llm import OpenAICompatibleLLM
from trip_planner.models import TripPlan, TripRequest
from trip_planner.photos import AmapPhotoProvider
from trip_planner.planner import TripPlanner
from trip_planner.poi import POIRepository
from trip_planner.providers import get_route_provider, get_weather_provider
from trip_planner.rag import GuideIndex
from trip_planner.restaurant import AmapRestaurantProvider
from trip_planner.tripdb import TripRepository
from trip_planner.ui_config import default_llm_config, get_llm_config
from trip_planner.ui_nav import render_nav


st.set_page_config(
    page_title="行程管家",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSS = """
<style>
    :root { --ink:#10233f; --muted:#61708a; --accent:#2e74b5; }
    .block-container { padding-top: 1.4rem; padding-bottom: 2rem; max-width: 1280px; }
    .day-card { background:#f8fbff; border:1px solid #dbe8f7; border-radius:14px;
        padding:14px 16px; margin-bottom:12px; }
    .time { color:#2e74b5; font-weight:700; font-size:.84rem; }
    .poi { color:#10233f; font-weight:700; }
    .note { color:#61708a; font-size:.85rem; }
    .issue { background:#fff7ed; border:1px solid #fed7aa; border-radius:10px;
        padding:9px 12px; margin:6px 0; color:#7c2d12; font-size:.88rem; }
    .ok { background:#ecfdf5; border:1px solid #a7f3d0; border-radius:10px;
        padding:9px 12px; margin:6px 0; color:#065f46; font-size:.88rem; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

poi_repo = POIRepository()
guide_index = GuideIndex()
trip_repo = TripRepository()


def image_url(url: str) -> str:
    if url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return url


def make_agent(
    api_key: str,
    base_url: str,
    model: str,
    map_provider: str,
    amap_key: str,
    baidu_ak: str,
    hotel_source: str,
) -> TripAgent:
    route = get_route_provider(map_provider, amap_key, baidu_ak)
    weather = get_weather_provider(map_provider, amap_key, baidu_ak)
    hotel = get_hotel_provider(hotel_source, amap_key)
    photo = AmapPhotoProvider(amap_key) if amap_key else None
    meal = AmapRestaurantProvider(amap_key) if amap_key else None
    planner = TripPlanner(
        poi_repo=poi_repo,
        guide_index=guide_index,
        route_provider=route,
        hotel_provider=hotel,
        photo_provider=photo,
        meal_provider=meal,
    )
    llm = (
        OpenAICompatibleLLM(api_key=api_key, base_url=base_url, model=model)
        if api_key.strip()
        else None
    )
    # weather is intentionally available for future display; planner currently
    # uses route data for feasibility and keeps weather out of hard constraints.
    _ = weather
    return TripAgent(planner, trip_repo, llm=llm, hotel_provider=hotel)


st.session_state.setdefault("plan", None)
st.session_state.setdefault("judge", None)
default_cfg = default_llm_config()
st.session_state.setdefault("llm_config", default_cfg)
st.session_state.setdefault(
    "provider_config",
    {
        "api_key": default_cfg["api_key"],
        "base_url": default_cfg["base_url"],
        "model": default_cfg["model"],
        "map_provider": "amap",
        "amap_key": AMAP_API_KEY,
        "baidu_ak": BAIDU_AK,
        "hotel_source": "amap" if AMAP_API_KEY else "local",
    },
)

with st.sidebar:
    render_nav()
    llm_cfg = get_llm_config(st)
    api_key = llm_cfg.get("api_key", "")
    base_url = llm_cfg.get("base_url", "")
    model = llm_cfg.get("model", "")
    st.caption(
        f"{llm_cfg.get('label', '模型')} · {model} · "
        + ("已填写密钥" if api_key else "规则模式")
    )
    last_test = st.session_state.get("last_model_test")
    if last_test:
        st.caption(
            f"最近调用：{'成功' if last_test['ok'] else '失败'} · "
            f"{last_test['latency']:.2f}s"
        )

    with st.expander("地图 / 酒店", expanded=False):
        map_provider = st.selectbox(
            "地图提供方",
            ["amap", "baidu", "mock"],
            format_func=lambda x: MAP_LABELS[x],
            key="map_provider",
        )
        st.session_state.setdefault("amap_key", AMAP_API_KEY)
        st.session_state.setdefault("baidu_ak", BAIDU_AK)
        amap_key = st.text_input("高德密钥", type="password", key="amap_key")
        baidu_ak = st.text_input("百度密钥", type="password", key="baidu_ak")
        st.session_state.setdefault(
            "hotel_source", "amap" if AMAP_API_KEY else "local"
        )
        hotel_source = st.selectbox(
            "酒店来源",
            ["auto", "local", "amap"],
            format_func=lambda x: HOTEL_LABELS[x],
            key="hotel_source",
        )
    with st.expander("按表单填写"):
        city_options = poi_repo.list_cities() + ["__other__"]
        city_choice = st.selectbox(
            "城市",
            city_options,
            format_func=lambda c: "其他城市（手动输入）"
            if c == "__other__"
            else f"{c.name} · 酒店参考 ¥{c.hotel_rate:.0f}/晚",
        )
        if city_choice == "__other__":
            city_value = st.text_input("输入城市名", placeholder="例如：大理、青岛、长沙")
            city_obj = None
        else:
            city_value = city_choice.id
            city_obj = city_choice
        must_visit = []
        if city_obj is not None:
            must_visit = st.multiselect(
                "必去地点（可多选）",
                [poi.name for poi in city_obj.pois],
                help="留空则由规划器自动选点。",
            )
        start = st.date_input("出发日期", value=date.today() + timedelta(days=7))
        days = st.slider("天数", 1, 6, 4)
        budget = st.number_input("预算（元）", 1000, 30000, 5000, step=500)
        origin = st.text_input("出发城市", "深圳")
        preferences = st.text_input("偏好", "美食、自然、不赶")
        pace = st.selectbox(
            "节奏", list(PACE_LABELS), format_func=lambda x: PACE_LABELS[x], index=1
        )
        save_form = st.checkbox("保存到计划仓库", value=False)
        if st.button("按表单生成", use_container_width=True):
            with st.spinner("建库并规划..."):
                try:
                    agent = make_agent(
                        api_key, base_url, model, map_provider, amap_key, baidu_ak, hotel_source
                    )
                    st.session_state.plan = agent.plan(
                        TripRequest(
                            city=city_value,
                            start_date=start.isoformat(),
                            days=days,
                            budget=float(budget),
                            origin=origin,
                            preferences=preferences,
                            pace=pace,
                            must_visit=must_visit,
                        ),
                        save=save_form,
                    )
                    st.session_state.judge = None
                    st.session_state.provider_config = {
                        "api_key": api_key,
                        "base_url": base_url,
                        "model": model,
                        "map_provider": map_provider,
                        "amap_key": amap_key,
                        "baidu_ak": baidu_ak,
                        "hotel_source": hotel_source,
                    }
                    st.rerun()
                except Exception as exc:
                    st.error(f"生成失败：{exc}")

st.markdown("## 行程管家")
_, nav_backend, nav_repo = st.columns([7, 1.2, 1.2])
with nav_backend:
    st.page_link("pages/1_后台.py", label="后台", icon="🛠️")
with nav_repo:
    st.page_link("pages/2_计划仓库.py", label="计划仓库", icon="🗂️")

if st.session_state.plan is None:
    st.markdown('<div style="height: 16vh"></div>', unsafe_allow_html=True)

left, center, right = st.columns([1, 2.4, 1])
with center:
    with st.container(border=True):
        text = st.text_area(
            "旅行需求",
            value="11月1-4日成都，预算5000，从深圳出发，喜欢美食和自然，不想太赶",
            height=100,
        )
        save_plan = st.checkbox("生成后保存到计划仓库", value=False)
        if st.button("生成行程", type="primary", use_container_width=True):
            with st.spinner("生成中..."):
                try:
                    agent = make_agent(
                        api_key,
                        base_url,
                        model,
                        map_provider,
                        amap_key,
                        baidu_ak,
                        hotel_source,
                    )
                    st.session_state.plan = agent.plan_from_text(text, save=save_plan)
                    st.session_state.judge = None
                    st.session_state.provider_config = {
                        "api_key": api_key,
                        "base_url": base_url,
                        "model": model,
                        "map_provider": map_provider,
                        "amap_key": amap_key,
                        "baidu_ak": baidu_ak,
                        "hotel_source": hotel_source,
                    }
                    st.rerun()
                except Exception as exc:
                    st.error(f"生成失败：{exc}")
        st.caption(
            "可用城市："
            + " · ".join(city.name for city in poi_repo.list_cities())
            + "；其他城市会尝试用高德实时地点数据建城。"
        )

plan: TripPlan | None = st.session_state.plan
if plan is None:
    st.stop()

request = plan.request
high_issues = [issue for issue in plan.issues if issue.severity == "high"]
c1, c2, c3, c4 = st.columns(4)
c1.metric("天数", f"{request.days} 天")
c2.metric("预估 / 预算", f"{plan.total_cost:.0f} / {request.budget:.0f} 元")
c3.metric(
    "景点",
    f"{sum(1 for day in plan.days for item in day.items if item.kind == 'poi')} 个",
)
c4.metric("高优先级问题", len(high_issues))

st.markdown(f"**{plan.summary}**")
if plan.db_path:
    st.caption(f"已保存到计划仓库：`{plan.trip_id}`")
else:
    if st.button("保存到计划仓库", type="secondary"):
        trip_repo.create(plan)
        st.session_state.plan = plan
        st.rerun()
    st.caption("当前计划未保存。")
st.caption(
    "景点/酒店名称、图片、评分来自高德；门票、时长、价格是规划估算，非实时库存。"
    if AMAP_API_KEY
    else "本地演示数据；填入高德密钥后显示真实图片和酒店。"
)
llm_calls = [step for step in plan.trace if step.get("tool") == "llm"]
if llm_calls:
    failed = any(not step.get("ok", True) for step in llm_calls)
    st.caption(
        f"本次大模型调用：{len(llm_calls)} 次"
        + ("，有失败并已回退模板。" if failed else "，解析/说明由模型完成。")
    )
else:
    st.caption("本次未调用大模型：规则模式。")

hero = ""
for day in plan.days:
    for item in day.items:
        if item.photo_url:
            hero = item.photo_url
            break
    if hero:
        break
if not hero and plan.selected_hotel:
    hero = plan.selected_hotel.photo_url
if hero:
    st.markdown(
        f'<img src="{image_url(hero)}" style="width:100%;height:260px;object-fit:cover;'
        f'border-radius:16px;margin:8px 0 16px;">',
        unsafe_allow_html=True,
    )

if plan.hotel_options:
    st.markdown("**酒店对比**")
    hotel_options = plan.hotel_options
    selected_id = plan.selected_hotel.id if plan.selected_hotel else hotel_options[0].id
    cols = st.columns(min(3, len(hotel_options)))
    for idx, hotel in enumerate(hotel_options):
        with cols[idx % len(cols)]:
            if hotel.photo_url:
                st.markdown(
                    f'<img src="{image_url(hotel.photo_url)}" style="width:100%;height:150px;'
                    f'object-fit:cover;border-radius:12px;">',
                    unsafe_allow_html=True,
                )
            else:
                st.caption("暂无实景图")
            st.markdown(f"**{hotel.name}**")
            price = f"¥{hotel.price:.0f}/晚" if hotel.price > 0 else "参考价待查"
            rating = f"{hotel.rating:.1f} 分" if hotel.rating > 0 else "暂无评分"
            st.caption(f"{price} · {rating} · {hotel.area}")
            if hotel.id == selected_id:
                st.button("当前选择", key=f"hotel_{hotel.id}", disabled=True, use_container_width=True)
            elif st.button("选择这家", key=f"hotel_{hotel.id}", use_container_width=True):
                cfg = st.session_state.provider_config
                agent = make_agent(
                    cfg["api_key"],
                    cfg["base_url"],
                    cfg["model"],
                    cfg["map_provider"],
                    cfg["amap_key"],
                    cfg["baidu_ak"],
                    cfg["hotel_source"],
                )
                with st.spinner("重算住宿预算与路线..."):
                    st.session_state.plan = agent.replan(
                        plan, hotel, save=bool(plan.db_path)
                    )
                    st.session_state.judge = None
                    st.rerun()
    if plan.hotel_options[0].source == "amap":
        st.caption("酒店名称/图片/评分来自高德；参考价非实时房态。")
    else:
        st.caption("高德酒店接口未返回结果，当前显示本地演示酒店。")

rec_agent = make_agent(
    api_key,
    base_url,
    model,
    map_provider,
    amap_key,
    baidu_ak,
    hotel_source,
)
suggestions = rec_agent.recommendations(plan)
attractions = [poi for poi in suggestions if poi.category != "food"]
foods = [poi for poi in suggestions if poi.category == "food"]
if suggestions:
    st.markdown("**推荐加点**")
    for title, items in (("景点推荐", attractions), ("美食推荐", foods)):
        if not items:
            continue
        st.caption(title)
        cols = st.columns(min(3, len(items)))
        for idx, poi in enumerate(items[:3]):
            with cols[idx % len(cols)]:
                if poi.photo_url:
                    st.markdown(
                        f'<img src="{image_url(poi.photo_url)}" style="width:100%;height:110px;'
                        f'object-fit:cover;border-radius:12px;">',
                        unsafe_allow_html=True,
                    )
                st.markdown(f"**{poi.name}**")
                st.caption(
                    f"{poi.score:.1f} 分 · {poi.area or '高德推荐'}"
                    if poi.score > 0
                    else "高德推荐"
                )
                if st.button("加入行程", key=f"add_{poi.id}", use_container_width=True):
                    with st.spinner("重新安排整天行程..."):
                        st.session_state.plan = rec_agent.add_places(
                            plan,
                            [poi.name],
                            extra_pois=[poi],
                            save=bool(plan.db_path),
                        )
                        st.session_state.judge = None
                        st.rerun()

if high_issues:
    for issue in high_issues:
        st.markdown(f'<div class="issue">⚠ {issue.message}</div>', unsafe_allow_html=True)
else:
    st.markdown('<div class="ok">✓ 预算、强度、营业时间、通勤校验通过。</div>', unsafe_allow_html=True)

tab_itinerary, tab_budget = st.tabs(["每日行程", "预算"])

with tab_itinerary:
    if plan.selected_hotel:
        if plan.selected_hotel.price > 0:
            st.caption(
                f"住宿：{plan.selected_hotel.name} · 参考 ¥{plan.selected_hotel.price:.0f}/晚"
            )
        else:
            st.caption(f"住宿：{plan.selected_hotel.name} · 参考价待查")
    for day in plan.days:
        st.markdown(
            f"### 第 {day.day} 天 · {day.date} · {day.theme} "
            f"<span style='color:#61708a;font-size:.85rem'>约 {day.daily_minutes} 分钟</span>",
            unsafe_allow_html=True,
        )
        if not day.items:
            st.caption("这一天还没有安排，可以追问调整。")
        for item in day.items:
            cost = f"门票 ¥{item.ticket:.0f}" if item.ticket > 0 else ""
            meta = f"通勤 {item.travel_minutes} 分钟"
            if cost:
                meta += f" · {cost}"
            card = (
                f'<div class="day-card">'
                f'<span class="time">{item.start}-{item.end}</span> '
                f'<span class="poi">{item.poi_name}</span>'
                f'<div class="note">{meta} · {item.note}</div>'
                f'</div>'
            )
            if item.photo_url:
                img_col, body_col = st.columns([1, 4])
                with img_col:
                    st.markdown(
                        f'<img src="{image_url(item.photo_url)}" style="width:100%;height:110px;'
                        f'object-fit:cover;border-radius:12px;">',
                        unsafe_allow_html=True,
                    )
                with body_col:
                    st.markdown(card, unsafe_allow_html=True)
            else:
                st.markdown(card, unsafe_allow_html=True)
            if item.guide_citation:
                st.caption(f"攻略：{item.guide_citation}")

with tab_budget:
    budget_df = pd.DataFrame(
        [{"项目": item.label, "金额": item.amount} for item in plan.budget_items]
    )
    st.dataframe(budget_df, hide_index=True, use_container_width=True)
    st.bar_chart(budget_df.set_index("项目"), use_container_width=True)
    st.caption(f"预估合计 {plan.total_cost:.0f} 元，预算 {request.budget:.0f} 元。")

st.divider()
col1, col2 = st.columns(2)
with col1:
    if st.button("生成 Markdown + ICS", use_container_width=True):
        paths = write_exports(plan, REPORTS_DIR)
        st.success(f"已生成：{paths['markdown']}")
        st.download_button(
            "下载 Markdown",
            data=Path(paths["markdown"]).read_bytes(),
            file_name=Path(paths["markdown"]).name,
            mime="text/markdown",
        )
        st.download_button(
            "下载 ICS",
            data=Path(paths["ics"]).read_bytes(),
            file_name=Path(paths["ics"]).name,
            mime="text/calendar",
        )
with col2:
    if st.button("运行行程评审", use_container_width=True):
        cfg = st.session_state.provider_config
        llm = (
            OpenAICompatibleLLM(
                api_key=cfg["api_key"],
                base_url=cfg["base_url"],
                model=cfg["model"],
            )
            if cfg["api_key"]
            else None
        )
        st.session_state.judge = ItineraryJudge(llm).judge(plan)

if st.session_state.judge:
    judge = st.session_state.judge
    st.markdown("#### 行程评审")
    st.json(judge.to_dict())
