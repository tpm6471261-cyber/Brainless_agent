"""Real portable polling detectors; optional Windows integrations fail closed."""
from __future__ import annotations
import hashlib, shutil, subprocess, sys
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
