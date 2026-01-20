import json
import httpx
import pytest


def _openai_sse_chunk(content: str) -> bytes:
    # OpenAI SSE: data: {"choices":[{"delta":{"content":"..."}}]}\n\n
    payload = {"choices": [{"delta": {"content": content}}]}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


@pytest.mark.asyncio
async def test_retry_when_stream_ends_without_done_marker(monkeypatch):
    from app.streaming import StreamingAntiTruncationProcessor, ProtocolType
    import app.streaming as streaming_mod

    monkeypatch.setattr(streaming_mod.config, "ANTI_TRUNCATION_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(streaming_mod.config, "ANTI_TRUNCATION_DONE_MARKER", "[done]")

    # attempt1: 没有 [done]，自然结束；attempt2: 带 [done]
    scenarios = [
        [
            _openai_sse_chunk("Hello "),
            _openai_sse_chunk("world"),
        ],
        [
            _openai_sse_chunk("continued[done]"),
        ],
    ]
    calls = {"count": 0}

    class FakeUpstreamClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

        async def stream_request(self, method, url, headers, content=None, json=None):
            idx = calls["count"]
            calls["count"] += 1
            for c in scenarios[idx]:
                yield c

    monkeypatch.setattr(streaming_mod, "UpstreamClient", FakeUpstreamClient)

    p = StreamingAntiTruncationProcessor(
        protocol=ProtocolType.OPENAI,
        request_id="rid",
        upstream_base_url="http://upstream",
        path="/v1/chat/completions",
        headers={},
        request_body={"stream": True, "model": "gpt-4"},
    )

    out = b"".join([c async for c in p.process_stream()])
    assert calls["count"] == 2
    assert b"[done]" not in out  # marker 被剥离，不应透传给客户端


@pytest.mark.asyncio
async def test_stop_consuming_upstream_after_done_marker(monkeypatch):
    from app.streaming import StreamingAntiTruncationProcessor, ProtocolType
    import app.streaming as streaming_mod

    monkeypatch.setattr(streaming_mod.config, "ANTI_TRUNCATION_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(streaming_mod.config, "ANTI_TRUNCATION_DONE_MARKER", "[done]")

    consumed = {"chunks": 0}

    class FakeUpstreamClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

        async def stream_request(self, method, url, headers, content=None, json=None):
            # 先给出 done marker，再给一个“如果继续消费就会被读到”的 chunk
            for c in [
                _openai_sse_chunk("ok[done]"),
                _openai_sse_chunk("SHOULD_NOT_BE_FORWARDED"),
            ]:
                consumed["chunks"] += 1
                yield c

    monkeypatch.setattr(streaming_mod, "UpstreamClient", FakeUpstreamClient)

    p = StreamingAntiTruncationProcessor(
        protocol=ProtocolType.OPENAI,
        request_id="rid",
        upstream_base_url="http://upstream",
        path="/v1/chat/completions",
        headers={},
        request_body={"stream": True, "model": "gpt-4"},
    )

    out = b"".join([c async for c in p.process_stream()])
    assert b"SHOULD_NOT_BE_FORWARDED" not in out
    # 关键：检测到 done marker 后就 break，不应继续消费第二个 chunk
    assert consumed["chunks"] == 1


@pytest.mark.asyncio
async def test_retry_on_upstream_429(monkeypatch):
    from app.streaming import StreamingAntiTruncationProcessor, ProtocolType
    import app.streaming as streaming_mod

    monkeypatch.setattr(streaming_mod.config, "ANTI_TRUNCATION_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(streaming_mod.config, "ANTI_TRUNCATION_DONE_MARKER", "[done]")

    calls = {"count": 0}

    req = httpx.Request("POST", "http://upstream/v1/chat/completions")
    resp_429 = httpx.Response(429, request=req, content=b'{"error":"rate_limited"}')
    err_429 = httpx.HTTPStatusError("upstream 429", request=req, response=resp_429)

    class FakeUpstreamClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

        async def stream_request(self, method, url, headers, content=None, json=None):
            calls["count"] += 1
            if calls["count"] == 1:
                raise err_429
            yield _openai_sse_chunk("after_retry[done]")

    monkeypatch.setattr(streaming_mod, "UpstreamClient", FakeUpstreamClient)

    p = StreamingAntiTruncationProcessor(
        protocol=ProtocolType.OPENAI,
        request_id="rid",
        upstream_base_url="http://upstream",
        path="/v1/chat/completions",
        headers={},
        request_body={"stream": True, "model": "gpt-4"},
    )

    out = b"".join([c async for c in p.process_stream()])
    assert calls["count"] == 2
    assert b"upstream_error" not in out
    assert b"[done]" not in out


@pytest.mark.asyncio
async def test_retry_on_upstream_idle_timeout_and_emit_keepalive(monkeypatch):
    import asyncio
    from app.streaming import StreamingAntiTruncationProcessor, ProtocolType
    import app.streaming as streaming_mod

    monkeypatch.setattr(streaming_mod.config, "ANTI_TRUNCATION_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(streaming_mod.config, "ANTI_TRUNCATION_DONE_MARKER", "[done]")
    monkeypatch.setattr(streaming_mod.config, "ANTI_TRUNCATION_KEEPALIVE_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(streaming_mod.config, "ANTI_TRUNCATION_UPSTREAM_IDLE_TIMEOUT_SECONDS", 0.03)

    calls = {"count": 0}

    class FakeUpstreamClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

        async def stream_request(self, method, url, headers, content=None, json=None):
            calls["count"] += 1
            # 第一次：先吐出一个 chunk（表示已开始输出），然后卡住不再吐数据（触发 idle timeout -> retry）
            if calls["count"] == 1:
                yield _openai_sse_chunk("partial")
                while True:
                    await asyncio.sleep(1)
            # 第二次：正常返回
            yield _openai_sse_chunk("after_idle_retry[done]")

    monkeypatch.setattr(streaming_mod, "UpstreamClient", FakeUpstreamClient)

    p = StreamingAntiTruncationProcessor(
        protocol=ProtocolType.OPENAI,
        request_id="rid",
        upstream_base_url="http://upstream",
        path="/v1/chat/completions",
        headers={},
        request_body={"stream": True, "model": "gpt-4"},
    )

    chunks = [c async for c in p.process_stream()]
    out = b"".join(chunks)
    assert calls["count"] == 2
    assert b": keepalive\n\n" in out  # 期间应发过 keepalive
    assert b"[done]" not in out


@pytest.mark.asyncio
async def test_retry_on_upstream_request_error(monkeypatch):
    from app.streaming import StreamingAntiTruncationProcessor, ProtocolType
    import app.streaming as streaming_mod

    monkeypatch.setattr(streaming_mod.config, "ANTI_TRUNCATION_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(streaming_mod.config, "ANTI_TRUNCATION_DONE_MARKER", "[done]")

    calls = {"count": 0}
    req = httpx.Request("POST", "http://upstream/v1/chat/completions")
    err = httpx.ReadError("tcp disconnected", request=req)

    class FakeUpstreamClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

        async def stream_request(self, method, url, headers, content=None, json=None):
            calls["count"] += 1
            if calls["count"] == 1:
                raise err
            yield _openai_sse_chunk("after_network_retry[done]")

    monkeypatch.setattr(streaming_mod, "UpstreamClient", FakeUpstreamClient)

    p = StreamingAntiTruncationProcessor(
        protocol=ProtocolType.OPENAI,
        request_id="rid",
        upstream_base_url="http://upstream",
        path="/v1/chat/completions",
        headers={},
        request_body={"stream": True, "model": "gpt-4"},
    )

    out = b"".join([c async for c in p.process_stream()])
    assert calls["count"] == 2
    assert b"upstream_request_error" not in out
    assert b"[done]" not in out


@pytest.mark.asyncio
async def test_slow_first_chunk_should_wait_and_not_retry(monkeypatch):
    import asyncio
    from app.streaming import StreamingAntiTruncationProcessor, ProtocolType
    import app.streaming as streaming_mod

    monkeypatch.setattr(streaming_mod.config, "ANTI_TRUNCATION_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(streaming_mod.config, "ANTI_TRUNCATION_DONE_MARKER", "[done]")
    monkeypatch.setattr(streaming_mod.config, "ANTI_TRUNCATION_KEEPALIVE_INTERVAL_SECONDS", 0.01)
    # 即使 idle timeout 很小，也不应该在“首个 chunk 未到来之前”触发重试
    monkeypatch.setattr(streaming_mod.config, "ANTI_TRUNCATION_UPSTREAM_IDLE_TIMEOUT_SECONDS", 0.02)

    calls = {"count": 0}

    class FakeUpstreamClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

        async def stream_request(self, method, url, headers, content=None, json=None):
            calls["count"] += 1
            # 首包延迟：大于 keepalive 间隔
            await asyncio.sleep(0.03)
            yield _openai_sse_chunk("hello[done]")

    monkeypatch.setattr(streaming_mod, "UpstreamClient", FakeUpstreamClient)

    p = StreamingAntiTruncationProcessor(
        protocol=ProtocolType.OPENAI,
        request_id="rid",
        upstream_base_url="http://upstream",
        path="/v1/chat/completions",
        headers={},
        request_body={"stream": True, "model": "gpt-4"},
    )

    out = b"".join([c async for c in p.process_stream()])
    assert calls["count"] == 1  # 不应因为“慢”就立刻重试
    assert b": keepalive\n\n" in out
    assert b"[done]" not in out

