"""
日志工具与 request_id 生成
"""
import logging
import uuid
from typing import Optional
from fastapi import Request

logger = logging.getLogger(__name__)


def get_or_generate_request_id(request: Request) -> str:
    """
    获取或生成 request_id
    
    优先使用客户端传入的 X-Request-Id，否则生成新的
    
    Args:
        request: FastAPI Request 对象
        
    Returns:
        request_id 字符串
    """
    request_id = request.headers.get("x-request-id")
    if not request_id:
        request_id = str(uuid.uuid4())
    return request_id


def log_request_info(
    request_id: str,
    path: str,
    upstream_url: str,
    anti_truncation_enabled: bool,
    client_ip: str,
    xff: str,
    **extra_fields
):
    """
    记录请求信息日志
    
    Args:
        request_id: 请求 ID
        path: 请求路径
        upstream_url: 上游 URL
        anti_truncation_enabled: 是否启用抗截断
        client_ip: 客户端 IP
        xff: X-Forwarded-For 值
        **extra_fields: 其他额外字段
    """
    logger.info(
        f"[{request_id}] {path} -> {upstream_url} | "
        f"anti_truncation={anti_truncation_enabled} | "
        f"client_ip={client_ip} | xff={xff}",
        extra={
            "request_id": request_id,
            "path": path,
            "upstream_url": upstream_url,
            "anti_truncation_enabled": anti_truncation_enabled,
            "client_ip": client_ip,
            "xff": xff,
            **extra_fields
        }
    )


def log_anti_truncation_attempt(
    request_id: str,
    attempt: int,
    done_marker_found: bool,
    collected_chars: int
):
    """
    记录抗截断尝试信息
    
    Args:
        request_id: 请求 ID
        attempt: 尝试次数
        done_marker_found: 是否找到 done marker
        collected_chars: 已收集字符数
    """
    logger.info(
        f"[{request_id}] 抗截断 attempt={attempt} | "
        f"done_marker_found={done_marker_found} | "
        f"collected_chars={collected_chars}"
    )


def log_error(
    request_id: str,
    error_type: str,
    error_message: str,
    **extra_fields
):
    """
    记录错误日志
    
    Args:
        request_id: 请求 ID
        error_type: 错误类型
        error_message: 错误消息
        **extra_fields: 其他额外字段
    """
    logger.error(
        f"[{request_id}] {error_type}: {error_message}",
        extra={
            "request_id": request_id,
            "error_type": error_type,
            "error_message": error_message,
            **extra_fields
        }
    )
