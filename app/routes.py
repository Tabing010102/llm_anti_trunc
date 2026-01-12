"""
路由处理器模块（完整版，含抗截断集成）
"""
import asyncio
import json
import logging
from typing import Dict, Any, Optional
from fastapi import Request, Response
from fastapi.responses import StreamingResponse, JSONResponse

from app.config import config
from app.headers import build_upstream_headers, get_client_ip
from app.upstream import UpstreamClient, build_upstream_url, extract_host_from_url
from app.logging import get_or_generate_request_id, log_request_info, log_error
from app.anti_truncation import should_enable_anti_truncation, strip_model_prefix
from app.injection import (
    inject_done_marker_instruction_openai,
    inject_done_marker_instruction_gemini,
    inject_done_marker_instruction_claude
)
from app.streaming import (
    ProtocolType,
    create_streaming_response_with_anti_truncation
)

logger = logging.getLogger(__name__)


async def handle_openai_chat_completions(request: Request) -> Response:
    """
    处理 OpenAI Chat Completions 请求
    
    Args:
        request: FastAPI Request 对象
        
    Returns:
        Response 对象
    """
    # 生成 request_id
    request_id = get_or_generate_request_id(request)
    
    # 读取请求 body
    try:
        request_body = await request.json()
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_request",
                "message": f"无法解析 JSON: {e}",
                "request_id": request_id
            }
        )
    
    # 判断是否为流式请求
    is_streaming = request_body.get("stream", False)
    
    # 判断是否启用抗截断
    anti_trunc_enabled = should_enable_anti_truncation(
        request,
        request_body,
        is_streaming
    )
    
    # 构造上游 URL 和 headers
    upstream_base_url = config.UPSTREAM_OPENAI_BASE_URL
    path = "/v1/chat/completions"
    query_string = str(request.url.query) if request.url.query else ""
    
    upstream_host = extract_host_from_url(upstream_base_url)
    upstream_headers = build_upstream_headers(request, upstream_host)
    
    # 处理 model 前缀（如果启用抗截断）
    original_model = request_body.get("model", "")
    if anti_trunc_enabled and "model" in request_body:
        stripped_model, _ = strip_model_prefix(original_model)
        request_body["model"] = stripped_model
    
    # 注入 done marker 指令（如果启用抗截断且为流式）
    if anti_trunc_enabled and is_streaming:
        request_body = inject_done_marker_instruction_openai(request_body)
    
    # 记录日志
    client_ip = get_client_ip(request)
    xff = upstream_headers.get("x-forwarded-for", "")
    log_request_info(
        request_id=request_id,
        path=path,
        upstream_url=upstream_base_url,
        anti_truncation_enabled=anti_trunc_enabled,
        client_ip=client_ip,
        xff=xff,
        method="POST",
        streaming=is_streaming,
        model=original_model
    )
    
    # 根据是否流式和是否抗截断，选择处理方式
    if is_streaming:
        if anti_trunc_enabled:
            # 流式 + 抗截断
            disconnect_event = asyncio.Event()
            
            async def stream_with_disconnect_check():
                try:
                    async for chunk in create_streaming_response_with_anti_truncation(
                        protocol=ProtocolType.OPENAI,
                        request_id=request_id,
                        upstream_base_url=upstream_base_url,
                        path=path,
                        headers=upstream_headers,
                        request_body=request_body,
                        query_string=query_string,
                        client_disconnect_check=disconnect_event
                    ):
                        yield chunk
                except asyncio.CancelledError:
                    logger.warning(f"[{request_id}] 流式传输被取消")
                    disconnect_event.set()
                    raise
            
            return StreamingResponse(
                stream_with_disconnect_check(),
                media_type="text/event-stream",
                headers={
                    "x-request-id": request_id,
                    "x-anti-truncation": "enabled",
                    "cache-control": "no-cache",
                    "connection": "keep-alive"
                }
            )
        else:
            # 流式，无抗截断
            return await _simple_streaming_proxy(
                request_id,
                upstream_base_url,
                path,
                upstream_headers,
                request_body,
                query_string
            )
    else:
        # 非流式
        if anti_trunc_enabled:
            # 非流式不启用抗截断，添加提示头
            response = await _simple_proxy(
                request_id,
                upstream_base_url,
                path,
                upstream_headers,
                request_body,
                query_string
            )
            response.headers["x-anti-truncation-ignored"] = "non-streaming"
            return response
        else:
            return await _simple_proxy(
                request_id,
                upstream_base_url,
                path,
                upstream_headers,
                request_body,
                query_string
            )


