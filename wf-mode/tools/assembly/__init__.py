"""工程组装闭环引擎（Step 3 ~ Step 6）：

- strategy: 5选1复用策略量化评估引擎（Step 3）
- profiler: 本地项目技术栈、布局与验证指令画像（Step 3/4）
- slicer: AST 级代码切片最小传递依赖闭包计算器（Step 4/5）
- contract: 本地对接契约设计与分块 Diff 生成器（Step 4/5）
- provenance: SPDX 版权声明注入与 THIRD_PARTY_NOTICES.md 维护（Step 5）
- checkpoint: Git / 工作区安全快照与一键回滚（Step 5/6）
- patcher: 受控闸口校验与分块落盘执行器（Step 5）
- verifier: 语法编译、冒烟测试与本地回归验证器（Step 6）
"""

from __future__ import annotations
