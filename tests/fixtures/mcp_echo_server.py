"""极小参考 MCP server：用于 G-2 客户端测试，不依赖网络或 npx。

协议：stdin/stdout 逐行 JSON-RPC 2.0（MCP 规范 2024-11-05 基础子集）。
实现 initialize / notifications/initialized（通知，不回包）/ tools/list /
tools/call，提供 echo 工具。

测试可通过环境变量控制行为：
- MCP_FORCE_PROTOCOL_VERSION: 强制返回不匹配的协议版本（客户端应报错）。
"""

import json
import os
import sys

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "echo",
        "description": "回显输入文本",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要回显的文本"},
            },
            "required": ["text"],
        },
    }
]


def handle_message(msg: dict) -> dict | None:
    """处理一条 JSON-RPC 消息；通知返回 None（无响应）。"""
    if "id" not in msg:
        # 通知（如 notifications/initialized）：按规范不回包
        return None
    rid = msg["id"]
    method = msg.get("method")
    if method == "initialize":
        forced = os.environ.get("MCP_FORCE_PROTOCOL_VERSION")
        server_version = forced if forced else PROTOCOL_VERSION
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "protocolVersion": server_version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mcp-echo-server", "version": "0.1.0"},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params") or {}
        if params.get("name") != "echo":
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32602, "message": f"Unknown tool: {params.get('name')}"},
            }
        arguments = params.get("arguments") or {}
        text = str(arguments.get("text", ""))
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "content": [{"type": "text", "text": f"echo: {text}"}],
                "isError": False,
            },
        }
    # 未知方法：返回标准 JSON-RPC 错误
    return {
        "jsonrpc": "2.0",
        "id": rid,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_message(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
