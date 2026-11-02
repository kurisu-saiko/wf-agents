"""wf-agent 工具配置面板（Streamlit 单页）。

定位：配置能力、密钥、provider 顺序与本地工具路径；不运行工作流。
"""

from __future__ import annotations

import html
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for path in (HERE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import streamlit as st  # noqa: E402

import service  # noqa: E402

st.set_page_config(page_title="wf 工具配置面板", layout="wide")

st.markdown(
    """
<style>
.block-container {padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1320px;}
.wf-hero {padding: 18px 22px; border-radius: 16px; background: linear-gradient(120deg,#0f172a,#1e3a8a);
          color:#fff; margin-bottom: 18px;}
.wf-hero h1 {margin:0; font-size:1.55rem; color:#fff;}
.wf-hero p {margin:.35rem 0 0; color:#cbd5e1; font-size:.9rem;}
.wf-badge {display:inline-block; padding:2px 9px; border-radius:999px; font-size:.76rem;
           font-weight:600; letter-spacing:.01em; white-space:nowrap;}
.wf-active {background:#dcfce7; color:#166534;}
.wf-degraded {background:#fef3c7; color:#92400e;}
.wf-missing {background:#fee2e2; color:#991b1b;}
.wf-pending {background:#e0e7ff; color:#3730a3;}
.wf-disabled {background:#f1f5f9; color:#475569;}
.wf-panel {background:#e0f2fe; color:#075985;}
.wf-env {background:#f3e8ff; color:#6b21a8;}
.wf-yaml {background:#f1f5f9; color:#475569;}
div[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 14px;}
</style>
""",
    unsafe_allow_html=True,
)


def badge(text: str, tone: str) -> str:
    return f'<span class="wf-badge wf-{html.escape(tone)}">{html.escape(str(text))}</span>'


def status_tone(status: str) -> str:
    return {
        "active": "active",
        "degraded": "degraded",
        "missing": "missing",
        "pending": "pending",
        "disabled": "disabled",
    }.get(status, "disabled")


def source_badge(source: str) -> str:
    label, tone = {
        "panel": ("面板", "panel"),
        "env": ("环境变量", "env"),
        "yaml": ("yaml 默认", "yaml"),
        "none": ("未配置", "disabled"),
    }.get(source, (source, "disabled"))
    return badge(label, tone)


st.markdown(
    """
<div class="wf-hero">
  <h1>wf 工具配置面板</h1>
  <p>配置能力、密钥、主备顺序和本地工具路径。面板不运行工作流，也不记录运行状态。</p>
</div>
""",
    unsafe_allow_html=True,
)

try:
    caps_data = service.list_capabilities()
    caps = caps_data["capabilities"]
except Exception as exc:  # noqa: BLE001
    st.error(f"读取能力目录失败：{exc}")
    st.stop()

try:
    doctor_data = service.doctor()
except Exception:  # noqa: BLE001
    doctor_data = {}

tabs = st.tabs(
    ["总览", "能力与顺序", "密钥", "工具路径", "提示词", "诊断"]
)
overview_tab, order_tab, secret_tab, path_tab, prompt_tab, diag_tab = tabs

# ---------------------------------------------------------------- 总览
with overview_tab:
    counts = Counter(str(item.get("status") or "missing") for item in caps.values())
    cols = st.columns(5)
    for col, (label, key) in zip(
        cols,
        [
            ("可用 active", "active"),
            ("降级 degraded", "degraded"),
            ("缺失 missing", "missing"),
            ("待接入 pending", "pending"),
            ("已停用 disabled", "disabled"),
        ],
    ):
        col.metric(label, counts.get(key, 0))

    runtime = caps_data.get("runtime") or {}
    bin_ok = bool(runtime.get("bin")) and Path(runtime.get("bin", "")).is_dir()
    venv_ok = bool(runtime.get("venv")) and Path(runtime.get("venv", "")).is_dir()
    st.markdown("#### 运行时")
    left, right = st.columns(2)
    left.markdown(
        f"**工具目录** `{runtime.get('bin', '')}`  "
        + badge("存在" if bin_ok else "缺失", "active" if bin_ok else "missing"),
        unsafe_allow_html=True,
    )
    right.markdown(
        f"**虚拟环境** `{runtime.get('venv', '')}`  "
        + badge("存在" if venv_ok else "缺失", "active" if venv_ok else "missing"),
        unsafe_allow_html=True,
    )

    hosts = doctor_data.get("hosts") or {}
    if hosts:
        st.markdown("#### 宿主")
        st.markdown(
            " ".join(
                badge(f"{name}:{'检测到' if info.get('detected') else '未检测到'}",
                      "active" if info.get("detected") else "disabled")
                for name, info in hosts.items()
            ),
            unsafe_allow_html=True,
        )

# ---------------------------------------------------------------- 能力与顺序
with order_tab:
    st.caption("修改 provider 主备顺序与启停。面板保存值优先于 capabilities.yaml。")
    disabled = set(service.load_state().get("disabled", []))
    orders: dict[str, list[str]] = {}
    toggles: dict[str, bool] = {}

    for name, item in caps.items():
        with st.container(border=True):
            title_col, toggle_col, order_col = st.columns([3, 1.2, 4])
            with title_col:
                st.markdown(f"**{item.get('label')}** &nbsp; `{name}`", unsafe_allow_html=True)
                st.markdown(
                    badge(item.get("kind", ""), "pending")
                    + " "
                    + badge(item.get("status", ""), status_tone(str(item.get("status", "")))),
                    unsafe_allow_html=True,
                )
            with toggle_col:
                toggles[name] = st.toggle(
                    "启用",
                    value=name not in disabled,
                    key=f"enable_{name}",
                    disabled=item.get("kind") in {"pending", "mcp"},
                )
            with order_col:
                declared = item.get("providers") or []
                if declared:
                    chain = []
                    for value in [item.get("primary"), item.get("alternate"), *(item.get("fallback") or [])]:
                        if value and value not in chain:
                            chain.append(value)
                    orders[name] = st.text_input(
                        "主备顺序（逗号分隔）",
                        value=", ".join(chain),
                        key=f"order_{name}",
                        help="面板值优先；留空则回退 capabilities.yaml。",
                    )
                else:
                    st.caption("由宿主 MCP 或待接入能力提供，无需配置顺序。")

    if st.button("保存能力与顺序", type="primary"):
        try:
            parsed = {
                name: [part.strip() for part in value.split(",") if part.strip()]
                for name, value in orders.items()
            }
            service.save_provider_orders(parsed)
            service.save_state({name for name, enabled in toggles.items() if not enabled})
            st.success("已保存能力启停与 provider 顺序。")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"保存失败：{exc}")

