"""统一错误类型。

适配器、核心槽和调度器只抛 ToolError；wf-tool 负责把它翻译成统一信封。
错误消息中禁止出现令牌、密钥或完整请求头。
"""

from __future__ import annotations


class ToolError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict | None = None,
        allow_fallback: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}
        self.allow_fallback = allow_fallback

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
        }
