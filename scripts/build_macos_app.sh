#!/usr/bin/env bash
# Build Trace as a complete macOS .app:
#   1. Build the Electron Console for the current Mac architecture.
#   2. Build the Python menu-bar app with py2app.
#   3. Embed the Electron Console.app inside Trace.app/Contents/Resources.
#   4. Re-seal the outer app bundle after embedding nested code.
#   5. Create a DMG when create-dmg is available.

set -euo pipefail

cd "$(dirname "$0")/.."

APP_NAME="Trace"
APP_BUNDLE="dist/${APP_NAME}.app"
DMG_PATH="dist/${APP_NAME}-macOS.dmg"
ELECTRON_APP_NAME="Trace Console"
ELECTRON_RESOURCE_DIR="${APP_BUNDLE}/Contents/Resources/electron"

echo "=== Trace macOS packaging ==="
echo "project: $(pwd)"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv is required. Install it first, then rerun this script."
    exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
    echo "ERROR: npm is required to build the bundled Electron console."
    exit 1
fi

case "$(uname -m)" in
    arm64)
        ELECTRON_ARCH="arm64"
        ELECTRON_OUT_DIR="mac-arm64"
        ;;
    x86_64)
        ELECTRON_ARCH="x64"
        ELECTRON_OUT_DIR="mac"
        ;;
    *)
        echo "ERROR: unsupported macOS architecture: $(uname -m)"
        exit 1
        ;;
esac

echo "[1/7] Sync Python environment"
uv sync

echo "[2/7] Build Electron console (${ELECTRON_ARCH})"
(cd electron_app && npm install && npm run build:renderer && npx electron-builder --mac "--${ELECTRON_ARCH}")
ELECTRON_BUNDLE="electron_app/dist/${ELECTRON_OUT_DIR}/${ELECTRON_APP_NAME}.app"
if [[ ! -x "${ELECTRON_BUNDLE}/Contents/MacOS/${ELECTRON_APP_NAME}" ]]; then
    echo "ERROR: Electron build did not create expected app: ${ELECTRON_BUNDLE}"
    exit 1
fi

echo "[3/7] Build ${APP_NAME}.app with py2app"
rm -rf build "$APP_BUNDLE" "$DMG_PATH"
mkdir -p dist

if uv run python setup.py py2app; then
    if [[ -d "$APP_BUNDLE" ]]; then
        echo "    built: $APP_BUNDLE"
    else
        echo "    py2app exited successfully but did not create $APP_BUNDLE"
    fi
else
    echo "    py2app build failed; falling back to install.sh"
fi

if [[ -d "$APP_BUNDLE" ]]; then
    echo "[4/7] Smoke-check app bundle exists"
    test -x "$APP_BUNDLE/Contents/MacOS/${APP_NAME}" || \
        test -x "$APP_BUNDLE/Contents/MacOS/main"

    echo "[5/7] Embed Electron console into ${APP_NAME}.app"
    rm -rf "$ELECTRON_RESOURCE_DIR"
    mkdir -p "$ELECTRON_RESOURCE_DIR"
    cp -R "$ELECTRON_BUNDLE" "$ELECTRON_RESOURCE_DIR/"
    test -x "${ELECTRON_RESOURCE_DIR}/${ELECTRON_APP_NAME}.app/Contents/MacOS/${ELECTRON_APP_NAME}"
    echo "    embedded: ${ELECTRON_RESOURCE_DIR}/${ELECTRON_APP_NAME}.app"
    echo "    codesign embedded Electron console"
    codesign --force --deep --sign - "${ELECTRON_RESOURCE_DIR}/${ELECTRON_APP_NAME}.app"

    echo "    fix bundled Python sqlite linkage"
    SQLITE_EXTENSION="$(find "$APP_BUNDLE/Contents/Resources/lib" -path "*/lib-dynload/_sqlite3.so" -print -quit)"
    if [[ -n "$SQLITE_EXTENSION" && -f "$SQLITE_EXTENSION" ]]; then
        install_name_tool \
            -change "@rpath/libsqlite3.dylib" \
            "@loader_path/../../../../Frameworks/libsqlite3.dylib" \
            "$SQLITE_EXTENSION"
        otool -L "$SQLITE_EXTENSION" | grep -q "@loader_path/../../../../Frameworks/libsqlite3.dylib"
    else
        echo "ERROR: bundled sqlite extension not found: $SQLITE_EXTENSION"
        exit 1
    fi

    echo "[6/7] Re-seal ${APP_NAME}.app after embedding nested Electron app"
    echo "    codesign embedded frameworks and python extensions"
    find "$APP_BUNDLE/Contents/Frameworks" -name '*.dylib' -print0 | while IFS= read -r -d '' lib; do
        codesign --force --sign - "$lib"
    done
    find "$APP_BUNDLE/Contents/Resources/lib" -name '*.so' -print0 2>/dev/null | while IFS= read -r -d '' so; do
        codesign --force --sign - "$so" 2>/dev/null || true
    done
    xattr -cr "$APP_BUNDLE" 2>/dev/null || true
    codesign --force --deep --sign - "$APP_BUNDLE"
    codesign --verify --deep --strict --verbose=2 "$APP_BUNDLE"

    echo "[7/7] Create DMG when create-dmg is installed"
    if command -v create-dmg >/dev/null 2>&1; then
        rm -f "$DMG_PATH"
        if create-dmg \
            --volname "$APP_NAME" \
            --window-size 520 320 \
            --app-drop-link 360 160 \
            "$DMG_PATH" \
            "$APP_BUNDLE"; then
            echo "    dmg: $DMG_PATH"
            exit 0
        fi
        echo "    create-dmg failed; falling back to install.sh"
    else
        echo "    create-dmg not found; falling back to install.sh"
    fi
else
    echo "[4/7] .app unavailable"
    echo "[5/7] Electron embed skipped"
    echo "[6/7] Re-seal skipped"
    echo "[7/7] DMG skipped"
fi

chmod +x install.sh
echo
echo "Fallback ready: ./install.sh"
echo "Run it to create dist/Trace.command source launcher."