# ---------------------------------------------------------------- 密钥
with secret_tab:
    st.caption("密钥只保存在本机配置，页面不回显明文；面板值优先于系统环境变量。")
    masked = service.masked_secrets()
    inputs: dict[str, str] = {}
    clears: set[str] = set()

    for label, info in masked.items():
        with st.container(border=True):
            st.markdown(
                f"**{label}** {source_badge(info['source'])} "
                f"`{info['masked'] or '未配置'}`",
                unsafe_allow_html=True,
            )
            if info.get("envPresent"):
                st.caption("系统环境变量已设置；保存面板值后会覆盖环境变量。")
            inputs[label] = st.text_input(
                "新值（留空不修改）",
                type="password",
                key=f"secret_{label}",
            )
            if st.checkbox("清除面板值", key=f"clear_{label}"):
                clears.add(label)

    target = st.selectbox(
        "连通测试对象",
        ["web_search", "web_extract", "project_search"],
        help="会真实发起一次最小请求，搜索类使用 test 查询。",
    )
    if st.button("保存并测试", type="primary"):
        try:
            service.save_secret_updates(
                {label: value for label, value in inputs.items() if value}, clears
            )
            result = service.probe(target)
            if result.get("ok"):
                st.success(f"{target} 连通测试通过。")
                st.json(result.get("data"))
            else:
                error = (result.get("error") or {}).get("message") or "未知错误"
                st.error(f"{target} 测试失败：{error}")
        except Exception as exc:  # noqa: BLE001
            st.error(f"保存或测试失败：{exc}")

