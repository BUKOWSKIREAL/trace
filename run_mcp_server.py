#!/usr/bin/env python
"""
Wrapper script to run the Trace MCP server.
This ensures the correct PYTHONPATH is set regardless of how it's invoked.
"""
import sys
from pathlib import Path

# Add the code directory to Python path
CODE_DIR = Path(__file__).parent / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

# Now import and run the server
from mcp.trace_server import main

if __name__ == "__main__":
    main()
