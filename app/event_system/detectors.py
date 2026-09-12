"""Real portable polling detectors; optional Windows integrations fail closed."""
from __future__ import annotations
import hashlib, importlib.util, shutil, socket, subprocess, sys
from datetime import datetime, timezone
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
                try: stat=path.stat();current[str(path)]=(path.is_dir(),stat.st_size,stat.st_mtime_ns,stat.st_ino,stat.st_ctime_ns)
                except OSError:continue
        events=[]
        removed={path:value for path,value in self._previous.items() if path not in current}
        added={path:value for path,value in current.items() if path not in self._previous}
        removed_by_inode={value[3]:path for path,value in removed.items() if value[3]}
        moved={path:removed_by_inode[value[3]] for path,value in added.items()
               if value[3] and value[3] in removed_by_inode}
        for path,value in current.items():
            old=self._previous.get(path);kind="FOLDER" if value[0] else "FILE"
            if path in moved:
                old_path=moved[path]; old_parent=Path(old_path).parent
                event_type=f"ON_{kind}_{'RENAMED' if old_parent==Path(path).parent else 'MOVED'}"
            elif old is None: event_type=f"ON_{kind}_CREATED"
            elif old!=value:event_type="ON_FILE_SIZE_CHANGED" if old[1]!=value[1] and not value[0] else f"ON_{kind}_MODIFIED"
            else:continue
            p=Path(path);data={"path":path,"filename":p.name,"extension":p.suffix,"size":value[1],
                "directory":str(p.parent),"creation_time_ns":value[4],"modified_time_ns":value[2]}
            if path in moved:data["previous_path"]=moved[path]
            events.append(Event(event_type,"filesystem",self.name,data=data,permissions_required=frozenset({"filesystem.read"})))
        for path,old in self._previous.items():
            if path not in current and path not in moved.values():events.append(Event(f"ON_{'FOLDER' if old[0] else 'FILE'}_DELETED","filesystem",self.name,data={"path":path},permissions_required=frozenset({"filesystem.read"})))
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
        installed=lambda name:importlib.util.find_spec(name) is not None
        powershell=windows and shutil.which("powershell.exe") is not None
        return {"Mouse":"AVAILABLE" if windows and installed("pyautogui") else "PARTIAL" if windows or installed("pyautogui") else "OPTIONAL FEATURE UNAVAILABLE",
            "Keyboard":"AVAILABLE" if windows and installed("pyautogui") else "PARTIAL" if windows or installed("pyautogui") else "OPTIONAL FEATURE UNAVAILABLE",
            "Window Events":"PARTIAL" if installed("pygetwindow") else "OPTIONAL FEATURE UNAVAILABLE",
            "Process Events":"AVAILABLE" if windows else "UNAVAILABLE", "Filesystem":"AVAILABLE",
            "Clipboard":"PARTIAL" if installed("pyperclip") else "OPTIONAL FEATURE UNAVAILABLE",
            "Screen":"PARTIAL" if installed("pyautogui") else "OPTIONAL FEATURE UNAVAILABLE",
            "UI Automation":"PARTIAL" if windows and installed("pygetwindow") else "OPTIONAL FEATURE UNAVAILABLE",
            "Browser":"PARTIAL",
            "Network":"AVAILABLE", "USB":"AVAILABLE" if powershell else "OPTIONAL FEATURE UNAVAILABLE",
            "Audio":"PARTIAL" if powershell else "OPTIONAL FEATURE UNAVAILABLE", "Power":"AVAILABLE" if windows else "UNAVAILABLE",
            "Notifications":"PARTIAL" if windows and installed("pygetwindow") else "OPTIONAL FEATURE UNAVAILABLE",
            "Sessions":"AVAILABLE" if powershell else "UNAVAILABLE",
            "Scheduler":"AVAILABLE", "Resources":"AVAILABLE"}

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

class SnapshotDetector:
    """Reusable state-diff detector for optional native adapters.

    Readers return a mapping of stable object IDs to safe metadata. This keeps
    platform-specific collection separate from event normalization and makes an
    adapter straightforward to inject for a future agent or test.
    """
    name="snapshot"
    def __init__(self,reader,*,category,created,removed,permission,source=None) -> None:
        self.reader=reader;self.category=category;self.created=created;self.removed=removed
        self.permission=permission;self.source=source or category;self.previous={};self.initialized=False
    async def poll(self):
        current=dict(self.reader());events=[]
        for key,value in current.items():
            if key not in self.previous:events.append(self._event(self.created,key,value))
            elif value!=self.previous[key]:events.append(self._event(f"ON_{self.category.upper()}_CHANGED",key,value,{"previous":self.previous[key]}))
        for key,value in self.previous.items():
            if key not in current:events.append(self._event(self.removed,key,value))
        self.previous=current;self.initialized=True;return tuple(events)
    def _event(self,event_type,key,value,extra=None):
        data={"id":str(key),**(dict(value) if isinstance(value,dict) else {"value":value}),**(extra or {})}
        return Event(event_type,self.category,self.source,data=data,permissions_required=frozenset({self.permission}))

class NetworkDetector(SnapshotDetector):
    """Observe interface/IP changes using only OS networking APIs."""
    @staticmethod
    def read_interfaces():
        result={}
        for family,_,_,_,address in socket.getaddrinfo(socket.gethostname(),None):
            ip=address[0]
            if family in {socket.AF_INET,socket.AF_INET6} and not ip.startswith("127.") and ip!="::1":
                result[ip]={"interface":"host","ip":ip,"family":"ipv6" if family==socket.AF_INET6 else "ipv4"}
        return result
    def __init__(self,reader=None) -> None:
        super().__init__(reader or self.read_interfaces,category="network",created="ON_NETWORK_CONNECTED",
            removed="ON_NETWORK_DISCONNECTED",permission="network.observe")

