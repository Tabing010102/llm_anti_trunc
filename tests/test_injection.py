"""
测试注入功能
"""
import pytest
from unittest.mock import patch

from app.injection import (
    inject_done_marker_instruction_openai,
    inject_done_marker_instruction_gemini,
    inject_done_marker_instruction_claude,
    inject_continuation_openai,
    inject_continuation_gemini,
    inject_continuation_claude
)


class TestInjectDoneMarker:
    """测试 done marker 指令注入"""
    
    @patch('app.injection.config')
    def test_openai_no_system(self, mock_config):
        """测试 OpenAI 注入（无 system 消息）"""
        mock_config.ANTI_TRUNCATION_DONE_MARKER = "[done]"
        
        body = {
            "messages": [
                {"role": "user", "content": "Hello"}
            ]
        }
        
        result = inject_done_marker_instruction_openai(body)
        
        # 应该在最前插入 system 消息
        assert result["messages"][0]["role"] == "system"
        assert "[done]" in result["messages"][0]["content"]
        assert result["messages"][1]["role"] == "user"
    
    @patch('app.injection.config')
    def test_openai_with_system(self, mock_config):
        """测试 OpenAI 注入（已有 system 消息）"""
        mock_config.ANTI_TRUNCATION_DONE_MARKER = "[done]"
        
        body = {
            "messages": [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hello"}
            ]
        }
        
        result = inject_done_marker_instruction_openai(body)
        
        # 应该合并到已有 system
        assert result["messages"][0]["role"] == "system"
        assert "[done]" in result["messages"][0]["content"]
        assert "You are helpful" in result["messages"][0]["content"]
    
    @patch('app.injection.config')
    def test_gemini_injection(self, mock_config):
        """测试 Gemini 注入"""
        mock_config.ANTI_TRUNCATION_DONE_MARKER = "[done]"
        
        body = {
            "contents": [
                {"role": "user", "parts": [{"text": "Hello"}]}
            ]
        }
        
        result = inject_done_marker_instruction_gemini(body)
        
        # 应该创建 systemInstruction
        assert "systemInstruction" in result
        assert "parts" in result["systemInstruction"]
        assert "[done]" in result["systemInstruction"]["parts"][0]["text"]
    
    @patch('app.injection.config')
    def test_claude_injection(self, mock_config):
        """测试 Claude 注入"""
        mock_config.ANTI_TRUNCATION_DONE_MARKER = "[done]"
        
        body = {
            "messages": [
                {"role": "user", "content": "Hello"}
            ]
        }
        
        result = inject_done_marker_instruction_claude(body)
        
        # 应该创建 system
        assert "system" in result
        assert "[done]" in result["system"]


class TestInjectContinuation:
    """测试续写上下文注入"""
    
    def test_openai_continuation(self):
        """测试 OpenAI 续写注入"""
        body = {
            "messages": [
                {"role": "user", "content": "Hello"}
            ]
        }
        
        result = inject_continuation_openai(body, "已输出内容", "请继续")
        
        # 应该追加 assistant 和 user 消息
        assert len(result["messages"]) == 3
        assert result["messages"][1]["role"] == "assistant"
        assert result["messages"][1]["content"] == "已输出内容"
        assert result["messages"][2]["role"] == "user"
        assert result["messages"][2]["content"] == "请继续"
    
    def test_gemini_continuation(self):
        """测试 Gemini 续写注入"""
        body = {
            "contents": [
                {"role": "user", "parts": [{"text": "Hello"}]}
            ]
        }
        
        result = inject_continuation_gemini(body, "已输出内容", "请继续")
        
        # 应该追加 model 和 user
        assert len(result["contents"]) == 3
        assert result["contents"][1]["role"] == "model"
        assert result["contents"][2]["role"] == "user"
    
    def test_claude_continuation(self):
        """测试 Claude 续写注入"""
        body = {
            "messages": [
                {"role": "user", "content": "Hello"}
            ]
        }
        
        result = inject_continuation_claude(body, "已输出内容", "请继续")
        
        # 应该追加 assistant 和 user
        assert len(result["messages"]) == 3
        assert result["messages"][1]["role"] == "assistant"
        assert result["messages"][2]["role"] == "user"
