"""Do It desktop planner with a local REST API. Run with: python app.py"""
from __future__ import annotations
import calendar, ctypes, json, threading, tkinter as tk, urllib.request, uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import urlparse
from email.utils import parsedate_to_datetime

ROOT=Path(__file__).resolve().parent; DATA_FILE=ROOT/"data"/"tasks.json"; HOST,PORT="127.0.0.1",8787; LOCK=threading.Lock()
IST=timezone(timedelta(hours=5, minutes=30), "IST"); CLOCK_LOCK=threading.Lock(); CLOCK_OFFSET=timedelta(); CLOCK_SOURCE="Device clock"
def now(): return datetime.now(timezone.utc).isoformat()
def ist_now():
    with CLOCK_LOCK: offset=CLOCK_OFFSET
    return datetime.now(IST)+offset
def sync_ist_clock():
    global CLOCK_OFFSET,CLOCK_SOURCE
    try:
        request=urllib.request.Request("https://www.google.com/generate_204",headers={"User-Agent":"DoIt/1.0"})
        with urllib.request.urlopen(request,timeout=4) as response: server_time=parsedate_to_datetime(response.headers["Date"]).astimezone(timezone.utc)
        with CLOCK_LOCK: CLOCK_OFFSET=server_time-datetime.now(timezone.utc); CLOCK_SOURCE="Online IST"
    except (OSError,ValueError,KeyError,TypeError):
        with CLOCK_LOCK: CLOCK_SOURCE="Device IST fallback"
def ist_datetime(day, hour, minute, period):
    hour=int(hour)%12+(12 if period=="PM" else 0); return datetime.strptime(f"{day} {hour:02d}:{minute}","%Y-%m-%d %H:%M").replace(tzinfo=IST)
def dark_title_bar(window):
    """Use Windows' native dark chrome when it is available."""
    try:
        enabled=ctypes.c_int(1); color=ctypes.c_int(0x0025201E); border=ctypes.c_int(0x0025201E)
        for attribute in (20,19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(window.winfo_id(),attribute,ctypes.byref(enabled),ctypes.sizeof(enabled))==0: break
        ctypes.windll.dwmapi.DwmSetWindowAttribute(window.winfo_id(),35,ctypes.byref(color),ctypes.sizeof(color))
        ctypes.windll.dwmapi.DwmSetWindowAttribute(window.winfo_id(),34,ctypes.byref(border),ctypes.sizeof(border))
    except (AttributeError,OSError): pass
def load_tasks():
    DATA_FILE.parent.mkdir(exist_ok=True)
    try: return json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else []
    except (json.JSONDecodeError,OSError): return []
def save_tasks(tasks):
    DATA_FILE.parent.mkdir(exist_ok=True); temp=DATA_FILE.with_suffix(".tmp"); temp.write_text(json.dumps(tasks,indent=2),encoding="utf-8"); temp.replace(DATA_FILE)
def future_time(value, label):
    if not value: return
    try:
        stamp=datetime.fromisoformat(value.replace("Z","+00:00"))
        if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=IST)
    except ValueError: raise ValueError(f"{label} must be a valid date and time.")
    if stamp.astimezone(IST)<=ist_now(): raise ValueError(f"{label} must be in the future (IST).")
