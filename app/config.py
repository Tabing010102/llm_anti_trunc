"""
配置模块：使用环境变量（带默认值）
"""
import os
from typing import List


class Config:
    """全局配置类"""
    
    # 上游地址
    UPSTREAM_OPENAI_BASE_URL: str = os.getenv("UPSTREAM_OPENAI_BASE_URL", "https://api.openai.com")
    UPSTREAM_GEMINI_BASE_URL: str = os.getenv("UPSTREAM_GEMINI_BASE_URL", "https://generativelanguage.googleapis.com")
    UPSTREAM_CLAUDE_BASE_URL: str = os.getenv("UPSTREAM_CLAUDE_BASE_URL", "https://api.anthropic.com")
    
    # 抗截断配置
    ANTI_TRUNCATION_ENABLED_DEFAULT: bool = os.getenv("ANTI_TRUNCATION_ENABLED_DEFAULT", "false").lower() == "true"
    ANTI_TRUNCATION_MAX_ATTEMPTS: int = int(os.getenv("ANTI_TRUNCATION_MAX_ATTEMPTS", "3"))
    ANTI_TRUNCATION_DONE_MARKER: str = os.getenv("ANTI_TRUNCATION_DONE_MARKER", "[done]")
    ANTI_TRUNCATION_MODEL_PREFIX: str = os.getenv("ANTI_TRUNCATION_MODEL_PREFIX", "流式抗截断/")
    
    # 透明代理/真实IP配置
    TRUST_PROXY_HEADERS: bool = os.getenv("TRUST_PROXY_HEADERS", "true").lower() == "true"
    TRUSTED_PROXY_CIDRS: str = os.getenv(
        "TRUSTED_PROXY_CIDRS", 
        "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
    )
    
    # HTTP 行为配置
    UPSTREAM_TIMEOUT_SECONDS: int = int(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "60"))
    UPSTREAM_CONNECT_TIMEOUT_SECONDS: int = int(os.getenv("UPSTREAM_CONNECT_TIMEOUT_SECONDS", "10"))
    MAX_BODY_SIZE_MB: int = int(os.getenv("MAX_BODY_SIZE_MB", "50"))
    
    @classmethod
    def get_trusted_proxy_cidrs_list(cls) -> List[str]:
        """解析 TRUSTED_PROXY_CIDRS 为列表"""
        if not cls.TRUSTED_PROXY_CIDRS:
            return []
        return [cidr.strip() for cidr in cls.TRUSTED_PROXY_CIDRS.split(",") if cidr.strip()]
    
    @classmethod
    def log_startup_warnings(cls):
        """启动时输出警告信息"""
        import logging
        logger = logging.getLogger(__name__)
        
        if cls.TRUST_PROXY_HEADERS:
            cidrs = cls.get_trusted_proxy_cidrs_list()
            if not cidrs:
                logger.warning(
                    "⚠️  TRUST_PROXY_HEADERS=true 但 TRUSTED_PROXY_CIDRS 为空！"
                    "这意味着不信任任何来源的 forwarded 头，将回退到 request.client.host"
                )
            else:
                logger.warning(
                    f"⚠️  TRUST_PROXY_HEADERS=true，信任来自以下网段的 forwarded 头：{cidrs}"
                )
                logger.warning(
                    "   如果你的 Relay 可能被同一私网的非可信客户端直连，请显式配置为反代/LB 的固定网段！"
                )


config = Config()
