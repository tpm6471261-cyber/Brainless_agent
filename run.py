import asyncio
import sys
from pathlib import Path

from app.agents.cli import run_agent_cli
from app.main import main as cli_main
from run_dashboard import main as dashboard_main

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "agent":
        run_agent_cli(sys.argv[2:], Path(__file__).resolve().parent / "data/memory.db")
    elif len(sys.argv) > 1 and sys.argv[1] == "cli":
        asyncio.run(cli_main())
    else:
        dashboard_main()