async def handle_gemini_generate_content(
    request: Request,
    model: str,
    is_streaming: bool,
    is_beta: bool = False
) -> Response:
    """
    处理 Gemini generateContent 请求
    
    Args:
        request: FastAPI Request 对象
        model: 模型名称
        is_streaming: 是否流式
        is_beta: 是否 beta 版本
        
    Returns:
        Response 对象
    """
    # 生成 request_id
    request_id = get_or_generate_request_id(request)
    
    # 读取请求 body
    try:
        request_body = await request.json()
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_request",
                "message": f"无法解析 JSON: {e}",
                "request_id": request_id
            }
        )
    
    # 判断是否启用抗截断（Gemini 的 model 在路径中）
    # 创建临时 body 带 model 字段用于判断
    temp_body = {**request_body, "model": model}
    anti_trunc_enabled = should_enable_anti_truncation(
        request,
        temp_body,
        is_streaming
    )
    
    # 处理 model 前缀
    original_model = model
    if anti_trunc_enabled:
        model, _ = strip_model_prefix(model)
    
    # 构造路径
    version = "v1beta" if is_beta else "v1"
    action = "streamGenerateContent" if is_streaming else "generateContent"
    path = f"/{version}/models/{model}:{action}"
    
    # 注入 done marker 指令
    if anti_trunc_enabled and is_streaming:
        request_body = inject_done_marker_instruction_gemini(request_body)
    
    # 构造上游 headers
    upstream_base_url = config.UPSTREAM_GEMINI_BASE_URL
    upstream_host = extract_host_from_url(upstream_base_url)
    upstream_headers = build_upstream_headers(request, upstream_host)
    query_string = str(request.url.query) if request.url.query else ""
    
    # 记录日志
    client_ip = get_client_ip(request)
    xff = upstream_headers.get("x-forwarded-for", "")
    log_request_info(
        request_id=request_id,
        path=path,
        upstream_url=upstream_base_url,
        anti_truncation_enabled=anti_trunc_enabled,
        client_ip=client_ip,
        xff=xff,
        method="POST",
        streaming=is_streaming,
        model=original_model
    )
    
    # 处理请求
    if is_streaming:
        if anti_trunc_enabled:
            disconnect_event = asyncio.Event()
            
            async def stream_with_disconnect_check():
                try:
                    async for chunk in create_streaming_response_with_anti_truncation(
                        protocol=ProtocolType.GEMINI,
                        request_id=request_id,
                        upstream_base_url=upstream_base_url,
                        path=path,
                        headers=upstream_headers,
                        request_body=request_body,
                        query_string=query_string,
                        client_disconnect_check=disconnect_event
                    ):
                        yield chunk
                except asyncio.CancelledError:
                    logger.warning(f"[{request_id}] 流式传输被取消")
                    disconnect_event.set()
                    raise
            
            return StreamingResponse(
                stream_with_disconnect_check(),
                media_type="text/event-stream",
                headers={
                    "x-request-id": request_id,
                    "x-anti-truncation": "enabled"
                }
            )
        else:
            return await _simple_streaming_proxy(
                request_id,
                upstream_base_url,
                path,
                upstream_headers,
                request_body,
                query_string
            )
    else:
        response = await _simple_proxy(
            request_id,
            upstream_base_url,
            path,
            upstream_headers,
            request_body,
            query_string
        )
        if anti_trunc_enabled:
            response.headers["x-anti-truncation-ignored"] = "non-streaming"
        return response


