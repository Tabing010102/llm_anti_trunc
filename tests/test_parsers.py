"""
测试协议解析器
"""
import pytest
import json

from app.parsers.openai_sse import OpenAISSEParser
from app.parsers.gemini_sse import GeminiSSEParser
from app.parsers.claude_sse import ClaudeSSEParser


class TestOpenAISSEParser:
    """测试 OpenAI SSE 解析器"""
    
    def test_parse_content(self):
        """测试解析增量内容"""
        chunk_data = {
            "choices": [
                {"delta": {"content": "Hello"}}
            ]
        }
        chunk = f"data: {json.dumps(chunk_data)}\n\n".encode("utf-8")
        
        text, _ = OpenAISSEParser.parse_chunk(chunk)
        assert text == "Hello"
    
    def test_parse_done(self):
        """测试解析 [DONE] 标记"""
        chunk = b"data: [DONE]\n\n"
        
        text, _ = OpenAISSEParser.parse_chunk(chunk)
        assert text is None
    
    def test_strip_done_marker(self):
        """测试移除 done marker"""
        chunk_data = {
            "choices": [
                {"delta": {"content": "完成[done]"}}
            ]
        }
        chunk = f"data: {json.dumps(chunk_data)}\n\n".encode("utf-8")
        
        result = OpenAISSEParser.strip_done_marker(chunk, "[done]")
        result_text = result.decode("utf-8")
        
        # 应该移除 [done]
        assert "[done]" not in result_text
        assert "完成" in result_text


class TestGeminiSSEParser:
    """测试 Gemini SSE 解析器"""
    
    def test_parse_content(self):
        """测试解析增量内容"""
        chunk_data = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Hello"}
                        ]
                    }
                }
            ]
        }
        chunk = f"data: {json.dumps(chunk_data)}\n\n".encode("utf-8")
        
        text, _ = GeminiSSEParser.parse_chunk(chunk)
        assert text == "Hello"
    
    def test_strip_done_marker(self):
        """测试移除 done marker"""
        chunk_data = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "完成[done]"}
                        ]
                    }
                }
            ]
        }
        chunk = f"data: {json.dumps(chunk_data)}\n\n".encode("utf-8")
        
        result = GeminiSSEParser.strip_done_marker(chunk, "[done]")
        result_text = result.decode("utf-8")
        
        assert "[done]" not in result_text
        assert "完成" in result_text


class TestClaudeSSEParser:
    """测试 Claude SSE 解析器"""
    
    def test_parse_content_block_delta(self):
        """测试解析 content_block_delta 事件"""
        chunk = b"event: content_block_delta\ndata: {\"delta\":{\"text\":\"Hello\"}}\n\n"
        
        text, _ = ClaudeSSEParser.parse_chunk(chunk)
        assert text == "Hello"
    
    def test_parse_message_stop(self):
        """测试解析 message_stop 事件"""
        chunk = b"event: message_stop\ndata: {}\n\n"
        
        text, _ = ClaudeSSEParser.parse_chunk(chunk)
        assert text is None
    
    def test_strip_done_marker(self):
        """测试移除 done marker"""
        chunk = "event: content_block_delta\ndata: {\"delta\":{\"text\":\"完成[done]\"}}\n\n".encode("utf-8")
        
        result = ClaudeSSEParser.strip_done_marker(chunk, "[done]")
        result_text = result.decode("utf-8")
        
        assert "[done]" not in result_text
        assert "完成" in result_text
