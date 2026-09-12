"""Interactive CLI entry point."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.config.settings import load_settings
from app.bootstrap import Application
from app.runtime.task_manager import TaskManager
from app.safety.intervention import ConsoleInterventionGate
from app.runtime.guided_workflow import GuidedBrowserWorkflow, WorkflowStore


CLI_ADVISORY_NOTICE = (
    "Ordinary CLI results are advisory. Supported guided browser tasks can execute only "
    "bounded semantic steps and require confirmation before external actions."
)


def format_cli_result(result: str) -> str:
    """Label provider text so it cannot be mistaken for an executed action."""
    return f"Provider response (advisory; no external action was executed):\n\n{result}"


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    root = Path(__file__).resolve().parents[1]
    settings = load_settings()
    application = Application(root, settings, intervention=ConsoleInterventionGate())
    print(f"Brainless Agent starting...\n\nBrowser: READY\nChatGPT: READY\n\n{CLI_ADVISORY_NOTICE}\n")
    try:
        objective = input("Enter task:\n> ").strip()
        if objective:
            if GuidedBrowserWorkflow.supports(objective):
                provider = application.providers.get(application.providers.names[0])
                workflow = GuidedBrowserWorkflow(provider, application.browser,
                    WorkflowStore(root / "data/guided-workflows.json"))
                print("\n" + await workflow.run(objective))
            else:
                task = TaskManager(application.providers.names).create(objective)
                print("\n" + format_cli_result(await application.runtime.run(task)))
    finally:
        await application.close()


if __name__ == "__main__":
    asyncio.run(main())
