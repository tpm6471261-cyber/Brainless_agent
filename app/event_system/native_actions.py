"""Real desktop action adapters registered behind the central action boundary."""
from __future__ import annotations
import os
import shutil
import subprocess
import webbrowser
import sys
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
        if pid<=4:raise PermissionError("Protected system process termination is forbidden")
        os.kill(pid,15);return True
    def get_screen_size(_):
        size=pyauto().size();return {"width":int(size[0]),"height":int(size[1])}
    def get_monitors(_):
        if sys.platform!="win32":
            size=get_screen_size({});return [{"id":0,"primary":True,"x":0,"y":0,**size}]
        import ctypes
        from ctypes import wintypes
        monitors=[]
        callback_type=ctypes.WINFUNCTYPE(ctypes.c_bool,wintypes.HMONITOR,wintypes.HDC,ctypes.POINTER(wintypes.RECT),wintypes.LPARAM)
        def callback(handle,_dc,rect,_data):
            area=rect.contents;monitors.append({"id":str(handle),"x":area.left,"y":area.top,
                "width":area.right-area.left,"height":area.bottom-area.top,
                "primary":area.left==0 and area.top==0});return True
        if not ctypes.windll.user32.EnumDisplayMonitors(None,None,callback_type(callback),0):raise OSError("EnumDisplayMonitors failed")
        return monitors
    def focus_application(a):
        import pygetwindow
        wanted=str(a["name"]).casefold()
        matches=[item for item in pygetwindow.getAllWindows() if wanted in str(item.title).casefold()]
        if not matches:raise LookupError("Application window was not found")
        matches[0].activate();return True
    def request_power(a):
        _=a
        if sys.platform!="win32":raise RuntimeError("Power control is available only on Windows")
        return True
    def open_path(a):
        target=str(path(a["path"]))
        if os.name=="nt":os.startfile(target)  # type: ignore[attr-defined]
        else:subprocess.Popen(["xdg-open",target],shell=False)
        return target
    def window(a):
        import pygetwindow
        matches=pygetwindow.getWindowsWithTitle(str(a["title"]))
        if not matches:raise LookupError("Window was not found")
        return matches[0]
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
        ActionSpec("KEY_DOWN","Hold key","keyboard",frozenset({"keyboard.control"}),RiskLevel.MEDIUM,frozenset({"key"}),"none",lambda a:pyauto().keyDown(str(a["key"]))),
        ActionSpec("RELEASE_KEY","Release key","keyboard",frozenset({"keyboard.control"}),RiskLevel.LOW,frozenset({"key"}),"none",lambda a:pyauto().keyUp(str(a["key"]))),
        ActionSpec("TYPE_TEXT","Type text","keyboard",frozenset({"keyboard.control"}),RiskLevel.MEDIUM,frozenset({"text"}),"none",lambda a:pyauto().write(str(a["text"]))),
        ActionSpec("HOTKEY","Press key combination","keyboard",frozenset({"keyboard.control"}),RiskLevel.MEDIUM,frozenset({"keys"}),"none",lambda a:pyauto().hotkey(*[str(x) for x in a["keys"]])),
        ActionSpec("KEY_SEQUENCE","Press a key sequence","keyboard",frozenset({"keyboard.control"}),RiskLevel.MEDIUM,frozenset({"keys","interval"}),"none",lambda a:pyauto().press([str(x) for x in a["keys"]],interval=float(a["interval"]))),
        ActionSpec("READ_CLIPBOARD","Read clipboard","clipboard",frozenset({"clipboard.read"}),RiskLevel.MEDIUM,frozenset(),"text",lambda _:str(clipboard().paste())),
        ActionSpec("WRITE_CLIPBOARD","Write clipboard","clipboard",frozenset({"clipboard.write"}),RiskLevel.MEDIUM,frozenset({"text"}),"none",lambda a:clipboard().copy(str(a["text"]))),
        ActionSpec("CLEAR_CLIPBOARD","Clear clipboard","clipboard",frozenset({"clipboard.write"}),RiskLevel.MEDIUM,frozenset(),"none",lambda _:clipboard().copy("")),
        ActionSpec("CREATE_FILE","Create file","filesystem",frozenset({"filesystem.write"}),RiskLevel.MEDIUM,frozenset({"path","content"}),"path",lambda a:(path(a["path"]).write_text(str(a["content"]),encoding="utf-8"),str(path(a["path"])))[1]),
        ActionSpec("COPY_FILE","Copy file","filesystem",frozenset({"filesystem.write"}),RiskLevel.MEDIUM,frozenset({"source","destination"}),"path",copy_file),
        ActionSpec("MOVE_FILE","Move file","filesystem",frozenset({"filesystem.write"}),RiskLevel.MEDIUM,frozenset({"source","destination"}),"path",move_file),
        ActionSpec("RENAME_FILE","Rename file","filesystem",frozenset({"filesystem.write"}),RiskLevel.MEDIUM,frozenset({"source","destination"}),"path",move_file),
        ActionSpec("DELETE_FILE","Delete file","filesystem",frozenset({"filesystem.delete"}),RiskLevel.HIGH,frozenset({"path"}),"bool",delete_file),
        ActionSpec("CREATE_FOLDER","Create folder","filesystem",frozenset({"filesystem.write"}),RiskLevel.MEDIUM,frozenset({"path"}),"path",lambda a:(path(a["path"]).mkdir(parents=True,exist_ok=True),str(path(a["path"])))[1]),
        ActionSpec("DELETE_FOLDER","Delete folder","filesystem",frozenset({"filesystem.delete"}),RiskLevel.HIGH,frozenset({"path"}),"bool",delete_folder),
        ActionSpec("OPEN_FILE","Open a file with its registered application","filesystem",frozenset({"filesystem.read"}),RiskLevel.MEDIUM,frozenset({"path"}),"path",open_path),
        ActionSpec("START_PROCESS","Start process","process",frozenset({"process.control"}),RiskLevel.MEDIUM,frozenset({"command"}),"pid",start_process),
        ActionSpec("STOP_PROCESS","Terminate process","process",frozenset({"process.control"}),RiskLevel.HIGH,frozenset({"pid"}),"bool",stop_process),
        ActionSpec("FOCUS_APPLICATION","Focus an application window","process",frozenset({"process.control"}),RiskLevel.MEDIUM,frozenset({"name"}),"bool",focus_application),
        ActionSpec("TAKE_SCREENSHOT","Capture screen","screen",frozenset({"screen.capture"}),RiskLevel.MEDIUM,frozenset({"path"}),"path",lambda a:(pyauto().screenshot(str(path(a["path"]))),str(path(a["path"])))[1]),
        ActionSpec("CAPTURE_REGION","Capture a screen region","screen",frozenset({"screen.capture"}),RiskLevel.MEDIUM,frozenset({"path","x","y","width","height"}),"path",lambda a:(pyauto().screenshot(str(path(a["path"])),region=(int(a["x"]),int(a["y"]),int(a["width"]),int(a["height"]))),str(path(a["path"])))[1]),
        ActionSpec("GET_SCREEN_SIZE","Get virtual screen size","screen",frozenset({"screen.observe"}),RiskLevel.LOW,frozenset(),"object",get_screen_size),
        ActionSpec("GET_MONITORS","Enumerate displays","screen",frozenset({"screen.observe"}),RiskLevel.LOW,frozenset(),"array",get_monitors),
        ActionSpec("MINIMIZE_WINDOW","Minimize a window","window",frozenset({"window.control"}),RiskLevel.MEDIUM,frozenset({"title"}),"none",lambda a:window(a).minimize()),
        ActionSpec("MAXIMIZE_WINDOW","Maximize a window","window",frozenset({"window.control"}),RiskLevel.MEDIUM,frozenset({"title"}),"none",lambda a:window(a).maximize()),
        ActionSpec("RESTORE_WINDOW","Restore a window","window",frozenset({"window.control"}),RiskLevel.MEDIUM,frozenset({"title"}),"none",lambda a:window(a).restore()),
        ActionSpec("CLOSE_WINDOW","Close a window","window",frozenset({"window.control"}),RiskLevel.HIGH,frozenset({"title"}),"none",lambda a:window(a).close()),
        ActionSpec("MOVE_WINDOW","Move a window","window",frozenset({"window.control"}),RiskLevel.MEDIUM,frozenset({"title","x","y"}),"none",lambda a:window(a).moveTo(int(a["x"]),int(a["y"]))),
        ActionSpec("RESIZE_WINDOW","Resize a window","window",frozenset({"window.control"}),RiskLevel.MEDIUM,frozenset({"title","width","height"}),"none",lambda a:window(a).resizeTo(int(a["width"]),int(a["height"]))),
        ActionSpec("FOCUS_WINDOW","Focus a window","window",frozenset({"window.control"}),RiskLevel.MEDIUM,frozenset({"title"}),"none",lambda a:window(a).activate()),
        ActionSpec("ACTIVATE_WINDOW","Activate a window","window",frozenset({"window.control"}),RiskLevel.MEDIUM,frozenset({"title"}),"none",lambda a:window(a).activate()),
        ActionSpec("OPEN_BROWSER","Open the default browser","browser",frozenset({"browser.control"}),RiskLevel.MEDIUM,frozenset(),"bool",lambda _:webbrowser.open("about:blank")),
        ActionSpec("OPEN_URL","Open URL in default browser","browser",frozenset({"browser.control"}),RiskLevel.MEDIUM,frozenset({"url"}),"bool",lambda a:webbrowser.open(str(a["url"]))),
        ActionSpec("REQUEST_SLEEP","Request Windows sleep","power",frozenset({"power.control","system.control"}),RiskLevel.HIGH,frozenset(),"bool",lambda a:(request_power(a),subprocess.run(["rundll32.exe","powrprof.dll,SetSuspendState","0,1,0"],check=True),True)[2]),
        ActionSpec("REQUEST_HIBERNATE","Request Windows hibernation","power",frozenset({"power.control","system.control"}),RiskLevel.HIGH,frozenset(),"bool",lambda a:(request_power(a),subprocess.run(["shutdown.exe","/h"],check=True),True)[2]),
        ActionSpec("REQUEST_SHUTDOWN","Request Windows shutdown","power",frozenset({"power.control","system.control"}),RiskLevel.HIGH,frozenset(),"bool",lambda a:(request_power(a),subprocess.run(["shutdown.exe","/s","/t","0"],check=True),True)[2]),
        ActionSpec("REQUEST_RESTART","Request Windows restart","power",frozenset({"power.control","system.control"}),RiskLevel.HIGH,frozenset(),"bool",lambda a:(request_power(a),subprocess.run(["shutdown.exe","/r","/t","0"],check=True),True)[2]),
    )
    for spec in specs: registry.register(spec)