def clean_task(payload, existing=None):
    task=existing.copy() if existing else {"id":str(uuid.uuid4()),"createdAt":now()}
    for field,default in (("title",""),("notes",""),("category","Personal"),("dueAt",""),("remindAt",""),("priority","Medium")):
        task[field]=str(payload[field]).strip() if field in payload else task.get(field,default)
    if not task["title"]: raise ValueError("A task title is required.")
    if task["category"] not in {"Exam","Learning","Project","Personal"}: task["category"]="Personal"
    if task["priority"] not in {"High","Medium","Low"}: task["priority"]="Medium"
    if "dueAt" in payload: future_time(task["dueAt"], "The due time")
    if "remindAt" in payload: future_time(task["remindAt"], "The reminder time")
    task["completed"]=bool(payload["completed"]) if "completed" in payload else task.get("completed",False); task["updatedAt"]=now(); return task

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_): pass
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Access-Control-Allow-Headers","Content-Type"); self.send_header("Access-Control-Allow-Methods","GET, POST, PATCH, DELETE, OPTIONS"); super().end_headers()
    def route(self): return urlparse(self.path).path.rstrip("/")
    def body(self): return json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))) or b"{}")
    def reply(self,body,status=200):
        data=json.dumps(body).encode(); self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_OPTIONS(self): self.send_response(204); self.end_headers()
    def do_GET(self):
        if self.route()=="/api/health": return self.reply({"ok":True,"service":"Do It","time":now()})
        if self.route()=="/api/tasks":
            with LOCK: tasks=load_tasks()
            return self.reply(sorted(tasks,key=lambda t:(t["completed"],t.get("dueAt") or "9999")))
        self.reply({"error":"Not found"},404)
    def do_POST(self):
        if self.route()!="/api/tasks": return self.reply({"error":"Not found"},404)
        try:
            with LOCK: tasks=load_tasks(); task=clean_task(self.body()); tasks.append(task); save_tasks(tasks)
            self.reply(task,201)
        except (ValueError,json.JSONDecodeError) as e: self.reply({"error":str(e)},400)
    def do_PATCH(self):
        task_id=self.route().removeprefix("/api/tasks/")
        try:
            with LOCK:
                tasks=load_tasks(); pos=next((i for i,t in enumerate(tasks) if t["id"]==task_id),None)
                if pos is None: return self.reply({"error":"Task not found"},404)
                tasks[pos]=clean_task(self.body(),tasks[pos]); save_tasks(tasks)
            self.reply(tasks[pos])
        except (ValueError,json.JSONDecodeError) as e: self.reply({"error":str(e)},400)
    def do_DELETE(self):
        task_id=self.route().removeprefix("/api/tasks/")
        with LOCK:
            tasks=load_tasks(); kept=[t for t in tasks if t["id"]!=task_id]
            if len(kept)==len(tasks): return self.reply({"error":"Task not found"},404)
            save_tasks(kept)
        self.reply({"deleted":task_id})

def shown(value):
    try: return datetime.fromisoformat(value.replace("Z","+00:00")).astimezone(IST).strftime("%d %b %Y, %I:%M %p IST") if value else "—"
    except ValueError: return value
class SchedulePanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=(34,27,34,30)); self.parent=parent; first_time=ist_now()+timedelta(hours=1); self.year,self.month=ist_now().year,ist_now().month; self.date=tk.StringVar(value=ist_now().strftime("%Y-%m-%d")); self.title_var=tk.StringVar(); self.notes=tk.StringVar(); self.category=tk.StringVar(value="Personal"); self.priority=tk.StringVar(value="Medium"); self.hour=tk.StringVar(value=str(int(first_time.strftime("%I")))); self.minute=tk.StringVar(value=first_time.strftime("%M")); self.period=tk.StringVar(value=first_time.strftime("%p")); self.reminder=tk.StringVar(); self.ui()
    def ui(self):
        shell=ttk.Frame(self); shell.pack(fill="both",expand=True); sidebar=ttk.Frame(shell,width=255,padding=(14,16)); sidebar.pack(side="left",fill="y"); sidebar.pack_propagate(False); ttk.Label(sidebar,text="✦  Do It",style="Heading.TLabel").pack(anchor="w",pady=(4,18)); ttk.Button(sidebar,text="＋  New task or plan",style="Accent.TButton").pack(fill="x",pady=(0,18)); ttk.Label(sidebar,text="WORKSPACE",style="Sub.TLabel").pack(anchor="w",pady=(0,7)); ttk.Button(sidebar,text="Overview",command=self.parent.show_overview).pack(fill="x"); ttk.Button(sidebar,text="Scheduled",command=self.parent.show_overview).pack(fill="x",pady=(4,0)); ttk.Label(sidebar,text="PLANNING",style="Sub.TLabel").pack(anchor="w",pady=(24,7)); ttk.Label(sidebar,text="Create your next focused plan.",style="Sub.TLabel",wraplength=210).pack(anchor="w"); ttk.Label(sidebar,text="●",style="Activity.TLabel").pack(side="bottom",anchor="w",pady=(0,8))
        outer=ttk.Frame(shell,padding=(52,42,54,36)); outer.pack(side="left",fill="both",expand=True); head=ttk.Frame(outer); head.pack(fill="x"); ttk.Button(head,text="← Back to overview",command=self.parent.show_overview).pack(side="left"); ttk.Label(head,text="Schedule a task or plan",style="Heading.TLabel").pack(side="left",padx=(16,0)); ttk.Label(head,text="IST scheduling clock · online sync",style="Sub.TLabel").pack(side="right")
        body=ttk.Frame(outer); body.pack(fill="both",expand=True,pady=(18,0)); left=ttk.Frame(body,style="Card.TFrame",padding=16); left.pack(side="left",fill="both",expand=True); ttk.Label(left,text="Selected date",style="Heading.TLabel").pack(anchor="w"); ttk.Label(left,textvariable=self.date,style="Heading.TLabel").pack(anchor="w",pady=(1,10)); self.cal=ttk.Frame(left,style="Card.TFrame"); self.cal.pack(fill="both",expand=True); self.draw_calendar()
        right=ttk.Frame(body,style="Card.TFrame",padding=16); right.pack(side="left",fill="y",padx=(16,0));
        for label,widget in (("Task",ttk.Entry(right,textvariable=self.title_var,width=29)),("Notes",ttk.Entry(right,textvariable=self.notes,width=29)),("Area",ttk.Combobox(right,textvariable=self.category,values=("Exam","Learning","Project","Personal"),state="readonly",width=26)),("Priority",ttk.Combobox(right,textvariable=self.priority,values=("High","Medium","Low"),state="readonly",width=26))): ttk.Label(right,text=label).pack(anchor="w",pady=(4,2)); widget.pack(fill="x")
        ttk.Label(right,text="Time · IST").pack(anchor="w",pady=(8,2)); picker=ttk.Frame(right,style="Card.TFrame"); picker.pack(fill="x"); ttk.Combobox(picker,textvariable=self.hour,values=tuple(str(hour) for hour in range(1,13)),state="readonly",width=5).pack(side="left"); ttk.Label(picker,text=":").pack(side="left",padx=5); ttk.Combobox(picker,textvariable=self.minute,values=tuple(f"{minute:02d}" for minute in range(60)),state="readonly",width=5).pack(side="left"); ttk.Combobox(picker,textvariable=self.period,values=("AM","PM"),state="readonly",width=5).pack(side="left",padx=(8,0)); ttk.Label(right,text="Reminder (HH:MM, optional · IST)").pack(anchor="w",pady=(8,2)); ttk.Entry(right,textvariable=self.reminder,width=29).pack(fill="x")
        ttk.Button(right,text="Schedule task",style="Accent.TButton",command=self.save).pack(fill="x",pady=(16,0))
    def draw_calendar(self):
        for w in self.cal.winfo_children(): w.destroy()
        nav=ttk.Frame(self.cal,style="Card.TFrame"); nav.grid(row=0,column=0,columnspan=7,sticky="ew",pady=(0,10)); ttk.Button(nav,text="‹",command=lambda:self.move(-1)).pack(side="left"); ttk.Label(nav,text=f"{calendar.month_name[self.month]} {self.year}",style="Heading.TLabel").pack(side="left",expand=True); ttk.Button(nav,text="›",command=lambda:self.move(1)).pack(side="right")
        for col,name in enumerate(("Mon","Tue","Wed","Thu","Fri","Sat","Sun")): ttk.Label(self.cal,text=name).grid(row=1,column=col,padx=3,pady=(0,4))
        today=ist_now().date()
        for row,week in enumerate(calendar.monthcalendar(self.year,self.month),2):
            for col,day in enumerate(week):
                if day:
                    if datetime(self.year,self.month,day).date()<today: ttk.Label(self.cal,text=str(day),style="Past.TLabel",width=3,anchor="center").grid(row=row,column=col,padx=2,pady=2)
                    else: ttk.Button(self.cal,text=str(day),width=3,command=lambda d=day:self.choose(d)).grid(row=row,column=col,padx=2,pady=2)
    def move(self,delta):
        self.month+=delta
        if self.month==13:self.year+=1;self.month=1
        if self.month==0:self.year-=1;self.month=12
        self.draw_calendar()
    def choose(self,day): self.date.set(f"{self.year:04d}-{self.month:02d}-{day:02d}")
    def save(self):
        try:
            due=ist_datetime(self.date.get(),self.hour.get(),self.minute.get(),self.period.get()).isoformat(); reminder=""
            if self.reminder.get().strip(): reminder=datetime.strptime(f"{self.date.get()} {self.reminder.get().strip()}","%Y-%m-%d %H:%M").replace(tzinfo=IST).isoformat()
            task=clean_task({"title":self.title_var.get(),"notes":self.notes.get(),"category":self.category.get(),"priority":self.priority.get(),"dueAt":due,"remindAt":reminder})
        except ValueError as e: return messagebox.showerror("Check the schedule",str(e),parent=self)
        self.parent.save_scheduled(task); self.parent.show_overview(True)
