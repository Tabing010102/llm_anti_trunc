"""
流式抗截断处理器
"""
import asyncio
import logging
from typing import Dict, Any, Optional, AsyncIterator, Literal
from enum import Enum

import httpx

from app.config import config
from app.parsers import OpenAISSEParser, GeminiSSEParser, ClaudeSSEParser
from app.upstream import UpstreamClient, build_upstream_url
from app.injection import (
    inject_continuation_openai,
    inject_continuation_gemini,
    inject_continuation_claude
)
from app.anti_truncation import get_continuation_prompt
from app.logging import log_anti_truncation_attempt

logger = logging.getLogger(__name__)


class ProtocolType(str, Enum):
    """协议类型"""
    OPENAI = "openai"
    GEMINI = "gemini"
    CLAUDE = "claude"


class StreamingAntiTruncationProcessor:
    """流式抗截断处理器"""
    
    def __init__(
        self,
        protocol: ProtocolType,
        request_id: str,
        upstream_base_url: str,
        path: str,
        headers: Dict[str, str],
        request_body: Dict[str, Any],
        query_string: str = ""
    ):
        """
        初始化处理器
        
        Args:
            protocol: 协议类型
            request_id: 请求 ID
            upstream_base_url: 上游 base URL
            path: 请求路径
            headers: 上游请求头
            request_body: 请求 body（JSON）
            query_string: 查询字符串
        """
        self.protocol = protocol
        self.request_id = request_id
        self.upstream_base_url = upstream_base_url
        self.path = path
        self.headers = headers
        self.original_body = request_body
        self.query_string = query_string
        
        # 状态
        self.collected_text = ""
        self.done_marker_found = False
        self.attempt = 0
        self.max_attempts = config.ANTI_TRUNCATION_MAX_ATTEMPTS
        self.done_marker = config.ANTI_TRUNCATION_DONE_MARKER
        
        # 解析器
        if protocol == ProtocolType.OPENAI:
            self.parser = OpenAISSEParser()
        elif protocol == ProtocolType.GEMINI:
            self.parser = GeminiSSEParser()
        elif protocol == ProtocolType.CLAUDE:
            self.parser = ClaudeSSEParser()
        else:
            raise ValueError(f"不支持的协议类型: {protocol}")
        
        # 客户端断连标志
        self.client_disconnected = False
        
        # 可重试的上游状态码（瞬时错误/限流）
        self.retryable_upstream_status_codes = {
            408,  # Request Timeout
            425,  # Too Early（部分代理/网关会用）
            429,  # Too Many Requests
            500,  # Internal Server Error
            502,  # Bad Gateway
            503,  # Service Unavailable
            504,  # Gateway Timeout
        }
    
    async def process_stream(
        self,
        client_disconnect_check: Optional[asyncio.Event] = None
    ) -> AsyncIterator[bytes]:
        """
        处理流式响应，支持抗截断
        
        Args:
            client_disconnect_check: 客户端断连事件（可选）
            
        Yields:
            处理后的字节块
        """
        while self.attempt < self.max_attempts and not self.done_marker_found:
            self.attempt += 1
            
            logger.info(
                f"[{self.request_id}] 抗截断 attempt {self.attempt}/{self.max_attempts}"
            )
            
            # 构造当前请求 body
            if self.attempt == 1:
                # 第一次，使用原始 body（已注入 done marker 指令）
                current_body = self.original_body
            else:
                # 续写，注入上下文
                continuation_prompt = get_continuation_prompt(
                    self.collected_text,
                    self.attempt
                )
                current_body = self._inject_continuation(
                    self.original_body,
                    self.collected_text,
                    continuation_prompt
                )
            
            # 发起上游请求
            chunk_count = 0
            attempt_done_marker_found = False
            
            try:
                async with UpstreamClient() as upstream_client:
                    upstream_url = build_upstream_url(
                        self.upstream_base_url,
                        self.path
                    )
                    if self.query_string:
                        upstream_url = f"{upstream_url}?{self.query_string}"
                    
                    async for chunk in upstream_client.stream_request(
                        method="POST",
                        url=upstream_url,
                        headers=self.headers,
                        json=current_body
                    ):
                        # 检查客户端是否断连
                        if client_disconnect_check and client_disconnect_check.is_set():
                            logger.warning(
                                f"[{self.request_id}] 客户端断开连接，取消流式传输"
                            )
                            self.client_disconnected = True
                            return
                        
                        chunk_count += 1
                        
                        # 解析 chunk，提取文本
                        delta_text, _ = self.parser.parse_chunk(chunk)
                        
                        if delta_text:
                            # 收集文本
                            self.collected_text += delta_text
                            
                            # 检查是否包含 done marker
                            if self.done_marker in delta_text:
                                self.done_marker_found = True
                                attempt_done_marker_found = True
                                logger.info(
                                    f"[{self.request_id}] 检测到 done marker！"
                                )
                        
                        # 清理 done marker 后转发给客户端
                        cleaned_chunk = self.parser.strip_done_marker(
                            chunk,
                            self.done_marker
                        )
                        
                        yield cleaned_chunk
                        
                        # 一旦检测到 done marker，就主动结束本次上游流，避免等待上游继续输出导致下游取消
                        if self.done_marker_found:
                            break
                
                # 记录本次 attempt
                log_anti_truncation_attempt(
                    request_id=self.request_id,
                    attempt=self.attempt,
                    done_marker_found=attempt_done_marker_found,
                    collected_chars=len(self.collected_text)
                )
                
                # 如果找到 done marker，结束
                if self.done_marker_found:
                    logger.info(
                        f"[{self.request_id}] 抗截断完成，共 {self.attempt} 次尝试，"
                        f"收集 {len(self.collected_text)} 字符"
                    )
                    break
                
                # 如果未找到 done marker，但已是最后一次尝试
                if self.attempt >= self.max_attempts:
                    logger.warning(
                        f"[{self.request_id}] 达到最大尝试次数 {self.max_attempts}，"
                        f"但未检测到 done marker"
                    )
                    # 发送一个特殊的响应头提示（通过 SSE 注释）
                    yield f": X-Anti-Truncation-Max-Attempts-Reached\n\n".encode("utf-8")
                    break
                
                # 否则，准备下一次续写
                logger.info(
                    f"[{self.request_id}] 未检测到 done marker，准备续写..."
                )

            except asyncio.CancelledError:
                # 不要吞掉取消信号：让路由层记录“被取消”，并尽快终止
                raise

            except httpx.HTTPStatusError as e:
                status_code = None
                try:
                    status_code = e.response.status_code if e.response else None
                except Exception:
                    status_code = None
                
                # 上游瞬时错误：允许在剩余 attempt 内重试
                if (
                    status_code in self.retryable_upstream_status_codes
                    and self.attempt < self.max_attempts
                    and not self.done_marker_found
                    and not self.client_disconnected
                ):
                    logger.warning(
                        f"[{self.request_id}] 上游返回 {status_code}，将进行重试 "
                        f"(attempt {self.attempt}/{self.max_attempts})"
                    )
                    continue
                
                # 不可重试或已无剩余 attempt：向下游发送错误事件并结束
                logger.error(
                    f"[{self.request_id}] 上游错误 (attempt {self.attempt}): {e}",
                    exc_info=True
                )
                import json
                error_event = {
                    "error": "upstream_error",
                    "status_code": status_code,
                    "message": str(e),
                    "attempt": self.attempt,
                    "request_id": self.request_id
                }
                yield f"data: {json.dumps(error_event)}\n\n".encode("utf-8")
                break

            except Exception as e:
                logger.error(
                    f"[{self.request_id}] 流式处理异常 (attempt {self.attempt}): {e}",
                    exc_info=True
                )
                # 发送错误事件
                import json
                error_event = {
                    "error": "streaming_error",
                    "message": str(e),
                    "attempt": self.attempt,
                    "request_id": self.request_id
                }
                yield f"data: {json.dumps(error_event)}\n\n".encode("utf-8")
                break
        
        # 流结束
        logger.debug(f"[{self.request_id}] 流式处理结束")
    
    def _inject_continuation(
        self,
        original_body: Dict[str, Any],
        collected_text: str,
        continuation_prompt: str
    ) -> Dict[str, Any]:
        """
        注入续写上下文
        
        Args:
            original_body: 原始请求 body
            collected_text: 已收集的文本
            continuation_prompt: 续写提示
            
        Returns:
            注入后的 body
        """
        if self.protocol == ProtocolType.OPENAI:
            return inject_continuation_openai(
                original_body,
                collected_text,
                continuation_prompt
            )
        elif self.protocol == ProtocolType.GEMINI:
            return inject_continuation_gemini(
                original_body,
                collected_text,
                continuation_prompt
            )
        elif self.protocol == ProtocolType.CLAUDE:
            return inject_continuation_claude(
                original_body,
                collected_text,
                continuation_prompt
            )
        else:
            raise ValueError(f"不支持的协议类型: {self.protocol}")


async def create_streaming_response_with_anti_truncation(
    protocol: ProtocolType,
    request_id: str,
    upstream_base_url: str,
    path: str,
    headers: Dict[str, str],
    request_body: Dict[str, Any],
    query_string: str = "",
    client_disconnect_check: Optional[asyncio.Event] = None
) -> AsyncIterator[bytes]:
    """
    创建带抗截断的流式响应
    
    Args:
        protocol: 协议类型
        request_id: 请求 ID
        upstream_base_url: 上游 base URL
        path: 请求路径
        headers: 上游请求头
        request_body: 请求 body（已注入 done marker 指令）
        query_string: 查询字符串
        client_disconnect_check: 客户端断连事件
        
    Yields:
        处理后的字节块
    """
    processor = StreamingAntiTruncationProcessor(
        protocol=protocol,
        request_id=request_id,
        upstream_base_url=upstream_base_url,
        path=path,
        headers=headers,
        request_body=request_body,
        query_string=query_string
    )
    
    async for chunk in processor.process_stream(client_disconnect_check):
        yield chunk
