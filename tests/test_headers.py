"""
测试头部处理和真实IP透明代理
"""
import pytest
from unittest.mock import Mock, patch
from fastapi import Request
from fastapi.datastructures import Headers

from app.headers import (
    is_ip_in_cidrs,
    parse_forwarded_header,
    parse_x_forwarded_for,
    get_client_ip,
    build_upstream_headers,
    HOP_BY_HOP_HEADERS
)
from app.config import config


class TestIPInCIDRs:
    """测试 IP 是否在 CIDR 范围内"""
    
    def test_ipv4_in_cidr(self):
        assert is_ip_in_cidrs("192.168.1.100", ["192.168.0.0/16"])
        assert is_ip_in_cidrs("10.0.0.1", ["10.0.0.0/8"])
        assert not is_ip_in_cidrs("8.8.8.8", ["192.168.0.0/16"])
    
    def test_ipv6_in_cidr(self):
        assert is_ip_in_cidrs("::1", ["::1/128"])
        assert is_ip_in_cidrs("2001:db8::1", ["2001:db8::/32"])
    
    def test_localhost(self):
        assert is_ip_in_cidrs("127.0.0.1", ["127.0.0.0/8"])
        assert is_ip_in_cidrs("127.0.0.5", ["127.0.0.0/8"])


class TestParseForwardedHeaders:
    """测试 Forwarded 头解析"""
    
    def test_parse_forwarded_simple(self):
        result = parse_forwarded_header("for=192.0.2.60")
        assert result == "192.0.2.60"
    
    def test_parse_forwarded_with_proto(self):
        result = parse_forwarded_header("for=192.0.2.60;proto=http")
        assert result == "192.0.2.60"
    
    def test_parse_x_forwarded_for_simple(self):
        result = parse_x_forwarded_for("203.0.113.195")
        assert result == "203.0.113.195"
    
    def test_parse_x_forwarded_for_multiple(self):
        result = parse_x_forwarded_for("203.0.113.195, 70.41.3.18, 150.172.238.178")
        assert result == "203.0.113.195"


class TestGetClientIP:
    """测试获取客户端真实 IP"""
    
    @patch('app.headers.config')
    def test_trust_proxy_false(self, mock_config):
        """不信任代理头时，直接返回 request.client.host"""
        mock_config.TRUST_PROXY_HEADERS = False
        
        mock_request = Mock(spec=Request)
        mock_request.client = Mock(host="1.2.3.4")
        mock_request.headers = Headers({"x-forwarded-for": "9.9.9.9"})
        
        result = get_client_ip(mock_request)
        assert result == "1.2.3.4"
    
    @patch('app.headers.config')
    def test_trust_proxy_true_from_trusted_cidr(self, mock_config):
        """信任代理头且来自可信网段，解析 XFF"""
        mock_config.TRUST_PROXY_HEADERS = True
        mock_config.get_trusted_proxy_cidrs_list = Mock(return_value=["127.0.0.0/8"])
        
        mock_request = Mock(spec=Request)
        mock_request.client = Mock(host="127.0.0.1")
        mock_request.headers = Headers({"x-forwarded-for": "9.9.9.9, 127.0.0.1"})
        
        result = get_client_ip(mock_request)
        assert result == "9.9.9.9"
    
    @patch('app.headers.config')
    def test_trust_proxy_true_from_untrusted(self, mock_config):
        """信任代理头但来自非可信网段，回退到直接 IP"""
        mock_config.TRUST_PROXY_HEADERS = True
        mock_config.get_trusted_proxy_cidrs_list = Mock(return_value=["127.0.0.0/8"])
        
        mock_request = Mock(spec=Request)
        mock_request.client = Mock(host="8.8.8.8")
        mock_request.headers = Headers({"x-forwarded-for": "9.9.9.9"})
        
        result = get_client_ip(mock_request)
        assert result == "8.8.8.8"


class TestBuildUpstreamHeaders:
    """测试构造上游请求头"""
    
    def test_hop_by_hop_headers_removed(self):
        """验证 hop-by-hop 头被剔除"""
        mock_request = Mock(spec=Request)
        mock_request.client = Mock(host="1.2.3.4")
        mock_request.headers = Headers({
            "content-type": "application/json",
            "connection": "keep-alive",  # 应被剔除
            "transfer-encoding": "chunked",  # 应被剔除
            "authorization": "Bearer token"
        })
        mock_request.url = Mock(scheme="https")
        
        result = build_upstream_headers(mock_request, "api.example.com")
        
        assert "content-type" in result
        assert "authorization" in result
        assert "connection" not in result
        assert "transfer-encoding" not in result
    
    def test_xff_appended(self):
        """验证 X-Forwarded-For 被正确追加"""
        mock_request = Mock(spec=Request)
        mock_request.client = Mock(host="1.2.3.4")
        mock_request.headers = Headers({
            "x-forwarded-for": "9.9.9.9"
        })
        mock_request.url = Mock(scheme="https")
        
        with patch('app.headers.config') as mock_config:
            mock_config.TRUST_PROXY_HEADERS = False
            result = build_upstream_headers(mock_request, "api.example.com")
        
        # 应追加客户端 IP
        assert result["x-forwarded-for"] == "9.9.9.9, 1.2.3.4"
    
    def test_real_ip_set(self):
        """验证 X-Real-IP 被正确设置"""
        mock_request = Mock(spec=Request)
        mock_request.client = Mock(host="1.2.3.4")
        mock_request.headers = Headers({})
        mock_request.url = Mock(scheme="https")
        
        with patch('app.headers.config') as mock_config:
            mock_config.TRUST_PROXY_HEADERS = False
            result = build_upstream_headers(mock_request, "api.example.com")
        
        assert result["x-real-ip"] == "1.2.3.4"
    
    def test_forwarded_proto_host_port(self):
        """验证 X-Forwarded-Proto/Host/Port 被补齐"""
        mock_request = Mock(spec=Request)
        mock_request.client = Mock(host="1.2.3.4")
        mock_request.headers = Headers({"host": "example.com"})
        mock_request.url = Mock(scheme="https")
        
        with patch('app.headers.config') as mock_config:
            mock_config.TRUST_PROXY_HEADERS = False
            result = build_upstream_headers(mock_request, "api.example.com")
        
        assert result["x-forwarded-proto"] == "https"
        assert result["x-forwarded-host"] == "example.com"
        assert "x-forwarded-port" in result
