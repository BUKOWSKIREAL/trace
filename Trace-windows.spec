# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path


block_cipher = None
ROOT = Path(SPECPATH).resolve()
CODE = ROOT / "code"
ELECTRON_EXE_NAME = "Trace Console.exe"
ELECTRON_WIN = Path(
    os.environ.get(
        "TRACE_ELECTRON_WIN_DIR",
        str(ROOT / "electron_app" / "dist" / "win-unpacked"),
    )
).resolve()


datas = [
    (str(CODE / "menubar" / "icon.png"), "menubar"),
]
if ELECTRON_WIN.exists():
    electron_exe = ELECTRON_WIN / ELECTRON_EXE_NAME
    if not electron_exe.exists():
        raise SystemExit(f"missing Electron console executable: {electron_exe}")
    datas.append((str(ELECTRON_WIN), "electron"))

hiddenimports = [
    "core.electron_diff_bridge",
    "core.electron_restore_bridge",
    "core.electron_reassign_bridge",
    "core.electron_revert_agent_bridge",
    "core.electron_init_bridge",
    "core.handlers.binary_handler",
    "core.handlers.docx_handler",
    "core.handlers.image_handler",
    "core.handlers.pdf_handler",
    "core.handlers.pptx_handler",
    "core.handlers.text_handler",
    "core.handlers.xlsx_handler",
    "daemon.activity_recorder",
    "daemon.attribution_resolver",
    "daemon.config_runtime",
    "daemon.trace_activity",
    "daemon.detectors.cli_detector",
    "daemon.detectors.gui_detector",
    "daemon.detectors.script_detector",
    "daemon.detectors.transcript_detector",
    "hooks.trace_codex_hook",
    "mcp.trace_server",
    "menubar.tray_pystray",
    "PIL.Image",
    "PIL.ImageDraw",
    "pystray",
]


common_kwargs = {
    "pathex": [str(CODE)],
    "binaries": [],
    "hiddenimports": hiddenimports,
    "hookspath": [],
    "hooksconfig": {},
    "runtime_hooks": [],
    "excludes": ["rumps", "AppKit"],
    "win_no_prefer_redirects": False,
    "win_private_assemblies": False,
    "cipher": block_cipher,
    "noarchive": False,
}


trace_analysis = Analysis([str(CODE / "main.py")], datas=datas, **common_kwargs)
trace_pyz = PYZ(trace_analysis.pure, trace_analysis.zipped_data, cipher=block_cipher)
trace_exe = EXE(
    trace_pyz,
    trace_analysis.scripts,
    [],
    exclude_binaries=True,
    name="Trace",
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
)


bridge_analysis = Analysis([str(CODE / "electron_bridge.py")], datas=[], **common_kwargs)
bridge_pyz = PYZ(bridge_analysis.pure, bridge_analysis.zipped_data, cipher=block_cipher)
bridge_exe = EXE(
    bridge_pyz,
    bridge_analysis.scripts,
    [],
    exclude_binaries=True,
    name="TraceBridge",
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
)


coll = COLLECT(
    trace_exe,
    bridge_exe,
    trace_analysis.binaries,
    trace_analysis.datas,
    bridge_analysis.binaries,
    bridge_analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Trace",
)
