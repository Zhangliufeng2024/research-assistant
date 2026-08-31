# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('D:/vscode files/research-assistant-v3/research_assistant/web/static', 'research_assistant/web/static'), ('C:/Users/ZHANGL~1/AppData/Local/Temp/ra_claude_clean_jcrdjoxk', '.claude')]
binaries = []
hiddenimports = ['uvicorn', 'uvicorn.lifespan', 'uvicorn.lifespan.on', 'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.http.h11_impl', 'uvicorn.protocols.http.httptools_impl', 'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto', 'uvicorn.protocols.websockets.wsproto_impl', 'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.loops.asyncio', 'fastapi', 'starlette', 'starlette.routing', 'starlette.responses', 'starlette.staticfiles', 'starlette.websockets', 'httpx', 'httpx._transports', 'httpx._transports.default', 'httpcore', 'httpcore._async', 'httpcore._backends', 'httpcore._backends.auto', 'httpcore._backends.anyio', 'h11', 'anyio', 'anyio._backends', 'anyio._backends._asyncio', 'sniffio', 'dotenv', 'docx', 'docx.opc', 'docx.opc.constants', 'research_assistant', 'research_assistant.web', 'research_assistant.web.app', 'research_assistant.web.routes', 'research_assistant.web.ws', 'research_assistant.web.prompt', 'research_assistant.api', 'research_assistant.agent', 'research_assistant.cli', 'research_assistant.config', 'research_assistant.core', 'research_assistant.constants', 'research_assistant.models', 'research_assistant.docgen', 'research_assistant.orchestrator', 'research_assistant.retry', 'research_assistant.display', 'research_assistant.steer', 'research_assistant.utils', 'research_assistant.runtime', 'research_assistant.runtime.platform_store', 'research_assistant.runtime.task_hub', 'research_assistant.runtime.scheduler', 'research_assistant.context', 'research_assistant.context.sources', 'research_assistant.artifacts', 'research_assistant.artifacts.versioning', 'research_assistant.workflows', 'research_assistant.workflows.registry', 'research_assistant.workflows.runner', 'research_assistant.llm', 'research_assistant.llm.base', 'research_assistant.llm.anthropic', 'research_assistant.llm.openai_compat', 'research_assistant.llm.factory', 'research_assistant.tools', 'research_assistant.tools.registry', 'research_assistant.tools.file_ops', 'research_assistant.tools.bash', 'research_assistant.tools.python_exec', 'research_assistant.launcher', 'research_assistant.launcher_desktop', 'research_assistant.desktop', 'webview', 'webview.platforms.winforms', 'webview.platforms.edgechromium', 'clr_loader', 'clr_loader.netfx', 'pythonnet', 'clr', 'numpy', 'pandas', 'matplotlib', 'PIL']
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('clr_loader')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pythonnet')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['D:/vscode files/research-assistant-v3/research_assistant/launcher_desktop.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['scipy', 'cv2', 'torch', 'tensorflow', 'pytest', 'IPython', 'notebook', 'jupyter', 'llvmlite', 'numba', 'shap', 'pymupdf', 'fitz'],
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
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['D:/vscode files/research-assistant-v3/packaging/app_icon.ico'],
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
