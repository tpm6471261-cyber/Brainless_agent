"""Real desktop action adapters registered behind the central action boundary."""
from __future__ import annotations
import os
import shutil
import subprocess
from pathlib import Path
from app.event_system.actions import ActionRegistry, ActionSpec, RiskLevel

def register_desktop_actions(registry: ActionRegistry) -> None:
    def pyauto():
        import pyautogui
        return pyautogui
    def clipboard():
        import pyperclip
        return pyperclip
    def path(value: object) -> Path: return Path(str(value)).expanduser().resolve()
    def copy_file(a): return str(shutil.copy2(path(a["source"]), path(a["destination"])))
    def move_file(a): return str(shutil.move(path(a["source"]), path(a["destination"])))
    def delete_file(a): path(a["path"]).unlink(); return True
    def delete_folder(a): shutil.rmtree(path(a["path"])); return True
    def start_process(a): return subprocess.Popen([str(x) for x in a["command"]], shell=False).pid
    def stop_process(a): os.kill(int(a["pid"]), 15); return True
    specs = (
        ActionSpec("MOVE_MOUSE","Move pointer","mouse",frozenset({"mouse.control"}),RiskLevel.LOW,frozenset({"x","y"}),"none",lambda a:pyauto().moveTo(int(a["x"]),int(a["y"]))),
        ActionSpec("LEFT_CLICK","Left click","mouse",frozenset({"mouse.control"}),RiskLevel.MEDIUM,frozenset({"x","y"}),"none",lambda a:pyauto().click(int(a["x"]),int(a["y"]))),
        ActionSpec("RIGHT_CLICK","Right click","mouse",frozenset({"mouse.control"}),RiskLevel.MEDIUM,frozenset({"x","y"}),"none",lambda a:pyauto().click(int(a["x"]),int(a["y"]),button="right")),
        ActionSpec("DOUBLE_CLICK","Double click","mouse",frozenset({"mouse.control"}),RiskLevel.MEDIUM,frozenset({"x","y"}),"none",lambda a:pyauto().doubleClick(int(a["x"]),int(a["y"]))),
        ActionSpec("MIDDLE_CLICK","Middle click","mouse",frozenset({"mouse.control"}),RiskLevel.MEDIUM,frozenset({"x","y"}),"none",lambda a:pyauto().click(int(a["x"]),int(a["y"]),button="middle")),
        ActionSpec("MOUSE_DOWN","Hold mouse button","mouse",frozenset({"mouse.control"}),RiskLevel.MEDIUM,frozenset({"button"}),"none",lambda a:pyauto().mouseDown(button=str(a["button"]))),
        ActionSpec("MOUSE_UP","Release mouse button","mouse",frozenset({"mouse.control"}),RiskLevel.LOW,frozenset({"button"}),"none",lambda a:pyauto().mouseUp(button=str(a["button"]))),
        ActionSpec("SCROLL","Scroll wheel","mouse",frozenset({"mouse.control"}),RiskLevel.LOW,frozenset({"delta"}),"none",lambda a:pyauto().scroll(int(a["delta"]))),
        ActionSpec("DRAG","Drag pointer","mouse",frozenset({"mouse.control"}),RiskLevel.MEDIUM,frozenset({"x","y","duration","button"}),"none",lambda a:pyauto().dragTo(int(a["x"]),int(a["y"]),float(a["duration"]),button=str(a["button"]))),
        ActionSpec("PRESS_KEY","Press key","keyboard",frozenset({"keyboard.control"}),RiskLevel.MEDIUM,frozenset({"key"}),"none",lambda a:pyauto().press(str(a["key"]))),
        ActionSpec("RELEASE_KEY","Release key","keyboard",frozenset({"keyboard.control"}),RiskLevel.LOW,frozenset({"key"}),"none",lambda a:pyauto().keyUp(str(a["key"]))),
        ActionSpec("TYPE_TEXT","Type text","keyboard",frozenset({"keyboard.control"}),RiskLevel.MEDIUM,frozenset({"text"}),"none",lambda a:pyauto().write(str(a["text"]))),
        ActionSpec("HOTKEY","Press key combination","keyboard",frozenset({"keyboard.control"}),RiskLevel.MEDIUM,frozenset({"keys"}),"none",lambda a:pyauto().hotkey(*[str(x) for x in a["keys"]])),
        ActionSpec("READ_CLIPBOARD","Read clipboard","clipboard",frozenset({"clipboard.read"}),RiskLevel.MEDIUM,frozenset(),"text",lambda _:str(clipboard().paste())),
        ActionSpec("WRITE_CLIPBOARD","Write clipboard","clipboard",frozenset({"clipboard.write"}),RiskLevel.MEDIUM,frozenset({"text"}),"none",lambda a:clipboard().copy(str(a["text"]))),
        ActionSpec("CLEAR_CLIPBOARD","Clear clipboard","clipboard",frozenset({"clipboard.write"}),RiskLevel.MEDIUM,frozenset(),"none",lambda _:clipboard().copy("")),
        ActionSpec("CREATE_FILE","Create file","filesystem",frozenset({"filesystem.write"}),RiskLevel.MEDIUM,frozenset({"path","content"}),"path",lambda a:(path(a["path"]).write_text(str(a["content"]),encoding="utf-8"),str(path(a["path"])))[1]),
        ActionSpec("COPY_FILE","Copy file","filesystem",frozenset({"filesystem.write"}),RiskLevel.MEDIUM,frozenset({"source","destination"}),"path",copy_file),
        ActionSpec("MOVE_FILE","Move file","filesystem",frozenset({"filesystem.write"}),RiskLevel.MEDIUM,frozenset({"source","destination"}),"path",move_file),
        ActionSpec("DELETE_FILE","Delete file","filesystem",frozenset({"filesystem.delete"}),RiskLevel.HIGH,frozenset({"path"}),"bool",delete_file),
        ActionSpec("CREATE_FOLDER","Create folder","filesystem",frozenset({"filesystem.write"}),RiskLevel.MEDIUM,frozenset({"path"}),"path",lambda a:(path(a["path"]).mkdir(parents=True,exist_ok=True),str(path(a["path"])))[1]),
        ActionSpec("DELETE_FOLDER","Delete folder","filesystem",frozenset({"filesystem.delete"}),RiskLevel.HIGH,frozenset({"path"}),"bool",delete_folder),
        ActionSpec("START_PROCESS","Start process","process",frozenset({"process.control"}),RiskLevel.MEDIUM,frozenset({"command"}),"pid",start_process),
        ActionSpec("STOP_PROCESS","Terminate process","process",frozenset({"process.control"}),RiskLevel.HIGH,frozenset({"pid"}),"bool",stop_process),
        ActionSpec("TAKE_SCREENSHOT","Capture screen","screen",frozenset({"screen.capture"}),RiskLevel.MEDIUM,frozenset({"path"}),"path",lambda a:(pyauto().screenshot(str(path(a["path"]))),str(path(a["path"])))[1]),
    )
    for spec in specs: registry.register(spec)
