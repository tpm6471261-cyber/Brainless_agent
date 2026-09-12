"""Real portable polling detectors; optional Windows integrations fail closed."""
from __future__ import annotations
import hashlib, shutil, socket, subprocess, sys
from datetime import datetime
from pathlib import Path
from app.event_system.models import Event, EventSeverity

class FilesystemDetector:
    name="filesystem"
    def __init__(self,paths,limit=5000) -> None:self.paths=tuple(Path(x).resolve() for x in paths);self.limit=limit;self._previous={}
    async def poll(self):
        current={}
        for root in self.paths:
            if not root.exists():continue
            for path in list(root.rglob("*"))[:self.limit]:
                try: stat=path.stat();current[str(path)]=(path.is_dir(),stat.st_size,stat.st_mtime_ns)
                except OSError:continue
        events=[]
        for path,value in current.items():
            old=self._previous.get(path);kind="FOLDER" if value[0] else "FILE"
            if old is None: event_type=f"ON_{kind}_CREATED"
            elif old!=value:event_type="ON_FILE_SIZE_CHANGED" if old[1]!=value[1] and not value[0] else f"ON_{kind}_MODIFIED"
            else:continue
            p=Path(path);events.append(Event(event_type,"filesystem",self.name,data={"path":path,"filename":p.name,"extension":p.suffix,"size":value[1],"directory":str(p.parent)},permissions_required=frozenset({"filesystem.read"})))
        for path,old in self._previous.items():
            if path not in current:events.append(Event(f"ON_{'FOLDER' if old[0] else 'FILE'}_DELETED","filesystem",self.name,data={"path":path},permissions_required=frozenset({"filesystem.read"})))
        self._previous=current;return tuple(events)

class ResourceDetector:
    name="resources"
    def __init__(self,disk_percent=90) -> None:self.disk_percent=disk_percent;self._alerted=False
    async def poll(self):
        total,used,_=shutil.disk_usage(Path.home());percent=used/total*100 if total else 0
        alert=percent>=self.disk_percent
        if alert==self._alerted:return ()
        self._alerted=alert
        return (Event("ON_DISK_THRESHOLD","resources",self.name,
            data={"percent":round(percent,2),"threshold":self.disk_percent},
            severity=EventSeverity.WARNING if alert else EventSeverity.INFO,
            permissions_required=frozenset({"system.observe"})),)

class WindowsCapabilityReport:
    @staticmethod
    def detect() -> dict[str,str]:
        windows=sys.platform=="win32"
        return {"Mouse":"AVAILABLE" if windows else "UNAVAILABLE", "Keyboard":"AVAILABLE" if windows else "UNAVAILABLE",
            "Window Events":"AVAILABLE" if windows else "UNAVAILABLE", "Process Events":"PARTIAL",
            "Filesystem":"AVAILABLE", "UI Automation":"OPTIONAL FEATURE UNAVAILABLE",
            "Browser":"PARTIAL", "Network":"PARTIAL", "USB":"OPTIONAL FEATURE UNAVAILABLE",
            "Audio":"OPTIONAL FEATURE UNAVAILABLE", "Power":"PARTIAL" if windows else "UNAVAILABLE"}

class MousePositionDetector:
    name="mouse"
    def __init__(self,reader=None) -> None:self.reader=reader;self.previous=None
    async def poll(self):
        if self.reader is None:
            import pyautogui
            self.reader=pyautogui.position
        point=self.reader();position=((int(point[0]),int(point[1])))
        if position==self.previous:return ()
        old=self.previous;self.previous=position
        return (Event("ON_MOUSE_POSITION_CHANGED","mouse",self.name,data={"x":position[0],"y":position[1],"previous":old},permissions_required=frozenset({"mouse.observe"})),)

class ClipboardDetector:
    """Detect change using an in-memory digest; clipboard content never enters events/history."""
    name="clipboard"
    def __init__(self,reader=None,enabled=False) -> None:self.reader=reader;self.enabled=enabled;self.previous=None
    async def poll(self):
        if not self.enabled:return ()
        if self.reader is None:
            import pyperclip
            self.reader=pyperclip.paste
        value=str(self.reader());digest=hashlib.sha256(value.encode()).hexdigest()
        if digest==self.previous:return ()
        self.previous=digest
        return (Event("ON_CLIPBOARD_CHANGED","clipboard",self.name,data={"content_type":"text","length":len(value)},permissions_required=frozenset({"clipboard.read"})),)

class DisplayDetector:
    name="display"
    def __init__(self,reader=None) -> None:self.reader=reader;self.previous=None
    async def poll(self):
        if self.reader is None:
            import pyautogui
            self.reader=pyautogui.size
        size=self.reader();current=(int(size[0]),int(size[1]))
        if current==self.previous:return ()
        event_type="ON_DISPLAY_CONFIGURATION_CHANGED" if self.previous is None else "ON_RESOLUTION_CHANGED"
        previous=self.previous;self.previous=current
        return (Event(event_type,"screen",self.name,data={"width":current[0],"height":current[1],"previous":previous},permissions_required=frozenset({"screen.observe"})),)

