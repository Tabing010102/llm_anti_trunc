"""
上游请求处理模块
"""
import httpx
import logging
from typing import Dict, Any, Optional, AsyncIterator
from urllib.parse import urljoin, urlparse

from app.config import config

logger = logging.getLogger(__name__)


class UpstreamClient:
    """上游 HTTP 客户端"""
    
    def __init__(self):
        self.client: Optional[httpx.AsyncClient] = None
    
    async def __aenter__(self):
        """创建 httpx 客户端"""
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=config.UPSTREAM_CONNECT_TIMEOUT_SECONDS,
                read=config.UPSTREAM_TIMEOUT_SECONDS,
                write=config.UPSTREAM_TIMEOUT_SECONDS,
                pool=config.UPSTREAM_CONNECT_TIMEOUT_SECONDS
            ),
            follow_redirects=False,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """关闭客户端"""
        if self.client:
            await self.client.aclose()
    
    async def request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        content: Optional[bytes] = None,
        json: Optional[Dict[str, Any]] = None,
        stream: bool = False
    ) -> httpx.Response:
        """
        发送请求到上游
        
        Args:
            method: HTTP 方法
            url: 完整 URL
            headers: 请求头
            content: 原始字节内容（与 json 互斥）
            json: JSON 数据（与 content 互斥）
            stream: 是否流式响应
            
        Returns:
            httpx.Response 对象
        """
        if not self.client:
            raise RuntimeError("UpstreamClient 未初始化")
        
        logger.debug(f"上游请求: {method} {url} | stream={stream}")
        
        return await self.client.request(
            method=method,
            url=url,
            headers=headers,
            content=content,
            json=json,
            timeout=httpx.Timeout(
                connect=config.UPSTREAM_CONNECT_TIMEOUT_SECONDS,
                read=config.UPSTREAM_TIMEOUT_SECONDS if not stream else None,  # 流式不超时
                write=config.UPSTREAM_TIMEOUT_SECONDS,
                pool=config.UPSTREAM_CONNECT_TIMEOUT_SECONDS
            )
        )
    
    async def stream_request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        content: Optional[bytes] = None,
        json: Optional[Dict[str, Any]] = None
    ) -> AsyncIterator[bytes]:
        """
        发送流式请求到上游并逐块生成响应
        
        Args:
            method: HTTP 方法
            url: 完整 URL
            headers: 请求头
            content: 原始字节内容（与 json 互斥）
            json: JSON 数据（与 content 互斥）
            
        Yields:
            响应字节块
        """
        if not self.client:
            raise RuntimeError("UpstreamClient 未初始化")
        
        logger.debug(f"上游流式请求: {method} {url}")
        
        async with self.client.stream(
            method=method,
            url=url,
            headers=headers,
            content=content,
            json=json,
            timeout=httpx.Timeout(
                connect=config.UPSTREAM_CONNECT_TIMEOUT_SECONDS,
                read=None,  # 流式不超时
                write=config.UPSTREAM_TIMEOUT_SECONDS,
                pool=config.UPSTREAM_CONNECT_TIMEOUT_SECONDS
            )
        ) as response:
            # 记录响应状态
            logger.debug(f"上游响应状态: {response.status_code}")
            
            # 如果是错误响应，读取完整内容后抛出
            if response.status_code >= 400:
                error_body = await response.aread()
                logger.warning(f"上游错误响应 {response.status_code}: {error_body[:500]}")
                # 将错误信息作为异常抛出，由调用方处理
                raise httpx.HTTPStatusError(
                    f"上游返回 {response.status_code}",
                    request=response.request,
                    response=response
                )
            
            # 逐块生成响应内容
            async for chunk in response.aiter_bytes():
                if chunk:
                    yield chunk


def build_upstream_url(base_url: str, path: str) -> str:
    """
    构造上游完整 URL
    
    Args:
        base_url: 上游 base URL（如 https://api.openai.com）
        path: 请求路径（如 /v1/chat/completions）
        
    Returns:
        完整的上游 URL
    """
    # 确保 base_url 不以 / 结尾
    base_url = base_url.rstrip("/")
    # 确保 path 以 / 开头
    if not path.startswith("/"):
        path = f"/{path}"
    
    return f"{base_url}{path}"


def extract_host_from_url(url: str) -> str:
    """
    从 URL 中提取 host
    
    Args:
        url: 完整 URL
        
    Returns:
        host 字符串
    """
    parsed = urlparse(url)
    return parsed.netloc
