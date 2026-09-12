"""Canonical desktop capability names and safe observation mapping."""
from __future__ import annotations

PERMISSIONS=frozenset({
    "mouse.observe","mouse.control","keyboard.observe","keyboard.control",
    "screen.observe","screen.capture","clipboard.read","clipboard.write",
    "filesystem.read","filesystem.write","filesystem.delete","process.observe",
    "process.control","window.observe","window.control","browser.observe",
    "browser.control","network.observe","device.observe","audio.observe",
    "audio.control","system.observe","system.control","power.control",
    "security.observe","ui.observe","ui.control",
})

EVENT_CATEGORY_PERMISSIONS={
    "mouse":"mouse.observe","keyboard":"keyboard.observe","screen":"screen.observe",
    "clipboard":"clipboard.read","filesystem":"filesystem.read","process":"process.observe",
    "window":"window.observe","browser":"browser.observe","network":"network.observe",
    "device":"device.observe","audio":"audio.observe","system":"system.observe",
    "power":"system.observe","security":"security.observe","ui":"ui.observe",
    "scheduler":"system.observe","resources":"system.observe",
}

def permission_for_event(category:str) -> str:
    """Resolve the least observation permission for an event category."""
    try:return EVENT_CATEGORY_PERMISSIONS[category.casefold()]
    except KeyError as error:raise ValueError(f"Unknown event category: {category}") from error