class WindowDetector(SnapshotDetector):
    """Poll visible desktop windows; pygetwindow is loaded only when enabled."""
    @staticmethod
    def read_windows():
        import pygetwindow
        return {str(getattr(w,"_hWnd",w.title)):{"window_handle":getattr(w,"_hWnd",None),"title":w.title,
            "position":{"x":w.left,"y":w.top},"size":{"width":w.width,"height":w.height},
            "state":"minimized" if w.isMinimized else "maximized" if w.isMaximized else "normal"}
            for w in pygetwindow.getAllWindows() if w.title}
    def __init__(self,reader=None) -> None:
        super().__init__(reader or self.read_windows,category="window",created="ON_WINDOW_CREATED",
            removed="ON_WINDOW_DESTROYED",permission="window.observe")
    async def poll(self):
        current=dict(self.reader());events=[]
        for key,value in current.items():
            if key not in self.previous:
                events.extend((self._event("ON_WINDOW_CREATED",key,value),self._event("ON_WINDOW_OPENED",key,value)))
                continue
            old=self.previous[key]
            changes=(("title","ON_WINDOW_TITLE_CHANGED"),("position","ON_WINDOW_MOVED"),
                     ("size","ON_WINDOW_RESIZED"),("visible","ON_WINDOW_VISIBILITY_CHANGED"))
            for field,event_type in changes:
                if value.get(field)!=old.get(field):events.append(self._event(event_type,key,value,{f"previous_{field}":old.get(field)}))
            if value.get("state")!=old.get("state"):
                state=str(value.get("state","normal")).upper()
                kind="ON_WINDOW_RESTORED" if state=="NORMAL" else f"ON_WINDOW_{state}" if state in {"MINIMIZED","MAXIMIZED"} else "ON_WINDOW_STATE_CHANGED"
                events.append(self._event(kind,key,value,{"previous_state":old.get("state")}))
                if kind!="ON_WINDOW_STATE_CHANGED":events.append(self._event("ON_WINDOW_STATE_CHANGED",key,value,{"previous_state":old.get("state")}))
        for key,value in self.previous.items():
            if key not in current:events.extend((self._event("ON_WINDOW_DESTROYED",key,value),self._event("ON_WINDOW_CLOSED",key,value)))
        self.previous=current;self.initialized=True;return tuple(events)

class PowerDetector:
    """Read Windows SYSTEM_POWER_STATUS and emit battery/power transitions."""
    name="power"
    def __init__(self,reader=None) -> None:self.reader=reader or self._read_windows;self.previous=None
    @staticmethod
    def _read_windows():
        if sys.platform!="win32":return None
        import ctypes
        class Status(ctypes.Structure):
            _fields_=[("ACLineStatus",ctypes.c_byte),("BatteryFlag",ctypes.c_byte),
                ("BatteryLifePercent",ctypes.c_byte),("SystemStatusFlag",ctypes.c_byte),
                ("BatteryLifeTime",ctypes.c_ulong),("BatteryFullLifeTime",ctypes.c_ulong)]
        state=Status()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(state)):raise OSError("GetSystemPowerStatus failed")
        return {"battery_percentage":int(state.BatteryLifePercent),"charging":state.ACLineStatus==1,
            "power_source":"ac" if state.ACLineStatus==1 else "battery"}
    async def poll(self):
        current=self.reader()
        if current is None or current==self.previous:return ()
        old=self.previous;self.previous=dict(current);events=[]
        if old is None or old.get("charging")!=current["charging"]:events.append(Event(
            "ON_AC_CONNECTED" if current["charging"] else "ON_AC_DISCONNECTED","power",self.name,data=dict(current),permissions_required=frozenset({"system.observe"})))
        if old is not None and old.get("battery_percentage")!=current["battery_percentage"]:events.append(Event(
            "ON_BATTERY_LEVEL_CHANGED","power",self.name,data={**current,"previous_percentage":old.get("battery_percentage")},permissions_required=frozenset({"system.observe"})))
        level=current["battery_percentage"]
        if level<=5:events.append(Event("ON_BATTERY_CRITICAL","power",self.name,data=dict(current),severity=EventSeverity.CRITICAL,permissions_required=frozenset({"system.observe"})))
        elif level<=15:events.append(Event("ON_BATTERY_LOW","power",self.name,data=dict(current),severity=EventSeverity.WARNING,permissions_required=frozenset({"system.observe"})))
        return tuple(events)

class SchedulerDetector:
    """One-time and recurring monotonic timers suitable as agent building blocks."""
    name="scheduler"
    def __init__(self,clock=None) -> None:self.clock=clock or (lambda:datetime.now(timezone.utc));self._timers={}
    def schedule(self,timer_id:str,when:datetime,*,interval_seconds:float|None=None,data=None) -> None:
        if when.tzinfo is None:raise ValueError("Timer datetime must be timezone-aware")
        if interval_seconds is not None and interval_seconds<=0:raise ValueError("Interval must be positive")
        self._timers[timer_id]=[when,interval_seconds,dict(data or {})]
    def cancel(self,timer_id:str) -> None:self._timers.pop(timer_id,None)
    async def poll(self):
        now=self.clock();events=[]
        for timer_id,(when,interval,data) in tuple(self._timers.items()):
            if now<when:continue
            kind="ON_INTERVAL" if interval else "ON_TIMER"
            events.append(Event(kind,"scheduler",self.name,data={"timer_id":timer_id,**data},permissions_required=frozenset({"system.observe"})))
            if interval:self._timers[timer_id][0]=now.__class__.fromtimestamp(now.timestamp()+interval,tz=now.tzinfo)
            else:self._timers.pop(timer_id,None)
        return tuple(events)
