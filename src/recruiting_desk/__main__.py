"""
python -m recruiting_desk          start the app and open the browser
python -m recruiting_desk --mcp    run as an MCP server on stdio (Claude Desktop, etc.)
"""

import sys


def run():
    if "--mcp" in sys.argv:
        sys.argv.remove("--mcp")
        from .mcp_server import main as mcp_main
        mcp_main()
    else:
        from .app import main
        main()


if __name__ == "__main__":
    run()
