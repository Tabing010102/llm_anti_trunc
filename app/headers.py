"""
Header 透传与真实IP透明代理处理
"""
import ipaddress
import logging
from typing import Dict, Optional
from fastapi import Request

from app.config import config

logger = logging.getLogger(__name__)

# RFC 7230 hop-by-hop headers（不应透传）
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def is_ip_in_cidrs(ip_str: str, cidrs: list) -> bool:
    """
    检查 IP 是否在给定的 CIDR 列表中
    
    Args:
        ip_str: IP 地址字符串
        cidrs: CIDR 列表
        
    Returns:
        True 如果 IP 在任一 CIDR 范围内
    """
    try:
        ip = ipaddress.ip_address(ip_str)
        for cidr_str in cidrs:
            try:
                network = ipaddress.ip_network(cidr_str, strict=False)
                if ip in network:
                    return True
            except ValueError:
                logger.warning(f"无效的 CIDR: {cidr_str}")
                continue
        return False
    except ValueError:
        logger.warning(f"无效的 IP 地址: {ip_str}")
        return False


def parse_forwarded_header(forwarded: str) -> Optional[str]:
    """
    解析 Forwarded 头（RFC 7239），提取最左侧的 for= 参数
    
    例如: "for=192.0.2.60;proto=http;by=203.0.113.43" -> "192.0.2.60"
    
    Args:
        forwarded: Forwarded 头的值
        
    Returns:
        客户端 IP 或 None
    """
    # 简化实现：找到第一个 for= 参数
    parts = forwarded.split(";")
    for part in parts:
        part = part.strip()
        if part.lower().startswith("for="):
            value = part[4:].strip()
            # 移除可能的引号和方括号（IPv6）
            value = value.strip('"').strip("'")
            if value.startswith("[") and "]" in value:
                # IPv6: [2001:db8::1]:8080 -> 2001:db8::1
                value = value[1:value.index("]")]
            elif ":" in value and value.count(":") == 1:
                # IPv4 with port: 192.0.2.60:8080 -> 192.0.2.60
                value = value.split(":")[0]
            return value
    return None


def parse_x_forwarded_for(xff: str) -> Optional[str]:
    """
    解析 X-Forwarded-For 头，提取最左侧（最原始）的 IP
    
    例如: "203.0.113.195, 70.41.3.18, 150.172.238.178" -> "203.0.113.195"
    
    Args:
        xff: X-Forwarded-For 头的值
        
    Returns:
        客户端 IP 或 None
    """
    ips = [ip.strip() for ip in xff.split(",")]
    if ips:
        return ips[0]
    return None


def get_client_ip(request: Request) -> str:
    """
    获取客户端真实 IP
    
    根据 TRUST_PROXY_HEADERS 和 TRUSTED_PROXY_CIDRS 配置决定：
    - 如果不信任代理头，直接返回 request.client.host
    - 如果信任代理头，且请求来自可信网段，则解析 Forwarded/X-Forwarded-For
    - 否则回退到 request.client.host
    
    Args:
        request: FastAPI Request 对象
        
    Returns:
        客户端真实 IP 地址
    """
    # 直接连接的客户端 IP
    direct_ip = request.client.host if request.client else "unknown"
    
    # 如果不信任代理头，直接返回
    if not config.TRUST_PROXY_HEADERS:
        return direct_ip
    
    # 获取可信 CIDR 列表
    trusted_cidrs = config.get_trusted_proxy_cidrs_list()
    
    # 如果没有配置可信 CIDR，回退到直接 IP
    if not trusted_cidrs:
        logger.debug(f"TRUST_PROXY_HEADERS=true 但 TRUSTED_PROXY_CIDRS 为空，使用直接 IP: {direct_ip}")
        return direct_ip
    
    # 检查直接连接的 IP 是否在可信网段内
    if not is_ip_in_cidrs(direct_ip, trusted_cidrs):
        logger.debug(f"直接连接 IP {direct_ip} 不在可信网段内，不解析 forwarded 头")
        return direct_ip
    
    # 尝试从 Forwarded 头解析（RFC 7239，优先级更高）
    forwarded = request.headers.get("forwarded")
    if forwarded:
        client_ip = parse_forwarded_header(forwarded)
        if client_ip:
            logger.debug(f"从 Forwarded 头解析到客户端 IP: {client_ip}")
            return client_ip
    
    # 尝试从 X-Forwarded-For 解析
    xff = request.headers.get("x-forwarded-for")
    if xff:
        client_ip = parse_x_forwarded_for(xff)
        if client_ip:
            logger.debug(f"从 X-Forwarded-For 头解析到客户端 IP: {client_ip}")
            return client_ip
    
    # 都没有，回退到直接 IP
    logger.debug(f"未找到 forwarded 头，使用直接 IP: {direct_ip}")
    return direct_ip


