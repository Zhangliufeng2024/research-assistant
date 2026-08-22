# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:\\vscode files\\research-assistant-v3\\research_assistant\\launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('D:\\vscode files\\research-assistant-v3\\research_assistant\\web\\static', 'research_assistant/web/static'), ('D:\\vscode files\\research-assistant-v3\\build\\_claude_clean', '.claude')],
    hiddenimports=['uvicorn', 'uvicorn.lifespan', 'uvicorn.lifespan.on', 'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.http.h11_impl', 'uvicorn.protocols.http.httptools_impl', 'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto', 'uvicorn.protocols.websockets.wsproto_impl', 'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.loops.asyncio', 'fastapi', 'starlette', 'starlette.routing', 'starlette.responses', 'starlette.staticfiles', 'starlette.websockets', 'httpx', 'httpx._transports', 'httpx._transports.default', 'httpcore', 'httpcore._async', 'httpcore._backends', 'httpcore._backends.auto', 'httpcore._backends.anyio', 'h11', 'anyio', 'anyio._backends', 'anyio._backends._asyncio', 'sniffio', 'dotenv', 'docx', 'docx.opc', 'docx.opc.constants', 'fitz', 'research_assistant', 'research_assistant.web', 'research_assistant.web.app', 'research_assistant.web.routes', 'research_assistant.web.ws', 'research_assistant.web.chat', 'research_assistant.web.workspace', 'research_assistant.desktop', 'webview', 'tkinter', 'research_assistant.api', 'research_assistant.agent', 'research_assistant.cli', 'research_assistant.config', 'research_assistant.core', 'research_assistant.constants', 'research_assistant.models', 'research_assistant.docgen', 'research_assistant.orchestrator', 'research_assistant.retry', 'research_assistant.display', 'research_assistant.steer', 'research_assistant.utils', 'research_assistant.llm', 'research_assistant.llm.base', 'research_assistant.llm.anthropic', 'research_assistant.llm.openai_compat', 'research_assistant.llm.factory', 'research_assistant.tools', 'research_assistant.tools.registry', 'research_assistant.tools.file_ops', 'research_assistant.tools.bash', 'research_assistant.tools.python_exec'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'pandas', 'scipy', 'PIL', 'cv2', 'torch', 'tensorflow', 'pytest', 'IPython', 'notebook', 'jupyter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ResearchAssistant',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='NONE',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ResearchAssistant',
)
