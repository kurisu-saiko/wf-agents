"""两道人闸的静态规则；面板与测试共用，避免文案漂移。"""

from __future__ import annotations

NOTE = "面板只展示闸口规则，不记录运行状态，也不提供工作流入口。"

GATES = [
    {
        "id": "gate-1",
        "title": "闸口 1：需求确认",
        "stage": "阶段 1–3",
        "command": "/wf",
        "next": "/wf-plan",
        "release": "在对话中确认需求卡，然后由你手动执行 /wf-plan。",
        "blocked": [
            "所有调研能力（web_search / web_extract / project_search）",
            "仓库读取与结构搜索（repo_ingest / structural_search / dependency_graph）",
            "GitHub 与 Web MCP 工具",
        ],
        "reason": "/wf 的 Bash 白名单只有 wf_stage.py calibrate，命令中没有任何调研工具。",
        "checks": [
            "需求卡字段完整",
            "Must / Should 可观察、可验收",
            "未知项与缺口已列出",
        ],
    },
    {
        "id": "gate-2",
        "title": "闸口 2：方案确认",
        "stage": "阶段 4–5",
        "command": "/wf-plan",
        "next": "/wf-report",
        "release": "确认方案与需求覆盖表，然后由你手动执行 /wf-report。",
        "blocked": [
            "输出最终交付报告",
            "写文件、安装依赖、部署",
        ],
        "reason": "/wf-plan 没有 Write / Edit / Bash 写权限，且协议要求它只输出方案，不输出最终报告。",
        "checks": [
            "每个 Must 有覆盖或未覆盖结论",
            "候选有许可证与维护状态证据",
            "未验证项单独列出",
        ],
    },
]

REQUIRED_CAPABILITIES = {
    "gate-1": [],
    "gate-2": [
        "web_search",
        "web_extract",
        "project_search",
        "repo_ingest",
        "structural_search",
        "dependency_graph",
    ],
}
