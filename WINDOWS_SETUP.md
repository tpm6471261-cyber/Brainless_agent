# Windows setup

Run on Windows 10/11 with Python 3.11+ and install `requirements.txt`. The core filesystem/resource event
detectors require no extra package. Call `WindowsCapabilityReport.detect()` at startup to see available,
partial, and unavailable integrations. Optional native mouse, keyboard, UI Automation, device, audio,
notification and session adapters are not bundled and remain disabled; the rest of the application continues.

`pyautogui`, `pyperclip`, and `pygetwindow` provide control, clipboard, display and visible-window adapters;
Playwright provides the existing browser adapter. Normal user-session access is sufficient for those APIs.
Controlling an elevated application may require running Brainless Agent elevated, but elevation is never
requested or bypassed automatically. Power shutdown/hibernate actions are intentionally not registered yet.

Run tests with `pytest -q`. Start the CLI with `python run.py`, the Tk UI with `python run_gui.py`, or the local
authenticated dashboard with `BRAINLESS_DASHBOARD_TOKEN=<16+ characters> python run_dashboard.py`.
