# Windows setup

Run on Windows 10/11 with Python 3.11+ and install `requirements.txt`. The core filesystem/resource event
detectors require no extra package. Call `WindowsCapabilityReport.detect()` at startup to see available,
partial, and unavailable integrations. Optional native mouse, keyboard, UI Automation, device, audio,
notification and session adapters are not bundled and remain disabled; the rest of the application continues.