class ProcessDetector:
    name="process"
    def __init__(self,reader=None) -> None:self.reader=reader;self.previous={}
    def _read_windows(self):
        import csv,io
        output=subprocess.run(["tasklist","/fo","csv","/nh"],capture_output=True,text=True,check=True).stdout
        return {int(row[1]):row[0] for row in csv.reader(io.StringIO(output)) if len(row)>1}
    async def poll(self):
        if self.reader is None:
            if sys.platform!="win32":return ()
            self.reader=self._read_windows
        current=dict(self.reader());events=[]
        for pid,name in current.items():
            if pid not in self.previous:events.append(Event("ON_PROCESS_STARTED","process",self.name,process=name,data={"pid":pid,"name":name},permissions_required=frozenset({"process.observe"})))
        for pid,name in self.previous.items():
            if pid not in current:events.append(Event("ON_PROCESS_STOPPED","process",self.name,process=name,data={"pid":pid,"name":name},permissions_required=frozenset({"process.observe"})))
        self.previous=current;return tuple(events)

class KeyboardStateDetector:
    """Poll key transitions without recording typed text (disabled by default)."""
    name="keyboard"
    KEYS={"CTRL":0x11,"ALT":0x12,"SHIFT":0x10,"WIN":0x5B,"ENTER":0x0D,"ESCAPE":0x1B,
          "TAB":0x09,"BACKSPACE":0x08,"DELETE":0x2E,"INSERT":0x2D,"HOME":0x24,"END":0x23,
          "PAGEUP":0x21,"PAGEDOWN":0x22,"LEFT":0x25,"UP":0x26,"RIGHT":0x27,"DOWN":0x28,
          **{chr(code):code for code in range(0x30,0x5B)},**{f"F{i}":0x6F+i for i in range(1,13)}}
    def __init__(self,reader=None,enabled=False,hotkeys=()) -> None:
        self.reader,self.enabled,self.hotkeys=reader,enabled,tuple(tuple(x.upper() for x in h) for h in hotkeys);self.previous=set()
    def _windows_reader(self):
        import ctypes
        return {name for name,code in self.KEYS.items() if ctypes.windll.user32.GetAsyncKeyState(code)&0x8000}
    async def poll(self):
        if not self.enabled:return ()
        if self.reader is None:
            if sys.platform!="win32":return ()
            self.reader=self._windows_reader
        current={str(x).upper() for x in self.reader()};events=[]
        for key in sorted(current-self.previous):
            kind="ON_MODIFIER_CHANGED" if key in {"CTRL","ALT","SHIFT","WIN"} else "ON_KEY_DOWN"
            events.append(Event(kind,"keyboard",self.name,data={"key":key,"pressed":True},permissions_required=frozenset({"keyboard.observe"})))
        for key in sorted(self.previous-current):
            kind="ON_MODIFIER_CHANGED" if key in {"CTRL","ALT","SHIFT","WIN"} else "ON_KEY_UP"
            events.append(Event(kind,"keyboard",self.name,data={"key":key,"pressed":False},permissions_required=frozenset({"keyboard.observe"})))
        for hotkey in self.hotkeys:
            if set(hotkey).issubset(current) and not set(hotkey).issubset(self.previous):
                events.append(Event("ON_HOTKEY","keyboard",self.name,data={"keys":hotkey},permissions_required=frozenset({"keyboard.observe"})))
        self.previous=current;return tuple(events)

class WindowDetector:
    """Diff snapshots from Win32 (or an injected reader) into window lifecycle events."""
    name="windows"
    def __init__(self,reader=None) -> None:self.reader=reader;self.previous={};self.active=None
    def _read_windows(self):
        import ctypes
        user32=ctypes.windll.user32;windows={};active=int(user32.GetForegroundWindow())
        callback_type=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
        def visit(hwnd,_):
            length=user32.GetWindowTextLengthW(hwnd);title=ctypes.create_unicode_buffer(length+1);user32.GetWindowTextW(hwnd,title,length+1)
            rect=(ctypes.c_long*4)();user32.GetWindowRect(hwnd,rect);pid=ctypes.c_ulong();user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            windows[int(hwnd)]={"window_handle":int(hwnd),"title":title.value,"process_id":pid.value,
                "position":(rect[0],rect[1]),"size":(rect[2]-rect[0],rect[3]-rect[1]),"visible":bool(user32.IsWindowVisible(hwnd)),
                "state":"minimized" if user32.IsIconic(hwnd) else "maximized" if user32.IsZoomed(hwnd) else "normal"}
            return True
        user32.EnumWindows(callback_type(visit),0);return windows,active
    async def poll(self):
        if self.reader is None:
            if sys.platform!="win32":return ()
            self.reader=self._read_windows
        current,active=self.reader();events=[]
        for hwnd,item in current.items():
            old=self.previous.get(hwnd);base=dict(item)
            if old is None:events.append(Event("ON_WINDOW_CREATED","window",self.name,window=item.get("title"),data=base,permissions_required=frozenset({"window.observe"})))
            else:
                for field,event_type in (("title","ON_WINDOW_TITLE_CHANGED"),("position","ON_WINDOW_MOVED"),("size","ON_WINDOW_RESIZED"),("visible","ON_WINDOW_VISIBILITY_CHANGED"),("state","ON_WINDOW_STATE_CHANGED")):
                    if old.get(field)!=item.get(field):events.append(Event(event_type,"window",self.name,window=item.get("title"),data={**base,f"previous_{field}":old.get(field)},permissions_required=frozenset({"window.observe"})))
        for hwnd,item in self.previous.items():
            if hwnd not in current:events.append(Event("ON_WINDOW_DESTROYED","window",self.name,window=item.get("title"),data=dict(item),permissions_required=frozenset({"window.observe"})))
        if active!=self.active:
            if self.active in self.previous:events.append(Event("ON_WINDOW_DEACTIVATED","window",self.name,window=self.previous[self.active].get("title"),data=dict(self.previous[self.active]),permissions_required=frozenset({"window.observe"})))
            if active in current:events.append(Event("ON_WINDOW_ACTIVATED","window",self.name,window=current[active].get("title"),data=dict(current[active]),permissions_required=frozenset({"window.observe"})))
        self.previous,self.active=dict(current),active;return tuple(events)