async def handle_claude_messages(request: Request) -> Response:
    """
    处理 Claude Messages 请求
    
    Args:
        request: FastAPI Request 对象
        
    Returns:
        Response 对象
    """
    # 生成 request_id
    request_id = get_or_generate_request_id(request)
    
    # 读取请求 body
    try:
        request_body = await request.json()
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_request",
                "message": f"无法解析 JSON: {e}",
                "request_id": request_id
            }
        )
    
    # 判断是否为流式
    is_streaming = request_body.get("stream", False)
    
    # 判断是否启用抗截断
    anti_trunc_enabled = should_enable_anti_truncation(
        request,
        request_body,
        is_streaming
    )
    
    # 处理 model 前缀
    original_model = request_body.get("model", "")
    if anti_trunc_enabled and "model" in request_body:
        stripped_model, _ = strip_model_prefix(original_model)
        request_body["model"] = stripped_model
    
    # 注入 done marker 指令
    if anti_trunc_enabled and is_streaming:
        request_body = inject_done_marker_instruction_claude(request_body)
    
    # 构造上游 URL 和 headers
    upstream_base_url = config.UPSTREAM_CLAUDE_BASE_URL
    path = "/v1/messages"
    upstream_host = extract_host_from_url(upstream_base_url)
    upstream_headers = build_upstream_headers(request, upstream_host)
    query_string = str(request.url.query) if request.url.query else ""
    
    # 记录日志
    client_ip = get_client_ip(request)
    xff = upstream_headers.get("x-forwarded-for", "")
    log_request_info(
        request_id=request_id,
        path=path,
        upstream_url=upstream_base_url,
        anti_truncation_enabled=anti_trunc_enabled,
        client_ip=client_ip,
        xff=xff,
        method="POST",
        streaming=is_streaming,
        model=original_model
    )
    
    # 处理请求
    if is_streaming:
        if anti_trunc_enabled:
            disconnect_event = asyncio.Event()
            
            async def stream_with_disconnect_check():
                try:
                    async for chunk in create_streaming_response_with_anti_truncation(
                        protocol=ProtocolType.CLAUDE,
                        request_id=request_id,
                        upstream_base_url=upstream_base_url,
                        path=path,
                        headers=upstream_headers,
                        request_body=request_body,
                        query_string=query_string,
                        client_disconnect_check=disconnect_event
                    ):
                        yield chunk
                except asyncio.CancelledError:
                    logger.warning(f"[{request_id}] 流式传输被取消")
                    disconnect_event.set()
                    raise
            
            return StreamingResponse(
                stream_with_disconnect_check(),
                media_type="text/event-stream",
                headers={
                    "x-request-id": request_id,
                    "x-anti-truncation": "enabled"
                }
            )
        else:
            return await _simple_streaming_proxy(
                request_id,
                upstream_base_url,
                path,
                upstream_headers,
                request_body,
                query_string
            )
    else:
        response = await _simple_proxy(
            request_id,
            upstream_base_url,
            path,
            upstream_headers,
            request_body,
            query_string
        )
        if anti_trunc_enabled:
            response.headers["x-anti-truncation-ignored"] = "non-streaming"
        return response


# ========== 辅助函数 ==========

async def _simple_proxy(
    request_id: str,
    upstream_base_url: str,
    path: str,
    headers: Dict[str, str],
    body: Dict[str, Any],
    query_string: str
) -> Response:
    """简单代理（非流式，无抗截断）"""
    try:
        async with UpstreamClient() as client:
            upstream_url = build_upstream_url(upstream_base_url, path)
            if query_string:
                upstream_url = f"{upstream_url}?{query_string}"
            
            response = await client.request(
                method="POST",
                url=upstream_url,
                headers=headers,
                json=body,
                stream=False
            )
            
            # 构造响应头（剔除 hop-by-hop）
            response_headers = _filter_response_headers(response.headers)
            response_headers["x-request-id"] = request_id
            
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=response_headers
            )
    except Exception as e:
        log_error(request_id, "proxy_error", str(e))
        if hasattr(e, 'response'):
            error_response = e.response
            response_headers = _filter_response_headers(error_response.headers)
            response_headers["x-request-id"] = request_id
            return Response(
                content=error_response.content,
                status_code=error_response.status_code,
                headers=response_headers
            )
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": str(e), "request_id": request_id}
        )


async def _simple_streaming_proxy(
    request_id: str,
    upstream_base_url: str,
    path: str,
    headers: Dict[str, str],
    body: Dict[str, Any],
    query_string: str
) -> StreamingResponse:
    """简单流式代理（无抗截断）"""
    async def stream_generator():
        try:
            async with UpstreamClient() as client:
                upstream_url = build_upstream_url(upstream_base_url, path)
                if query_string:
                    upstream_url = f"{upstream_url}?{query_string}"
                
                async for chunk in client.stream_request(
                    method="POST",
                    url=upstream_url,
                    headers=headers,
                    json=body
                ):
                    yield chunk
        except Exception as e:
            log_error(request_id, "streaming_error", str(e))
            error_msg = json.dumps({
                "error": "streaming_error",
                "message": str(e),
                "request_id": request_id
            })
            yield f"data: {error_msg}\n\n".encode("utf-8")
    
    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={"x-request-id": request_id}
    )


def _filter_response_headers(headers) -> Dict[str, str]:
    """过滤响应头（剔除 hop-by-hop）"""
    hop_by_hop = {
        "connection", "keep-alive", "proxy-authenticate",
        "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade"
    }
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in hop_by_hop
    }
