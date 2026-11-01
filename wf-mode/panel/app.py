"""wf-agent 能力面板（Streamlit 单页）。"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for path in (HERE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import streamlit as st  # noqa: E402

import service  # noqa: E402

st.set_page_config(page_title="wf-agent 能力面板", layout="wide")
st.title("wf-agent 能力面板")
st.caption("提示词、装配工具、API 接入与状态测试；启停只写 panel/state.json。")

prompt_tab, tools_tab, api_tab, test_tab = st.tabs(
    ["提示词", "装配工具", "API 接入", "状态测试"]
)

# ---------------------------------------------------------------- 提示词
with prompt_tab:
    try:
        summary = service.agent_summary()
        st.text_input("tools 白名单", summary["tools"], disabled=True)
        st.text_input("hook", summary["hook"], disabled=True)
        body = st.text_area("提示词正文（frontmatter 只读）", summary["body"], height=520)
        if st.button("保存正文", key="save_prompt"):
            backup = service.save_agent_body(body)
            st.success(f"已保存；备份：{backup}")
            st.info("保存后需重新启动 agent 才会生效。")
    except Exception as exc:  # noqa: BLE001
        st.error(f"读取提示词失败：{exc}")

# ---------------------------------------------------------------- 装配工具
with tools_tab:
    try:
        data = service.list_capabilities()
        caps = data["capabilities"]
        disabled = set(service.load_state().get("disabled", []))
        rows = []
        for name, item in caps.items():
            providers = str(item.get("primary") or "")
            if item.get("alternate"):
                providers += f" / {item['alternate']}"
            rows.append(
                {
                    "能力": name,
                    "名称": item.get("label"),
                    "类型": item.get("kind"),
                    "主备": providers,
                    "状态": item.get("status"),
                    "启用": "否" if name in disabled else "是",
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)

        selected = st.multiselect(
            "停用能力（保存后 agent 调用会被拒绝）",
            options=sorted(caps),
            default=sorted(disabled),
        )
        if st.button("保存启停", key="save_state"):
            service.save_state(set(selected))
            st.success("已保存面板启停状态")
    except Exception as exc:  # noqa: BLE001
        st.error(f"读取能力目录失败：{exc}")

# ---------------------------------------------------------------- API 接入
with api_tab:
    try:
        data = service.list_capabilities()
        rows = []
        for name, item in data["capabilities"].items():
            env = item.get("env") or {}
            env_text = "、".join(f"{k}:{'有' if v else '缺'}" for k, v in env.items()) or "-"
            detail = ""
            if item.get("kind") == "cli":
                exists = "存在" if item.get("commandExists") else "缺失"
                detail = f"{item.get('command', '')}（{exists}）"
            elif item.get("kind") == "mcp":
                detail = f"MCP {item.get('mcpServer', '')}；工具 {', '.join(item.get('mcpTools') or [])}"
            elif item.get("kind") == "pending":
                detail = item.get("notes") or "待接入"
            rows.append(
                {
                    "能力": name,
                    "类型": item.get("kind"),
                    "环境变量": env_text,
                    "工具/接入": detail,
                    "状态": item.get("status"),
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.caption("环境变量只显示是否存在，不显示值。")
    except Exception as exc:  # noqa: BLE001
        st.error(f"读取接入状态失败：{exc}")

# ---------------------------------------------------------------- 状态测试
with test_tab:
    try:
        names = ["全部"] + sorted(service.list_capabilities()["capabilities"])
        chosen = st.selectbox("测试对象", names)
        if st.button("运行测试", key="run_health"):
            result = service.health(None if chosen == "全部" else chosen)
            rows = []
            for name, item in result.get("capabilities", {}).items():
                providers = item.get("providers") or {}
                if providers:
                    detail = "；".join(
                        f"{provider}:{'通过' if check.get('ok') else '失败'}"
                        for provider, check in providers.items()
                    )
                else:
                    detail = item.get("reason") or item.get("server") or item.get("status")
                rows.append({"能力": name, "状态": item.get("status"), "详情": detail})
            st.dataframe(rows, use_container_width=True, hide_index=True)
        if st.button("运行 doctor", key="run_doctor"):
            st.json(service.doctor())
    except Exception as exc:  # noqa: BLE001
        st.error(f"测试失败：{exc}")