class PowerDetector:
    name="power"
    def __init__(self,reader=None) -> None:self.reader=reader;self.previous=None
    def _read_windows(self):
        import ctypes
        class Status(ctypes.Structure):_fields_=[("ac",ctypes.c_byte),("flags",ctypes.c_byte),("percent",ctypes.c_byte),("reserved",ctypes.c_byte),("life",ctypes.c_ulong),("full",ctypes.c_ulong)]
        status=Status()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):raise OSError("GetSystemPowerStatus failed")
        return {"ac_connected":status.ac==1,"battery_percent":None if status.percent==255 else int(status.percent),"charging":bool(status.flags&8)}
    async def poll(self):
        if self.reader is None:
            if sys.platform!="win32":return ()
            self.reader=self._read_windows
        current=dict(self.reader());events=[];old=self.previous
        if old is not None and old.get("ac_connected")!=current.get("ac_connected"):
            events.append(Event("ON_AC_CONNECTED" if current.get("ac_connected") else "ON_AC_DISCONNECTED","power",self.name,data=current,permissions_required=frozenset({"system.observe"})))
        percent=current.get("battery_percent")
        if old is None or old.get("battery_percent")!=percent:
            events.append(Event("ON_BATTERY_LEVEL_CHANGED","power",self.name,data={**current,"previous_battery_percent":None if old is None else old.get("battery_percent")},permissions_required=frozenset({"system.observe"})))
            if percent is not None and percent<=10:events.append(Event("ON_BATTERY_CRITICAL" if percent<=5 else "ON_BATTERY_LOW","power",self.name,data=current,severity=EventSeverity.WARNING,permissions_required=frozenset({"system.observe"})))
        self.previous=current;return tuple(events)

class NetworkDetector:
    name="network"
    def __init__(self,reader=None) -> None:self.reader=reader;self.previous=None
    def _read(self):return sorted({x[4][0] for x in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET) if not x[4][0].startswith("127.")})
    async def poll(self):
        current=tuple((self.reader or self._read)());events=[]
        if self.previous is not None and bool(current)!=bool(self.previous):events.append(Event("ON_NETWORK_CONNECTED" if current else "ON_NETWORK_DISCONNECTED","network",self.name,data={"connected":bool(current),"address_count":len(current)},permissions_required=frozenset({"network.observe"})))
        if self.previous is not None and current!=self.previous:events.append(Event("ON_IP_CHANGED","network",self.name,data={"address_count":len(current)},permissions_required=frozenset({"network.observe"})))
        self.previous=current;return tuple(events)

class SchedulerDetector:
    name="scheduler"
    def __init__(self,interval_seconds=60,clock=None) -> None:self.interval_seconds=float(interval_seconds);self.clock=clock or datetime.now;self.previous=None
    async def poll(self):
        now=self.clock();events=[]
        if self.previous is None or (now-self.previous).total_seconds()>=self.interval_seconds:events.append(Event("ON_INTERVAL","scheduler",self.name,data={"timestamp":now.isoformat(),"interval_seconds":self.interval_seconds}))
        if self.previous is not None:
            if now.minute!=self.previous.minute:events.append(Event("ON_MINUTE","scheduler",self.name,data={"timestamp":now.isoformat()}))
            if now.hour!=self.previous.hour:events.append(Event("ON_HOUR","scheduler",self.name,data={"timestamp":now.isoformat()}))
            if now.date()!=self.previous.date():events.append(Event("ON_DATE_CHANGED","scheduler",self.name,data={"date":now.date().isoformat(),"previous_date":self.previous.date().isoformat()}))
        self.previous=now;return tuple(events)