# ---------------------------------------------------------------- 工具路径
with path_tab:
    st.caption("覆盖 runtime 目录或单个 CLI 可执行文件；留空表示使用 yaml 默认。")
    config = service.load_config()
    defaults = service.catalog_defaults()
    runtime_cfg = config.get("runtime") or {}
    default_runtime = defaults.get("runtime") or {}
    runtime_inputs: dict[str, str] = {}

    st.markdown("#### Runtime")
    r1, r2 = st.columns(2)
    with r1:
        runtime_inputs["bin"] = st.text_input(
            "工具目录 bin",
            value=runtime_cfg.get("bin") or "",
            placeholder=str(default_runtime.get("bin") or ""),
            key="path_bin",
        )
    with r2:
        runtime_inputs["venv"] = st.text_input(
            "虚拟环境 venv",
            value=runtime_cfg.get("venv") or "",
            placeholder=str(default_runtime.get("venv") or ""),
            key="path_venv",
        )

    st.markdown("#### CLI 可执行文件")
    cli_inputs: dict[str, dict[str, str]] = {}
    default_caps = defaults.get("capabilities") or {}
    for name, item in caps.items():
        if item.get("kind") != "cli":
            continue
        provider = item.get("primary")
        configured = ((config.get("cli_paths") or {}).get(name) or {}).get(provider, "")
        default_argv = (
            ((default_caps.get(name) or {}).get("exec") or {}).get(provider) or [""]
        )
        with st.container(border=True):
            st.markdown(
                f"**{item.get('label')}** `{name}` "
                + source_badge("panel" if configured else "yaml")
                + " "
                + badge(
                    "存在" if Path(item.get("command", "")).is_file() else "缺失",
                    "active" if Path(item.get("command", "")).is_file() else "missing",
                ),
                unsafe_allow_html=True,
            )
            cli_inputs[name] = {
                provider: st.text_input(
                    "可执行文件",
                    value=configured,
                    placeholder=str(default_argv[0]),
                    key=f"cli_{name}_{provider}",
                )
            }

    save_col, reset_col = st.columns([1, 1])
    with save_col:
        if st.button("保存路径", type="primary"):
            try:
                service.save_paths(runtime_inputs, cli_inputs)
                st.success("已保存工具路径。")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"保存失败：{exc}")
    with reset_col:
        if st.button("重置为 yaml 默认"):
            try:
                service.reset_paths()
                st.success("已清除面板路径覆盖。")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"重置失败：{exc}")

# ---------------------------------------------------------------- 提示词
with prompt_tab:
    try:
        summary = service.agent_summary()
        st.text_input("tools 白名单", summary["tools"], disabled=True)
        st.text_input("hook", summary["hook"], disabled=True)
        body = st.text_area("提示词正文（frontmatter 只读）", summary["body"], height=480)
        if st.button("保存正文", key="save_prompt"):
            backup = service.save_agent_body(body)
            st.success(f"已保存；备份：{backup}")
            st.info("保存后需重新启动 agent 才会生效。")
    except Exception as exc:  # noqa: BLE001
        st.error(f"读取提示词失败：{exc}")

# ---------------------------------------------------------------- 诊断
with diag_tab:
    st.caption("只检查配置与工具是否就绪，不运行工作流。")
    names = ["全部"] + sorted(caps)
    chosen = st.selectbox("测试对象", names, key="diag_target")
    if st.button("运行 health", key="run_health"):
        try:
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
                rows.append(
                    {"能力": name, "状态": item.get("status"), "详情": detail}
                )
            st.dataframe(rows, use_container_width=True, hide_index=True)
        except Exception as exc:  # noqa: BLE001
            st.error(f"health 失败：{exc}")
    if st.button("运行 doctor", key="run_doctor"):
        try:
            st.json(service.doctor())
        except Exception as exc:  # noqa: BLE001
            st.error(f"doctor 失败：{exc}")
