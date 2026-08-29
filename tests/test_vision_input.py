"""G-3 多模态视觉输入回归：消息层协议适配 + 会话层内联图片附件。

被测实现：
- ``llm/anthropic.py`` / ``llm/openai_compat.py``：统一内部表示（content
  为 text/image 部件列表）→ 各协议分格式；连续 user 消息合并；
- ``llm/fallback.py``：多部件消息原样透传；
- ``web/chat.py``：``_prepare_attachments``（内联 base64 图片校验/落盘/
  大小与数量限制 / RA_VISION_DISABLED 开关）、``_content_for_llm``
  （图片附件 → 多部件 content）、``_image_parts_from_entry``。

测试口径：全部为纯函数直测（沙箱 TestClient websocket_connect 会挂起，
历史教训——不做 WS 冒烟，把逻辑抽成纯函数）。
"""

import base64
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
import research_assistant.web.chat as chat_mod  # noqa: E402
from research_assistant.llm.anthropic import _build_anthropic_messages  # noqa: E402
from research_assistant.llm.base import LLMClient, LLMResponse  # noqa: E402
from research_assistant.llm.fallback import FallbackLLMClient  # noqa: E402
from research_assistant.llm.openai_compat import _build_openai_messages  # noqa: E402

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-png-payload"
PNG_B64 = base64.b64encode(PNG_BYTES).decode("ascii")


def _img_item(name: str = "a.png", data: str = PNG_B64,
              mime: str = "image/png") -> dict:
    return {"name": name, "mime_type": mime, "data_base64": data}


# ---------------------------------------------------------------------------
# 消息层：两种协议的分格式
# ---------------------------------------------------------------------------


class TestAnthropicMultipart:
    def test_image_part_shape(self):
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": "看图"},
            {"type": "image", "media_type": "image/png", "data": "QUJD"},
        ]}]
        out = _build_anthropic_messages(msgs)
        assert out[0]["role"] == "user"
        blocks = out[0]["content"]
        assert blocks[0] == {"type": "text", "text": "看图"}
        assert blocks[1] == {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"},
        }

    def test_plain_text_content_unchanged(self):
        msgs = [{"role": "user", "content": "纯文本"}]
        assert _build_anthropic_messages(msgs)[0]["content"] == "纯文本"

    def test_consecutive_user_messages_merged(self):
        # 会话层把「图片 + 文本 prompt」拆成两条 user 消息传入
        msgs = [
            {"role": "user", "content": [
                {"type": "image", "media_type": "image/png", "data": "QUJD"},
            ]},
            {"role": "user", "content": "图里有什么？"},
        ]
        out = _build_anthropic_messages(msgs)
        assert len(out) == 1
        assert out[0]["role"] == "user"
        assert out[0]["content"][0]["type"] == "image"
        assert out[0]["content"][1] == {"type": "text", "text": "图里有什么？"}


class TestOpenAIMultipart:
    def test_image_url_part_shape(self):
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": "看图"},
            {"type": "image", "media_type": "image/jpeg", "data": "QUJD"},
        ]}]
        out = _build_openai_messages(msgs)
        parts = out[0]["content"]
        assert parts[0] == {"type": "text", "text": "看图"}
        assert parts[1] == {
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64,QUJD"},
        }

    def test_consecutive_user_messages_merged(self):
        msgs = [
            {"role": "user", "content": [
                {"type": "image", "media_type": "image/png", "data": "QUJD"},
            ]},
            {"role": "user", "content": "图里有什么？"},
        ]
        out = _build_openai_messages(msgs)
        assert len(out) == 1
        parts = out[0]["content"]
        assert parts[0]["type"] == "image_url"
        assert parts[1] == {"type": "text", "text": "图里有什么？"}

    def test_tool_and_assistant_roles_untouched(self):
        msgs = [
            {"role": "assistant", "tool_calls": [
                {"id": "t1", "name": "read_file", "arguments": {"path": "x"}},
            ]},
            {"role": "tool", "tool_call_id": "t1", "content": "ok"},
        ]
        out = _build_openai_messages(msgs)
        assert out[0]["tool_calls"][0]["function"]["name"] == "read_file"
        assert out[1]["content"] == "ok"


class TestFallbackPassthrough:
    async def test_multipart_messages_pass_through_unchanged(self):
        captured: list[list[dict]] = []

        class StubClient(LLMClient):
            model = "stub"

            def __init__(self) -> None:
                super().__init__()

            async def chat(self, messages, **kw) -> LLMResponse:  # noqa: D102
                captured.append(json.loads(json.dumps(messages)))  # 深拷贝快照
                return LLMResponse(content="ok", stop_reason="end_turn")

            async def close(self) -> None:  # noqa: D102
                pass

        payload = [{"role": "user", "content": [
            {"type": "text", "text": "看图"},
            {"type": "image", "media_type": "image/png", "data": "QUJD"},
        ]}]
        client = FallbackLLMClient([StubClient()])
        await client.chat(payload)
        assert captured[0] == payload  # fallback 链不感知多模态，透传即可


