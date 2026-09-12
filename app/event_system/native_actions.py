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
    def stop_process(a):
        pid=int(a["pid"])
        if pid<=4 or pid==os.getpid():raise PermissionError("Protected process termination is refused")
        os.kill(pid,15);return True
    def rename_file(a):
        destination=path(a["destination"]);path(a["source"]).rename(destination);return str(destination)
    def open_file(a):
        target=path(a["path"])
        if os.name!="nt":raise OSError("OPEN_FILE is only supported on Windows")
        os.startfile(target)  # type: ignore[attr-defined]
        return str(target)
    def window(a):
        import pygetwindow
        matches=pygetwindow.getWindowsWithTitle(str(a["title"]))
        if not matches:raise LookupError("Window not found")
        return matches[0]
    def system_command(argument):
        if os.name!="nt":raise OSError("System power actions are only supported on Windows")
        return subprocess.Popen(argument,shell=False).pid
    specs = (
        ActionSpec("MOVE_MOUSE","Move pointer","mouse",frozenset({"mouse.control"}),RiskLevel.LOW,frozenset({"x","y"}),"none",lambda a:pyauto().moveTo(int(a["x"]),int(a["y"]))),
        ActionSpec("SET_MOUSE_POSITION","Set pointer position","mouse",frozenset({"mouse.control"}),RiskLevel.LOW,frozenset({"x","y"}),"none",lambda a:pyauto().moveTo(int(a["x"]),int(a["y"]))),
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
        ActionSpec("KEY_SEQUENCE","Press keys in order","keyboard",frozenset({"keyboard.control"}),RiskLevel.MEDIUM,frozenset({"keys","interval"}),"none",lambda a:pyauto().press([str(x) for x in a["keys"]],interval=float(a["interval"]))),
        ActionSpec("READ_CLIPBOARD","Read clipboard","clipboard",frozenset({"clipboard.read"}),RiskLevel.MEDIUM,frozenset(),"text",lambda _:str(clipboard().paste())),
        ActionSpec("WRITE_CLIPBOARD","Write clipboard","clipboard",frozenset({"clipboard.write"}),RiskLevel.MEDIUM,frozenset({"text"}),"none",lambda a:clipboard().copy(str(a["text"]))),
        ActionSpec("CLEAR_CLIPBOARD","Clear clipboard","clipboard",frozenset({"clipboard.write"}),RiskLevel.MEDIUM,frozenset(),"none",lambda _:clipboard().copy("")),
        ActionSpec("CREATE_FILE","Create file","filesystem",frozenset({"filesystem.write"}),RiskLevel.MEDIUM,frozenset({"path","content"}),"path",lambda a:(path(a["path"]).write_text(str(a["content"]),encoding="utf-8"),str(path(a["path"])))[1]),
        ActionSpec("COPY_FILE","Copy file","filesystem",frozenset({"filesystem.write"}),RiskLevel.MEDIUM,frozenset({"source","destination"}),"path",copy_file),
        ActionSpec("MOVE_FILE","Move file","filesystem",frozenset({"filesystem.write"}),RiskLevel.MEDIUM,frozenset({"source","destination"}),"path",move_file),
        ActionSpec("RENAME_FILE","Rename file or folder","filesystem",frozenset({"filesystem.write"}),RiskLevel.MEDIUM,frozenset({"source","destination"}),"path",rename_file),
        ActionSpec("OPEN_FILE","Open file with its registered application","filesystem",frozenset({"filesystem.read"}),RiskLevel.MEDIUM,frozenset({"path"}),"path",open_file),
        ActionSpec("DELETE_FILE","Delete file","filesystem",frozenset({"filesystem.delete"}),RiskLevel.HIGH,frozenset({"path"}),"bool",delete_file),
        ActionSpec("CREATE_FOLDER","Create folder","filesystem",frozenset({"filesystem.write"}),RiskLevel.MEDIUM,frozenset({"path"}),"path",lambda a:(path(a["path"]).mkdir(parents=True,exist_ok=True),str(path(a["path"])))[1]),
        ActionSpec("DELETE_FOLDER","Delete folder","filesystem",frozenset({"filesystem.delete"}),RiskLevel.HIGH,frozenset({"path"}),"bool",delete_folder),
        ActionSpec("START_PROCESS","Start process","process",frozenset({"process.control"}),RiskLevel.MEDIUM,frozenset({"command"}),"pid",start_process),
        ActionSpec("STOP_PROCESS","Terminate process","process",frozenset({"process.control"}),RiskLevel.HIGH,frozenset({"pid"}),"bool",stop_process),
        ActionSpec("TAKE_SCREENSHOT","Capture screen","screen",frozenset({"screen.capture"}),RiskLevel.MEDIUM,frozenset({"path"}),"path",lambda a:(pyauto().screenshot(str(path(a["path"]))),str(path(a["path"])))[1]),
        ActionSpec("CAPTURE_REGION","Capture a screen region","screen",frozenset({"screen.capture"}),RiskLevel.MEDIUM,frozenset({"path","left","top","width","height"}),"path",lambda a:(pyauto().screenshot(str(path(a["path"])),region=(int(a["left"]),int(a["top"]),int(a["width"]),int(a["height"]))),str(path(a["path"])))[1]),
        ActionSpec("CLOSE_WINDOW","Close a window","window",frozenset({"window.control"}),RiskLevel.HIGH,frozenset({"title"}),"none",lambda a:window(a).close()),
        ActionSpec("MINIMIZE_WINDOW","Minimize a window","window",frozenset({"window.control"}),RiskLevel.LOW,frozenset({"title"}),"none",lambda a:window(a).minimize()),
        ActionSpec("MAXIMIZE_WINDOW","Maximize a window","window",frozenset({"window.control"}),RiskLevel.LOW,frozenset({"title"}),"none",lambda a:window(a).maximize()),
        ActionSpec("RESTORE_WINDOW","Restore a window","window",frozenset({"window.control"}),RiskLevel.LOW,frozenset({"title"}),"none",lambda a:window(a).restore()),
        ActionSpec("FOCUS_WINDOW","Focus a window","window",frozenset({"window.control"}),RiskLevel.MEDIUM,frozenset({"title"}),"none",lambda a:window(a).activate()),
        ActionSpec("MOVE_WINDOW","Move a window","window",frozenset({"window.control"}),RiskLevel.MEDIUM,frozenset({"title","x","y"}),"none",lambda a:window(a).moveTo(int(a["x"]),int(a["y"]))),
        ActionSpec("RESIZE_WINDOW","Resize a window","window",frozenset({"window.control"}),RiskLevel.MEDIUM,frozenset({"title","width","height"}),"none",lambda a:window(a).resizeTo(int(a["width"]),int(a["height"]))),
        ActionSpec("REQUEST_SHUTDOWN","Request Windows shutdown","power",frozenset({"system.control","power.control"}),RiskLevel.CRITICAL,frozenset(),"pid",lambda _:system_command(["shutdown.exe","/s","/t","0"])),
        ActionSpec("REQUEST_RESTART","Request Windows restart","power",frozenset({"system.control","power.control"}),RiskLevel.CRITICAL,frozenset(),"pid",lambda _:system_command(["shutdown.exe","/r","/t","0"])),
        ActionSpec("REQUEST_HIBERNATE","Request Windows hibernation","power",frozenset({"system.control","power.control"}),RiskLevel.CRITICAL,frozenset(),"pid",lambda _:system_command(["shutdown.exe","/h"])),
    )
    for spec in specs: registry.register(spec)