def build_upstream_headers(request: Request, upstream_host: str) -> Dict[str, str]:
    """
    构造发送给上游的请求头
    
    规则：
    1. 透传所有入站头，但剔除 hop-by-hop 头
    2. 不透传客户端的 Host（让 httpx 自动设置或使用上游 host）
    3. 获取客户端真实 IP
    4. 写入/追加 X-Forwarded-For、Forwarded、X-Real-IP
    5. 补齐 X-Forwarded-Proto、X-Forwarded-Host、X-Forwarded-Port
    
    Args:
        request: FastAPI Request 对象
        upstream_host: 上游主机名（从 upstream URL 提取）
        
    Returns:
        发送给上游的 headers 字典
    """
    # 1. 透传所有入站头（除了 hop-by-hop 和 Host）
    upstream_headers = {}
    for key, value in request.headers.items():
        lower_key = key.lower()
        if lower_key not in HOP_BY_HOP_HEADERS and lower_key != "host":
            upstream_headers[key] = value

    # 1.1 关键：不要透传 Content-Length（body 可能会被修改；由 httpx 重新计算）
    for k in list(upstream_headers.keys()):
        if k.lower() == "content-length":
            upstream_headers.pop(k, None)
    
    # 2. 获取客户端真实 IP
    client_ip = get_client_ip(request)
    
    # 3. 处理 X-Forwarded-For
    existing_xff = upstream_headers.get("x-forwarded-for", "").strip()
    if existing_xff:
        # 已存在，追加到末尾
        upstream_headers["x-forwarded-for"] = f"{existing_xff}, {client_ip}"
    else:
        # 不存在，创建
        upstream_headers["x-forwarded-for"] = client_ip
    
    # 4. 处理 Forwarded（RFC 7239）
    scheme = request.url.scheme
    host = request.headers.get("host", upstream_host)
    forwarded_elem = f"for={client_ip};proto={scheme};host={host}"
    
    existing_forwarded = upstream_headers.get("forwarded", "").strip()
    if existing_forwarded:
        # 追加
        upstream_headers["forwarded"] = f"{existing_forwarded}, {forwarded_elem}"
    else:
        upstream_headers["forwarded"] = forwarded_elem
    
    # 5. 设置 X-Real-IP（覆盖）
    upstream_headers["x-real-ip"] = client_ip
    
    # 6. 补齐其他 X-Forwarded-* 头（如果缺失）
    if "x-forwarded-proto" not in upstream_headers:
        upstream_headers["x-forwarded-proto"] = scheme
    
    if "x-forwarded-host" not in upstream_headers:
        upstream_headers["x-forwarded-host"] = host
    
    if "x-forwarded-port" not in upstream_headers:
        # 从 host 中提取端口，或使用默认端口
        port = "443" if scheme == "https" else "80"
        if ":" in host:
            port = host.split(":")[-1]
        upstream_headers["x-forwarded-port"] = port
    
    logger.debug(f"构造上游 headers: client_ip={client_ip}, XFF={upstream_headers['x-forwarded-for']}")
    
    return upstream_headers