# ---------------------------------------------------------------------------
# 会话层：内联图片附件
# ---------------------------------------------------------------------------


class TestPrepareAttachments:
    def test_inline_image_saved_to_uploads(self, tmp_path):
        meta, err = chat_mod._prepare_attachments(
            tmp_path, "sid-vision", [_img_item()],
        )
        assert err == ""
        assert meta[0]["mime_type"] == "image/png"
        saved = Path(meta[0]["path"])
        assert saved.is_file()
        assert saved.read_bytes() == PNG_BYTES
        # 落盘位置：本会话产物目录的 uploads/ 子目录
        assert saved.parent.name == "uploads"
        assert "sid-vision" in saved.parent.parent.name

    def test_invalid_base64_rejected(self, tmp_path):
        meta, err = chat_mod._prepare_attachments(
            tmp_path, "sid", [_img_item(data="!!!not-base64!!!")],
        )
        assert meta == []
        assert "无法解码" in err

    def test_oversize_image_rejected(self, tmp_path, monkeypatch):
        big = base64.b64encode(b"x" * (chat_mod.VISION_IMAGE_MAX_BYTES + 1)).decode()
        meta, err = chat_mod._prepare_attachments(tmp_path, "sid", [_img_item(data=big)])
        assert meta == []
        assert "大小上限" in err

    def test_image_count_limit(self, tmp_path):
        items = [_img_item(name=f"i{i}.png") for i in range(chat_mod.VISION_MAX_IMAGES + 1)]
        meta, err = chat_mod._prepare_attachments(tmp_path, "sid", items)
        assert meta == []
        assert "图片数量超过上限" in err

    def test_unsupported_mime_rejected(self, tmp_path):
        meta, err = chat_mod._prepare_attachments(
            tmp_path, "sid", [_img_item(mime="image/bmp")],
        )
        assert meta == []
        assert "不支持的图片类型" in err

    def test_vision_disabled_switch(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RA_VISION_DISABLED", "1")
        meta, err = chat_mod._prepare_attachments(tmp_path, "sid", [_img_item()])
        assert meta == []
        assert "禁用视觉" in err

    def test_path_ref_image_gets_mime(self, tmp_path):
        # 既有路径引用形态：图片扩展名自动补 mime_type（与内联同口注入）
        uploads = tmp_path / "outputs" / "sid" / "uploads"
        uploads.mkdir(parents=True)
        f = uploads / "chart.png"
        f.write_bytes(PNG_BYTES)
        meta, err = chat_mod._prepare_attachments(
            tmp_path, "sid", [{"name": "chart.png", "path": str(f)}],
        )
        assert err == ""
        assert meta[0]["mime_type"] == "image/png"

    def test_missing_payload_rejected(self, tmp_path):
        meta, err = chat_mod._prepare_attachments(tmp_path, "sid", [{"name": "x"}])
        assert meta == []
        assert "缺少" in err


class TestContentForLLM:
    def test_image_entry_becomes_multipart(self, tmp_path):
        f = tmp_path / "pic.png"
        f.write_bytes(PNG_BYTES)
        entry = {"role": "user", "content": "看这张图",
                 "attachments": [{"name": "pic.png", "path": str(f),
                                  "mime_type": "image/png"}]}
        flat = chat_mod._content_for_llm(entry)
        assert isinstance(flat["content"], list)
        text_part, image_part = flat["content"]
        assert text_part == {"type": "text", "text": "看这张图"}
        assert image_part["type"] == "image"
        assert image_part["media_type"] == "image/png"
        assert base64.b64decode(image_part["data"]) == PNG_BYTES

    def test_text_only_entry_stays_string(self):
        entry = {"role": "user", "content": "你好",
                 "attachments": [{"name": "data.csv", "path": "/tmp/data.csv"}]}
        flat = chat_mod._content_for_llm(entry)
        assert isinstance(flat["content"], str)
        assert "data.csv" in flat["content"]

    def test_image_parts_skip_missing_file(self, tmp_path):
        entry = {"role": "user", "content": "看图",
                 "attachments": [{"name": "gone.png", "path": str(tmp_path / "gone.png"),
                                  "mime_type": "image/png"}]}
        assert chat_mod._image_parts_from_entry(entry) == []
        # 缺文件不产生 image 部件，content 退回纯文本（不阻塞回合）
        flat = chat_mod._content_for_llm(entry)
        assert isinstance(flat["content"], str)
