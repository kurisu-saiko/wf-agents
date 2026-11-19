"""两道人闸的静态规则；面板与测试共用，避免文案漂移。"""

from __future__ import annotations

NOTE = "面板仅在工作流首次交互时打开，进入计划模式或交付模式后自动关闭，不记录运行历史。"

GATES = [
    {
        "id": "gate-1",
        "title": "闸口 1：需求确认",
        "stage": "阶段 1–3",
        "command": "/wf",
        "next": "/wf-plan",
        "release": "确认需求卡后，自动关闭配置面板并进入计划与深度调研阶段。",
        "blocked": [
            "外部网络与 GitHub 仓库调研（web_search / web_extract / project_search / repo_health / package_meta）",
            "写文件、安装依赖与部署",
        ],
        "reason": "init 阶段未通过闸口 1 前只允许本地项目最小只读校准，防止偏离需求盲目调研。",
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
        "release": "确认方案与需求对照表后，保持面板关闭并输出最终只读报告。",
        "blocked": [
            "输出最终交付报告",
            "写文件、安装依赖、部署",
        ],
        "reason": "方案未经人工拍板前不进入最终交付，全程保持只读。",
        "checks": [
            "每个 Must 有覆盖或未覆盖结论",
            "候选有许可证分类、维护活跃度与 OSV 漏洞扫描证据",
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
        "repo_health",
        "package_meta",
        "package_security",
        "license_sbom",
        "dependency_graph",
        "structural_search",
    ],
}