class TaskPilot(tk.Tk):
    def __init__(self):
        super().__init__(); self.title("Do It"); self.geometry("1400x900"); self.minsize(1180,780); self.configure(bg="#1E2025"); self.state("zoomed"); self.reminded=set(); self.pulse_step=0; self.current_view="overview"; self.style(); self.dark_style(); self.ui(); self.refresh(); self.after(30,lambda:dark_title_bar(self)); self.attributes("-alpha",0.0); self.fade_in(); self.pulse(); self.after(30000,self.reminders); self.after(300000,self.refresh_clock)
    def style(self):
        s=ttk.Style(self); s.theme_use("clam"); s.configure("TFrame",background="#f7f5f0"); s.configure("Card.TFrame",background="#fff"); s.configure("Title.TLabel",background="#f7f5f0",foreground="#202433",font=("Georgia",25,"bold")); s.configure("Sub.TLabel",background="#f7f5f0",foreground="#697082",font=("Segoe UI",10)); s.configure("TLabel",background="#fff",foreground="#343946",font=("Segoe UI",10)); s.configure("Heading.TLabel",background="#fff",foreground="#202433",font=("Georgia",15,"bold")); s.configure("TButton",font=("Segoe UI",10,"bold"),padding=(11,7)); s.configure("Accent.TButton",background="#315eea",foreground="white"); s.map("Accent.TButton",background=[("active","#244bc7")]); s.configure("Treeview",rowheight=33,font=("Segoe UI",10),background="white",fieldbackground="white"); s.configure("Treeview.Heading",font=("Segoe UI",10,"bold"),background="#ececf0")
    def dark_style(self):
        s=ttk.Style(self); base="#1E2025"; card="#1E2025"; input_bg="#292C33"; text="#f4f4f4"; muted="#b4b4b4"; accent="#ececec"
        s.configure("TFrame",background=base); s.configure("Card.TFrame",background=card); s.configure("Title.TLabel",background=base,foreground=text,font=("Segoe UI",24,"bold")); s.configure("Sub.TLabel",background=base,foreground=muted,font=("Segoe UI",10)); s.configure("TLabel",background=card,foreground="#e6e6e6",font=("Segoe UI",10)); s.configure("Heading.TLabel",background=card,foreground=text,font=("Segoe UI",15,"bold")); s.configure("TButton",background="#292C33",foreground=text,padding=(11,7),borderwidth=0); s.map("TButton",background=[("active","#363941")]); s.configure("Accent.TButton",background=accent,foreground="#202020"); s.map("Accent.TButton",background=[("active","#ffffff")]); s.configure("TEntry",fieldbackground=input_bg,foreground=text,insertcolor=text,bordercolor="#3A3E47",padding=8); s.configure("TCombobox",fieldbackground=input_bg,background=input_bg,foreground=text,arrowcolor=text,padding=7); s.map("TCombobox",fieldbackground=[("readonly",input_bg)],foreground=[("readonly",text)]); s.configure("Treeview",rowheight=40,font=("Segoe UI",10),background=base,fieldbackground=base,foreground="#e6e6e6",borderwidth=0); s.map("Treeview",background=[("selected","#32353E")],foreground=[("selected","#ffffff")]); s.configure("Treeview.Heading",font=("Segoe UI",10,"bold"),background=base,foreground="#b4b4b4",relief="flat"); s.map("Treeview.Heading",background=[("active","#292C33")])
        s.configure("Past.TLabel",background=base,foreground="#696969",font=("Segoe UI",10),anchor="center")
    def fade_in(self, alpha=0.0):
        alpha=min(1.0,alpha+.08); self.attributes("-alpha",alpha)
        if alpha<1.0:self.after(18,lambda:self.fade_in(alpha))
    def pulse(self):
        online=CLOCK_SOURCE=="Online IST"; shades=("#2f9e61","#54d18b","#8cf0b2","#54d18b") if online else ("#c34a4a","#e26a6a","#ff9696","#e26a6a"); ttk.Style(self).configure("Activity.TLabel",background="#1E2025",foreground=shades[self.pulse_step%len(shades)],font=("Segoe UI",15,"bold")); self.pulse_step+=1; self.after(550,self.pulse)
    def refresh_clock(self):
        threading.Thread(target=sync_ist_clock,daemon=True).start(); self.after(300000,self.refresh_clock)
    def ui(self):
        shell=ttk.Frame(self); shell.pack(fill="both",expand=True); sidebar=ttk.Frame(shell,width=255,padding=(14,16)); sidebar.pack(side="left",fill="y"); sidebar.pack_propagate(False); ttk.Label(sidebar,text="✦  Do It",style="Heading.TLabel").pack(anchor="w",pady=(4,18)); ttk.Button(sidebar,text="＋  New task or plan",style="Accent.TButton",command=self.open_scheduler).pack(fill="x",pady=(0,18)); ttk.Label(sidebar,text="WORKSPACE",style="Sub.TLabel").pack(anchor="w",pady=(0,7)); ttk.Button(sidebar,text="Overview",command=self.show_overview).pack(fill="x"); ttk.Button(sidebar,text="Scheduled",command=self.refresh).pack(fill="x",pady=(4,0)); ttk.Button(sidebar,text="Completed",command=self.show_completed).pack(fill="x",pady=(4,0)); ttk.Label(sidebar,text="RECENTS",style="Sub.TLabel").pack(anchor="w",pady=(24,7)); ttk.Label(sidebar,text="Your plans appear here as you create them.",style="Sub.TLabel",wraplength=210).pack(anchor="w"); self.activity=ttk.Label(sidebar,text="●",style="Activity.TLabel"); self.activity.pack(side="bottom",anchor="w",pady=(0,8))
        content=ttk.Frame(shell,padding=(52,42,54,36)); content.pack(side="left",fill="both",expand=True); top=ttk.Frame(content); top.pack(fill="x"); ttk.Label(top,text="Overview",style="Title.TLabel").pack(side="left"); ttk.Button(top,text="Refresh",command=self.refresh).pack(side="right"); ttk.Label(content,text="Your upcoming tasks, personal goals, and learning plans.",style="Sub.TLabel").pack(anchor="w",pady=(6,28)); right=ttk.Frame(content); right.pack(fill="both",expand=True)
        cols=("state","title","category","priority","due"); self.tree=ttk.Treeview(right,columns=cols,show="headings",selectmode="browse")
        for k,l,w in (("state","Status",90),("title","Task",260),("category","Area",100),("priority","Priority",90),("due","Due",180)): self.tree.heading(k,text=l); self.tree.column(k,width=w,anchor="w")
        self.tree.pack(fill="both",expand=True,pady=(15,13)); self.tree.bind("<Double-1>",lambda _e:self.toggle()); actions=ttk.Frame(right,style="Card.TFrame"); actions.pack(fill="x"); ttk.Button(actions,text="Mark complete / reopen",command=self.toggle).pack(side="left"); ttk.Button(actions,text="Delete selected",command=self.delete).pack(side="right"); self.status=ttk.Label(right,text="",style="Sub.TLabel"); self.status.pack(anchor="w",pady=(12,0))
    def open_scheduler(self): self.show_scheduler()
    def save_scheduled(self,task):
        with LOCK: tasks=load_tasks(); tasks.append(task); save_tasks(tasks)
    def clear_page(self):
        for child in self.winfo_children(): child.destroy()
    def transition(self, build, alpha=1.0, fading_out=True):
        if fading_out:
            alpha=max(.84,alpha-.055); self.attributes("-alpha",alpha)
            if alpha>.84: return self.after(13,lambda:self.transition(build,alpha,True))
            self.clear_page(); build(); return self.after(13,lambda:self.transition(build,alpha,False))
        alpha=min(1.0,alpha+.055); self.attributes("-alpha",alpha)
        if alpha<1.0:self.after(13,lambda:self.transition(build,alpha,False))
    def show_scheduler(self):
        if self.current_view=="scheduler": return
        def build():
            self.current_view="scheduler"; SchedulePanel(self).pack(fill="both",expand=True)
        self.transition(build)
    def show_overview(self, scheduled=False):
        if self.current_view=="overview" and not scheduled: return
        def build():
            self.current_view="overview"; self.ui(); self.refresh()
            if scheduled: self.status.configure(text="Scheduled task added.")
        self.transition(build)
    def draw_main_calendar(self):
        for w in self.cal.winfo_children(): w.destroy()
        nav=ttk.Frame(self.cal,style="Card.TFrame"); nav.grid(row=0,column=0,columnspan=7,sticky="ew",pady=(0,5)); ttk.Button(nav,text="‹",command=lambda:self.move_main(-1)).pack(side="left"); ttk.Label(nav,text=f"{calendar.month_name[self.month]} {self.year}",style="Sub.TLabel").pack(side="left",expand=True); ttk.Button(nav,text="›",command=lambda:self.move_main(1)).pack(side="right")
        for col,name in enumerate(("M","T","W","T","F","S","S")): ttk.Label(self.cal,text=name).grid(row=1,column=col,padx=2)
        for row,week in enumerate(calendar.monthcalendar(self.year,self.month),2):
            for col,day in enumerate(week):
                if day: ttk.Button(self.cal,text=str(day),width=2,command=lambda d=day:self.choose_main(d)).grid(row=row,column=col,padx=1,pady=1)
    def move_main(self,delta):
        self.month+=delta
        if self.month==13:self.year+=1;self.month=1
        if self.month==0:self.year-=1;self.month=12
        self.draw_main_calendar()
    def choose_main(self,day): self.date.set(f"{self.year:04d}-{self.month:02d}-{day:02d}")
    def parse(self,value): return datetime.strptime(value.strip(),"%Y-%m-%d %H:%M").astimezone().isoformat() if value.strip() else ""
    def add(self):
        try:
            due=datetime.strptime(f"{self.date.get()} {self.due.get().strip()}","%Y-%m-%d %H:%M").astimezone().isoformat(); reminder=""
            if self.remind.get().strip(): reminder=datetime.strptime(f"{self.date.get()} {self.remind.get().strip()}","%Y-%m-%d %H:%M").astimezone().isoformat()
            task=clean_task({"title":self.title_var.get(),"notes":self.notes.get(),"category":self.category.get(),"priority":self.priority.get(),"dueAt":due,"remindAt":reminder})
        except ValueError as e: return messagebox.showerror("Check the task",str(e),parent=self)
        with LOCK: tasks=load_tasks(); tasks.append(task); save_tasks(tasks)
        self.title_var.set(""); self.notes.set(""); self.due.set(""); self.remind.set(""); self.refresh(); self.status.configure(text="Task added.")
    def selected(self):
        ids=self.tree.selection(); return next((t for t in load_tasks() if ids and t["id"]==ids[0]),None)
    def show_completed(self): self.refresh(completed_only=True); self.status.configure(text="Completed tasks")
    def toggle(self):
        task=self.selected()
        if not task:return messagebox.showinfo("Choose a task","Select a task first.",parent=self)
        with LOCK: tasks=load_tasks(); i=next(i for i,t in enumerate(tasks) if t["id"]==task["id"]); tasks[i]=clean_task({"completed":not task["completed"]},task); save_tasks(tasks)
        self.refresh()
    def delete(self):
        task=self.selected()
        if not task:return messagebox.showinfo("Choose a task","Select a task first.",parent=self)
        if messagebox.askyesno("Delete task",f"Delete ‘{task['title']}’?",parent=self):
            with LOCK: save_tasks([t for t in load_tasks() if t["id"]!=task["id"]])
            self.refresh()
    def refresh(self, completed_only=False):
        for item in self.tree.get_children():self.tree.delete(item)
        with LOCK:tasks=load_tasks()
        if completed_only: tasks=[task for task in tasks if task["completed"]]
        for t in sorted(tasks,key=lambda x:(x["completed"],x.get("dueAt") or "9999")): self.tree.insert("","end",iid=t["id"],values=("Done" if t["completed"] else "Open",t["title"],t["category"],t["priority"],shown(t.get("dueAt",""))))
        active=sum(not t["completed"] for t in tasks); self.status.configure(text=f"{active} open task{'s' if active!=1 else ''} · API available locally")
    def reminders(self):
        with LOCK:tasks=load_tasks()
        current=datetime.now(timezone.utc); due=[]
        for t in tasks:
            try:ready=not t["completed"] and t.get("remindAt") and t["id"] not in self.reminded and datetime.fromisoformat(t["remindAt"].replace("Z","+00:00"))<=current
            except ValueError:ready=False
            if ready:due.append(t);self.reminded.add(t["id"])
        if due:messagebox.showinfo("Do It reminder","\n".join(f"• {t['title']}" for t in due),parent=self)
        self.after(30000,self.reminders)
def main():
    threading.Thread(target=sync_ist_clock,daemon=True).start(); server=ThreadingHTTPServer((HOST,PORT),Handler); threading.Thread(target=server.serve_forever,daemon=True).start(); app=TaskPilot()
    try:app.mainloop()
    finally:server.shutdown();server.server_close()
if __name__=="__main__":main()
