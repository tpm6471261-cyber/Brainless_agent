"""One-call facade for actions, data retrieval, variables, events, and capability discovery."""
from __future__ import annotations
import asyncio
import getpass
import os
import subprocess
from pathlib import Path
from app.event_system.actions import ActionRegistry
from app.event_system.bus import EventBus, EventManager
from app.event_system.detectors import FilesystemDetector, ResourceDetector, WindowsCapabilityReport
from app.event_system.native_actions import register_desktop_actions
from app.safety.redaction import redact

class AutoWindow:
    def __init__(self, *, permissions=(), watch_paths=(), dry_run=False, confirm=None) -> None:
        self.permissions=set(permissions);self.variables={};self.bus=EventBus()
        self.actions=ActionRegistry(dry_run=dry_run,confirm=confirm)
        register_desktop_actions(self.actions)
        self.events=EventManager(self.bus,(FilesystemDetector(watch_paths),ResourceDetector()))
    async def call_action(self,name:str,**arguments): return await self.actions.execute(name,arguments,self.permissions)
    def call_action_sync(self,name:str,**arguments): return asyncio.run(self.call_action(name,**arguments))
    def set_variable(self,name:str,value): self.variables[name]=value
    def get_variable(self,name:str,default=None): return self.variables.get(name,default)
    async def poll_events(self): return await self.events.poll_once()
    def emergency_stop(self): self.actions.emergency_stop();self.bus.paused=True
    def resume_agent_system(self): self.actions.resume();self.bus.paused=False
    def get_data(self,name:str,**arguments):
        if name=="CAPABILITIES":return WindowsCapabilityReport.detect()
        if name=="ENVIRONMENT":return {"user":getpass.getuser(),"cwd":str(Path.cwd()),"platform":os.name}
        if name=="DISK_USAGE":
            import shutil
            total,used,free=shutil.disk_usage(Path(arguments.get("path",Path.home())))
            return {"total":total,"used":used,"free":free}
        if name=="MOUSE_POSITION":
            import pyautogui
            p=pyautogui.position();return {"x":p.x,"y":p.y}
        if name=="SCREEN_SIZE":
            import pyautogui
            s=pyautogui.size();return {"width":s.width,"height":s.height}
        if name=="WINDOWS":
            import pygetwindow
            return [{"title":w.title,"position":[w.left,w.top],"size":[w.width,w.height],"minimized":w.isMinimized,"maximized":w.isMaximized} for w in pygetwindow.getAllWindows()]
        if name=="PROCESSES":
            if os.name!="nt":return []
            output=subprocess.run(["tasklist","/fo","csv","/nh"],capture_output=True,text=True,check=True).stdout
            import csv,io
            return [{"name":r[0],"pid":int(r[1])} for r in csv.reader(io.StringIO(output)) if len(r)>1]
        if name=="CLIPBOARD":
            import pyperclip
            return redact(str(pyperclip.paste()))
        raise KeyError(f"Unknown data function: {name}")
