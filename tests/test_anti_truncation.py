"""
测试抗截断功能
"""
import pytest
from unittest.mock import Mock, patch

from app.anti_truncation import (
    should_enable_anti_truncation,
    strip_model_prefix,
    get_continuation_prompt
)
from app.config import config


class TestShouldEnableAntiTruncation:
    """测试抗截断启用条件"""
    
    @patch('app.anti_truncation.config')
    def test_model_prefix_trigger(self, mock_config):
        """测试 model 前缀触发"""
        mock_config.ANTI_TRUNCATION_MODEL_PREFIX = "流式抗截断/"
        
        mock_request = Mock()
        mock_request.headers = Mock(get=Mock(return_value=""))
        mock_request.query_params = Mock(get=Mock(return_value=""))
        
        body = {"model": "流式抗截断/gpt-4"}
        
        result = should_enable_anti_truncation(mock_request, body, is_streaming=True)
        assert result is True
    
    def test_header_trigger(self):
        """测试 header 触发"""
        mock_request = Mock()
        mock_request.headers = Mock(get=Mock(return_value="true"))
        mock_request.query_params = Mock(get=Mock(return_value=""))
        
        result = should_enable_anti_truncation(mock_request, {}, is_streaming=True)
        assert result is True
    
    def test_query_trigger(self):
        """测试 query 参数触发"""
        mock_request = Mock()
        mock_request.headers = Mock(get=Mock(return_value=""))
        mock_request.query_params = Mock(get=Mock(side_effect=lambda k: "1" if k == "anti_truncation" else ""))
        
        result = should_enable_anti_truncation(mock_request, {}, is_streaming=True)
        assert result is True
    
    def test_non_streaming_not_enabled(self):
        """测试非流式不启用"""
        mock_request = Mock()
        mock_request.headers = Mock(get=Mock(return_value="true"))
        mock_request.query_params = Mock(get=Mock(return_value=""))
        
        result = should_enable_anti_truncation(mock_request, {}, is_streaming=False)
        assert result is False


class TestStripModelPrefix:
    """测试 model 前缀剥离"""
    
    @patch('app.anti_truncation.config')
    def test_strip_prefix(self, mock_config):
        """测试剥离前缀"""
        mock_config.ANTI_TRUNCATION_MODEL_PREFIX = "流式抗截断/"
        
        stripped, original = strip_model_prefix("流式抗截断/gpt-4")
        assert stripped == "gpt-4"
        assert original == "流式抗截断/gpt-4"
    
    @patch('app.anti_truncation.config')
    def test_no_prefix(self, mock_config):
        """测试无前缀"""
        mock_config.ANTI_TRUNCATION_MODEL_PREFIX = "流式抗截断/"
        
        stripped, original = strip_model_prefix("gpt-4")
        assert stripped == "gpt-4"
        assert original == "gpt-4"


class TestGetContinuationPrompt:
    """测试续写提示生成"""
    
    def test_short_text(self):
        """测试短文本"""
        prompt = get_continuation_prompt("Hello", 2)
        assert "Hello" in prompt
        assert "5 个字符" in prompt
    
    def test_long_text(self):
        """测试长文本（取最后 100 字符）"""
        long_text = "A" * 200
        prompt = get_continuation_prompt(long_text, 2)
        assert "200 个字符" in prompt
        # 应该只包含最后 100 字符
        assert long_text[-100:] in prompt
