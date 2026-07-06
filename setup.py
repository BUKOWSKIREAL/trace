from setuptools import setup
from py2app.build_app import py2app as py2app_command


class TracePy2AppCommand(py2app_command):
    def finalize_options(self):
        # This project keeps runtime dependencies in pyproject.toml and uv.lock.
        # py2app 0.28 rejects setuptools' PEP 621 install_requires metadata,
        # so the app bundle command must clear it before py2app validates opts.
        self.distribution.install_requires = None
        super().finalize_options()


setup(
    name="Trace",
    version="0.1.0",
    install_requires=[],
    app=["code/main.py"],
    data_files=[
        ("code/menubar", ["code/menubar/icon.png"]),
    ],
    cmdclass={"py2app": TracePy2AppCommand},
    options={
        "py2app": {
            "argv_emulation": False,
            "iconfile": "assets/app_icon.icns",
            "packages": [
                "core",
                "daemon",
                "hooks",
                "menubar",
                "mcp",
                "models",
                "utils",
                "views",
                "watchdog",
                "psutil",
                "rumps",
                "ttkbootstrap",
                "pyfiglet",
            ],
            "includes": [
                "PIL",
                "docx",
                "fitz",
                "openpyxl",
                "pptx",
                "sqlite3",
                "tkinter",
            ],
            "frameworks": [
                "/opt/anaconda3/lib/libffi.8.dylib",
                "/opt/anaconda3/lib/libsqlite3.dylib",
                "/opt/anaconda3/lib/libtcl8.6.dylib",
                "/opt/anaconda3/lib/libtk8.6.dylib",
            ],
            "plist": {
                "CFBundleName": "Trace",
                "CFBundleDisplayName": "Trace",
                "CFBundleIdentifier": "cn.edu.shu.trace",
                "CFBundleShortVersionString": "0.1.0",
                "LSUIElement": True,
            },
        }
    },
)
