import cv2
import cv2.aruco as aruco
import numpy as np
import json
import math
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import font, messagebox, simpledialog
from PIL import Image, ImageTk
from roboid import *

from camera_discovery import scan_all
from claude_coach import DEFAULT_MODEL, MODELS, ClaudeCoach
from soccer_ai import ROLE_NAMES, STRATEGIES, Field, Planner

APP_VERSION = "1.0.3"  # installer/HamsterSoccer.iss 의 MyAppVersion 과 맞출 것
# 설치 프로그램이 API 키를 저장하는 곳. 앱에서 바꾼 설정도 여기에 저장한다
CONFIG_PATH = Path(os.environ.get("APPDATA", Path.home())) / "HamsterSoccer" / "config.json"

DANCE_SECONDS = 3
DANCE_STEP_MS = 250
DANCE_COLORS = ["red", "yellow", "green", "sky_blue", "blue", "purple"]
DANCE_NOTES = [523, 659, 784, 1047]  # 도 미 솔 도


def load_config():
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(config):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


CAMERA_STALE_SEC = 0.5  # 새 영상이 이 시간 넘게 안 오면 카메라가 끊긴 것으로 보고 로봇을 정지
BALL_MEMORY_SEC = 0.7   # 공이 로봇에 잠깐 가려져도 이 시간 동안은 마지막 위치로 계속 제어


DEFAULT_CAMERA = "http://192.168.66.1:9527/videostream.cgi?loginuse=admin&loginpas=admin"


def camera_label(source):
    return f"USB 카메라 {source}번" if isinstance(source, int) else f"IP 카메라 ({source.split('/')[2] if '//' in source else source})"


class CameraReader(threading.Thread):
    """카메라 영상을 별도 스레드에서 계속 읽어 가장 최근 프레임만 보관한다.
    source 가 문자열이면 IP 카메라 주소, 정수면 USB 카메라 번호.
    영상 읽기가 수십 초씩 멈춰도 화면과 로봇 제어(메인 스레드)는 멈추지 않는다. 끊기면 다시 연결을 시도한다."""

    def __init__(self, source):
        super().__init__(daemon=True)
        self.url = source
        self.connected = False
        self._frame = None
        self._frame_id = 0
        self._frame_time = 0.0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._reconnect = threading.Event()

    def latest(self):
        """(프레임 번호, 프레임, 받은 시각) — 번호가 바뀌었으면 새 프레임."""
        with self._lock:
            return self._frame_id, self._frame, self._frame_time

    def reconnect(self):
        self._reconnect.set()

    def stop(self):
        self._stop_event.set()

    def run(self):
        while not self._stop_event.is_set():
            self._reconnect.clear()
            if isinstance(self.url, int):
                cap = cv2.VideoCapture(self.url, cv2.CAP_DSHOW)
            else:
                cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            while cap.isOpened() and not self._stop_event.is_set() and not self._reconnect.is_set():
                ok, frame = cap.read()
                if not ok:
                    break
                with self._lock:
                    self._frame, self._frame_time = frame, time.monotonic()
                    self._frame_id += 1
                self.connected = True
            self.connected = False
            cap.release()
            if not self._reconnect.is_set():
                self._stop_event.wait(2.0)  # 잠시 쉬었다가 다시 연결


class HamsterSoccerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"햄스터봇 AI 로봇축구 v{APP_VERSION}")
        try:
            self.root.iconbitmap(str(Path(__file__).resolve().parent / "assets" / "app.ico"))
        except tk.TclError:
            pass
        self.root.geometry("1200x850")
        self.root.minsize(1100, 750)
        self.root.configure(bg="#ffffff")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.title_font = font.Font(family="맑은 고딕", size=14, weight="bold")
        self.score_font = font.Font(family="맑은 고딕", size=28, weight="bold")
        self.btn_font = font.Font(family="맑은 고딕", size=10, weight="bold")
        self.status_font = font.Font(family="맑은 고딕", size=10, weight="bold")

        self.is_playing = False
        self.game_time_minutes = 3
        self.remaining_seconds = self.game_time_minutes * 60
        self.timer_id = None
        self.base_speed = 50
        
        self.score_ai = 0
        self.score_player = 0
        self.goal_cooldown = 0
        self.ai_goal_rect = None
        self.p_goal_rect = None
        self.defining_goal = None 
        self.drag_start = None
        
        self.detected_status = {'camera': False, 'ball': False, 'r1': False, 'r2': False}
        self.robot_marker_ids = {'r1': 1, 'r2': 0}
        self.active_mode = tk.StringVar(value="both")
        self.show_debug = tk.BooleanVar(value=False)

        # AI 전략 / Claude 감독
        self.config = load_config()
        self.strategy = tk.IntVar(value=3)
        self.use_coach = tk.BooleanVar(value=False)
        self.planner = Planner()
        model = self.config.get("model") if self.config.get("model") in MODELS else DEFAULT_MODEL
        self.coach_model = tk.StringVar(value=MODELS[model]["label"])
        self.coach = ClaudeCoach(api_key=self.config.get("api_key") or os.environ.get("ANTHROPIC_API_KEY"),
                                 model=model, interval_sec=self.config.get("coach_interval", 5))
        self.coach_seen_id = 0
        self.prev_ball = None
        self.last_orders = {}
        self.dance_job = None
        self.dance_step = 0

        self.h1, self.h2 = None, None
        try:
            self.h1 = Hamster(0)
            self.h2 = Hamster(1)
        except Exception as e:
            print("초기 연결 실패:", e)

        # 카메라: 지난번에 고른 카메라(설정에 저장)를 쓰고, 없으면 기본 IP 카메라
        self.camera_source = self.config.get("camera_source", DEFAULT_CAMERA)
        self.camera = CameraReader(self.camera_source)
        self.camera.start()
        self.camera_switching = False
        self.last_frame_id = 0
        self.camera_lost = False
        self.last_ball = None  # (x, y, r, 본 시각)

        self.ball_lower = np.array([15, 90, 90])
        self.ball_upper = np.array([45, 255, 255])
        self.clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)) 
        
        self.calibrating = False
        self.current_hsv = None
        self.disp_size = (0, 0)
        self.orig_frame_shape = (0, 0)
        self.ball_ema = None
        self.ball_lost_count = 0

        self.dict_orig = aruco.getPredefinedDictionary(aruco.DICT_ARUCO_ORIGINAL)
        try:
            self.aruco_params = aruco.DetectorParameters()
            self.is_new_cv2 = True
        except AttributeError:
            self.aruco_params = aruco.DetectorParameters_create()
            self.is_new_cv2 = False

        self.aruco_params.adaptiveThreshWinSizeMin = 3
        self.aruco_params.adaptiveThreshWinSizeMax = 33 
        self.aruco_params.adaptiveThreshWinSizeStep = 10
        self.aruco_params.minMarkerPerimeterRate = 0.015 

        if self.is_new_cv2:
            self.detector_orig = aruco.ArucoDetector(self.dict_orig, self.aruco_params)

        self.setup_ui()
        self.update_frame()

    def setup_ui(self):
        top_frame = tk.Frame(self.root, bg="white")
        top_frame.pack(fill="x", pady=10, padx=10)
        for i in range(5): top_frame.grid_columnconfigure(i, weight=1 if i==3 else 0)

        frame1 = tk.LabelFrame(top_frame, text="경기 제어", bg="white", font=self.status_font, labelanchor="nw")
        frame1.grid(row=0, column=0, sticky="ns", padx=5)
        self.btn_start = tk.Button(frame1, text="시작", bg="#7f8c8d", fg="white", font=self.btn_font, width=12, height=2, relief="raised", command=self.toggle_play)
        self.btn_start.pack(pady=5, padx=10)
        tk.Button(frame1, text="시간 설정", bg="#7f8c8d", fg="white", font=self.btn_font, width=12, relief="raised", command=self.set_time).pack(pady=2)
        tk.Button(frame1, text="점수 초기화", bg="#7f8c8d", fg="white", font=self.btn_font, width=12, relief="raised", command=self.reset_score).pack(pady=2)

        frame2 = tk.LabelFrame(top_frame, text="로봇 설정", bg="white", font=self.status_font, labelanchor="nw")
        frame2.grid(row=0, column=1, sticky="ns", padx=5)
        
        mode_frame = tk.Frame(frame2, bg="white")
        mode_frame.pack(anchor="w", padx=5)
        tk.Radiobutton(mode_frame, text="1번(ID1)만", variable=self.active_mode, value="r1", bg="white").pack(anchor="w")
        tk.Radiobutton(mode_frame, text="2번(ID0)만", variable=self.active_mode, value="r2", bg="white").pack(anchor="w")
        tk.Radiobutton(mode_frame, text="두 대 모두", variable=self.active_mode, value="both", bg="white").pack(anchor="w")
        
        tk.Button(frame2, text="속도 조절", bg="#7f8c8d", fg="white", font=self.btn_font, relief="raised", command=self.set_speed).pack(fill="x", padx=5, pady=2)
        tk.Button(frame2, text="각도 조절", bg="#7f8c8d", fg="white", font=self.btn_font, relief="raised").pack(fill="x", padx=5, pady=2)
        self.btn_calibrate = tk.Button(frame2, text="공 색상 보정(영상 클릭)", bg="#7f8c8d", fg="white", font=self.btn_font, relief="raised", command=self.start_calibration)
        self.btn_calibrate.pack(fill="x", padx=5, pady=2)
        
        tk.Label(frame2, text="골대 지정(클릭=자동인식/드래그=직접지정)", bg="white", font=("맑은 고딕", 8)).pack(pady=(2,0))
        goal_btn_frame = tk.Frame(frame2, bg="white")
        goal_btn_frame.pack(fill="x", padx=5, pady=2)
        tk.Button(goal_btn_frame, text="AI골대", bg="#7f8c8d", fg="white", width=6, command=lambda: self.set_goal_mode('ai')).pack(side="left", expand=True)
        tk.Button(goal_btn_frame, text="P골대", bg="#7f8c8d", fg="white", width=6, command=lambda: self.set_goal_mode('p')).pack(side="left", expand=True)
        tk.Button(goal_btn_frame, text="초기화", bg="#7f8c8d", fg="white", width=6, command=self.reset_goals).pack(side="left", expand=True)

        frame_ai = tk.LabelFrame(top_frame, text="AI 전략 (두 대 모두 모드)", bg="white", font=self.status_font, labelanchor="nw")
        frame_ai.grid(row=0, column=2, sticky="ns", padx=5)
        for num, name in STRATEGIES.items():
            tk.Radiobutton(frame_ai, text=f"{num}. {name}", variable=self.strategy, value=num, bg="white",
                           font=("맑은 고딕", 9)).pack(anchor="w", padx=5)
        tk.Checkbutton(frame_ai, text="🧠 Claude 감독 (전략 자동 선택)", variable=self.use_coach, bg="white",
                       font=("맑은 고딕", 9, "bold")).pack(anchor="w", padx=5, pady=(4, 0))
        coach_row = tk.Frame(frame_ai, bg="white")
        coach_row.pack(fill="x", padx=5, pady=2)
        tk.Button(coach_row, text="API 키", bg="#7f8c8d", fg="white", font=("맑은 고딕", 8), command=self.set_api_key).pack(side="left")
        tk.Button(coach_row, text="감독 주기", bg="#7f8c8d", fg="white", font=("맑은 고딕", 8), command=self.set_coach_interval).pack(side="left", padx=2)
        model_menu = tk.OptionMenu(coach_row, self.coach_model, *[m["label"] for m in MODELS.values()],
                                   command=self.set_coach_model)
        model_menu.config(font=("맑은 고딕", 8), bg="white", highlightthickness=0)
        model_menu.pack(side="left", padx=2)
        self.coach_label = tk.Label(frame_ai, text=self.coach_status_text(), bg="white", fg="#555",
                                    font=("맑은 고딕", 8), wraplength=210, justify="left", anchor="w")
        self.coach_label.pack(fill="x", padx=5, pady=(2, 4))

        frame3 = tk.Frame(top_frame, bg="#f39c12", bd=2, relief="solid")
        frame3.grid(row=0, column=3, sticky="nsew", padx=10)
        self.timer_label = tk.Label(frame3, text="남은 시간 03:00", bg="#f39c12", fg="white", font=self.title_font)
        self.timer_label.pack(pady=(15, 5))
        self.score_label = tk.Label(frame3, text="AI 0 : 0 Player", bg="#f39c12", fg="white", font=self.score_font)
        self.score_label.pack(expand=True)

        frame4 = tk.LabelFrame(top_frame, text="연결 / 인식 상태", bg="white", font=self.status_font, labelanchor="nw")
        frame4.grid(row=0, column=4, sticky="ns", padx=5)
        
        self.status_labels = {}
        status_items = [("camera", "카메라"), ("ball", "축구공(노랑)"), ("r1", "로봇 1 (ID1)"), ("r2", "로봇 2 (ID0)")]
        for key, text in status_items:
            row = tk.Frame(frame4, bg="white")
            row.pack(fill="x", padx=5, pady=1)
            tk.Label(row, text=text, bg="white", width=12, anchor="w", font=("맑은 고딕", 9)).pack(side="left")
            dot = tk.Label(row, text="● 미인식", bg="white", fg="#e74c3c", font=("맑은 고딕", 9))
            dot.pack(side="left")
            self.status_labels[key] = dot
            
        tk.Button(frame4, text="카메라 선택 / 연결", bg="#7f8c8d", fg="white", font=self.btn_font, command=self.open_camera_dialog).pack(fill="x", padx=5, pady=2)
        tk.Button(frame4, text="연결/하드웨어 점검", bg="#7f8c8d", fg="white", font=self.btn_font, command=self.check_status).pack(fill="x", padx=5, pady=2)
        
        bz_frame = tk.Frame(frame4, bg="white")
        bz_frame.pack(fill="x", padx=5, pady=2)
        tk.Button(bz_frame, text="R1(ID1) 부저", bg="#7f8c8d", fg="white", font=("맑은 고딕", 8), command=lambda: self.test_buzzer(self.h1)).pack(side="left", expand=True, padx=1)
        tk.Button(bz_frame, text="R2(ID0) 부저", bg="#7f8c8d", fg="white", font=("맑은 고딕", 8), command=lambda: self.test_buzzer(self.h2)).pack(side="left", expand=True, padx=1)
        
        map_frame = tk.Frame(frame4, bg="white")
        map_frame.pack(fill="x", padx=5, pady=2)
        tk.Button(map_frame, text="자동 매칭", bg="#7f8c8d", fg="white", font=("맑은 고딕", 8)).pack(side="left", expand=True, padx=1)
        tk.Button(map_frame, text="매핑 뒤집기", bg="#7f8c8d", fg="white", font=("맑은 고딕", 8), command=self.flip_mapping).pack(side="left", expand=True, padx=1)
        
        tk.Checkbutton(frame4, text="디버그 정보 표시", variable=self.show_debug, bg="white", font=("맑은 고딕", 9)).pack(anchor="w", padx=5)

        self.strategy_banner = tk.Label(self.root, text="", bg="#2c3e50", fg="white", anchor="w",
                                        font=("맑은 고딕", 13, "bold"), padx=12, pady=6)
        self.strategy_banner.pack(fill="x", padx=10, pady=(0, 6))

        self.video_label = tk.Label(self.root, bg="black")
        self.video_label.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        self.video_label.bind("<Button-1>", self.on_video_press)
        self.video_label.bind("<B1-Motion>", self.on_video_drag)
        self.video_label.bind("<ButtonRelease-1>", self.on_video_release)

    def test_buzzer(self, robot):
        if robot:
            robot.buzzer(1000); wait(100); robot.buzzer(0)

    def flip_mapping(self):
        self.robot_marker_ids['r1'], self.robot_marker_ids['r2'] = self.robot_marker_ids['r2'], self.robot_marker_ids['r1']
        self.status_labels['r1'].master.winfo_children()[0].config(text=f"로봇 1 (ID{self.robot_marker_ids['r1']})")
        self.status_labels['r2'].master.winfo_children()[0].config(text=f"로봇 2 (ID{self.robot_marker_ids['r2']})")
        messagebox.showinfo("매핑 뒤집기", f"1번 로봇: ID{self.robot_marker_ids['r1']}\n2번 로봇: ID{self.robot_marker_ids['r2']}\n로 변경되었습니다.")

    def set_goal_mode(self, mode):
        self.defining_goal = mode
        messagebox.showinfo("골대 지정", "영상 위에서 마우스를 드래그하여 골대 영역을 그려주세요.")

    def reset_goals(self):
        self.ai_goal_rect = None
        self.p_goal_rect = None

    def reset_score(self):
        self.score_ai = 0
        self.score_player = 0
        self.update_score_display()

    def update_score_display(self):
        self.score_label.config(text=f"AI {self.score_ai} : {self.score_player} Player")

    def switch_camera(self, source):
        """기존 카메라 연결을 완전히 끊은 뒤 새 카메라에 연결한다.
        (동시에 두 연결이 같은 카메라를 잡으면 충돌하므로, 이전 스레드가 끝나길 기다렸다가 연결)"""
        if self.camera_switching:
            return
        if source != self.camera_source and (self.ai_goal_rect or self.p_goal_rect):
            self.reset_goals()
            messagebox.showinfo("카메라 변경", "카메라가 바뀌어 화면 위치가 달라지므로 골대 지정을 초기화했습니다.\n"
                                                "연결된 뒤 AI골대·P골대를 다시 지정해 주세요.")
        old, self.camera = self.camera, None
        self.camera_source = source
        self.camera_switching = True
        self.config["camera_source"] = source
        save_config(self.config)
        self.detected_status['camera'] = False
        self.update_status_indicators()
        self.strategy_banner.config(text=f"📷 {camera_label(source)} 에 연결하는 중...", bg="#2980b9")

        def worker():
            if old:
                old.stop()
                old.join(timeout=10)  # 영상이 멈춰 있으면 읽기 제한 시간 동안 기다릴 수 있음
            new = CameraReader(source)
            new.start()
            self.last_frame_id = 0
            self.camera = new
            self.camera_switching = False

        threading.Thread(target=worker, daemon=True).start()

    def open_camera_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("카메라 선택")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        candidates = []
        results = queue.Queue()
        thumbs = {}

        tk.Label(win, text=f"현재: {camera_label(self.camera_source)}", font=("맑은 고딕", 10, "bold")).pack(anchor="w", padx=12, pady=(10, 4))

        # ① 자동 탐색 결과에서 고르기
        f_auto = tk.LabelFrame(win, text="① 찾은 카메라에서 고르기 (미리보기를 보고 선택)", padx=8, pady=6)
        f_auto.pack(fill="x", padx=12, pady=4)
        top = tk.Frame(f_auto)
        top.pack(fill="x")
        btn_scan = tk.Button(top, text="🔍 다시 찾기", font=("맑은 고딕", 9))
        btn_scan.pack(side="left")
        status = tk.Label(top, text="", fg="#555", font=("맑은 고딕", 9))
        status.pack(side="left", padx=8)
        body = tk.Frame(f_auto)
        body.pack(fill="x", pady=(6, 0))
        listbox = tk.Listbox(body, width=62, height=8, font=("맑은 고딕", 9), exportselection=False)
        listbox.pack(side="left", fill="y")
        preview = tk.Label(body, text="미리보기", width=40, height=12, bg="#222", fg="#888")
        preview.pack(side="left", padx=(8, 0))

        def show_preview(_=None):
            sel = listbox.curselection()
            if not sel:
                return
            cand = candidates[sel[0]]
            if cand.snapshot is None:
                preview.config(image="", text="지금 사용 중인 카메라" if cand.in_use else "미리보기 없음",
                               width=40, height=12)
                return
            if sel[0] not in thumbs:
                rgb = cv2.cvtColor(cand.snapshot, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(rgb)
                img.thumbnail((320, 240))
                thumbs[sel[0]] = ImageTk.PhotoImage(img)
            preview.config(image=thumbs[sel[0]], text="", width=320, height=240)

        listbox.bind("<<ListboxSelect>>", show_preview)

        def scan():
            btn_scan.config(state="disabled")
            listbox.delete(0, "end")
            candidates.clear()
            thumbs.clear()
            preview.config(image="", text="찾는 중...", width=40, height=12)
            current = self.camera_source

            def worker():
                try:
                    found = scan_all(current, progress=lambda msg: results.put(("progress", msg)))
                    results.put(("done", found))
                except Exception as e:  # 탐색이 실패해도 직접 입력으로 연결할 수 있어야 함
                    results.put(("error", str(e)))

            threading.Thread(target=worker, daemon=True).start()
            poll()

        def poll():
            if not win.winfo_exists():
                return
            while not results.empty():
                kind_, data = results.get()
                if kind_ == "progress":
                    status.config(text=data)
                elif kind_ == "error":
                    status.config(text=f"탐색 오류: {data}")
                    btn_scan.config(state="normal")
                    return
                else:
                    candidates.extend(data)
                    for cand in data:
                        listbox.insert("end", cand.label)
                    status.config(text=f"카메라 {len(data)}개를 찾았습니다." if data else
                                  "카메라를 찾지 못했습니다. 카메라 와이파이 연결을 확인하거나 ② 에 직접 입력하세요.")
                    preview.config(text="목록에서 카메라를 고르세요" if data else "")
                    if data:
                        listbox.selection_set(0)
                        show_preview()
                    btn_scan.config(state="normal")
                    return
            win.after(200, poll)

        btn_scan.config(command=scan)

        # ② 직접 입력
        is_usb = isinstance(self.camera_source, int)
        manual_url = tk.StringVar(value=DEFAULT_CAMERA if is_usb else self.camera_source)
        f_manual = tk.LabelFrame(win, text="② 직접 입력 (IP 카메라 주소 또는 USB 카메라 번호)", padx=8, pady=6)
        f_manual.pack(fill="x", padx=12, pady=4)
        tk.Entry(f_manual, textvariable=manual_url, width=80).pack(fill="x")
        tk.Label(f_manual, text="예) http://192.168.66.1:9527/videostream.cgi?loginuse=admin&loginpas=admin  또는  0",
                 fg="#555", font=("맑은 고딕", 8)).pack(anchor="w")

        def parse_manual():
            text = manual_url.get().strip()
            return int(text) if text.isdigit() else text

        def connect(source):
            if source in ("", None):
                messagebox.showerror("카메라 선택", "카메라를 고르거나 주소를 입력하세요.", parent=win)
                return
            win.destroy()
            self.switch_camera(source)

        def connect_selected():
            sel = listbox.curselection()
            if not sel:
                messagebox.showinfo("카메라 선택", "① 목록에서 카메라를 고르세요. (또는 ② 직접 입력 후 [입력한 카메라로 연결])", parent=win)
                return
            connect(candidates[sel[0]].source)

        btns = tk.Frame(win)
        btns.pack(pady=10)
        tk.Button(btns, text="선택한 카메라로 연결", bg="#27ae60", fg="white", command=connect_selected).pack(side="left", padx=4)
        tk.Button(btns, text="입력한 카메라로 연결", command=lambda: connect(parse_manual())).pack(side="left", padx=4)
        tk.Button(btns, text="취소", width=8, command=win.destroy).pack(side="left", padx=4)

        scan()  # 창을 열면 바로 자동 탐색

    def on_video_press(self, event):
        if self.calibrating: return
        if self.defining_goal:
            self.drag_start = (event.x, event.y)

    def on_video_drag(self, event):
        pass 

    def on_video_release(self, event):
        orig_h, orig_w = self.orig_frame_shape
        disp_w, disp_h = self.disp_size
        if orig_w == 0 or disp_w == 0: return

        if self.calibrating and self.current_hsv is not None:
            fx = int(event.x * orig_w / disp_w)
            fy = int(event.y * orig_h / disp_h)
            fx, fy = max(5, min(orig_w - 6, fx)), max(5, min(orig_h - 6, fy))
            patch = self.current_hsv[fy-5:fy+5, fx-5:fx+5].reshape(-1, 3)
            h_mean, s_mean, v_mean = patch.mean(axis=0)
            self.ball_lower = np.array([max(0, h_mean-10), max(50, s_mean-60), max(50, v_mean-60)])
            self.ball_upper = np.array([min(179, h_mean+10), 255, 255])
            self.calibrating = False
            self.btn_calibrate.config(bg="#7f8c8d")
            messagebox.showinfo("완료", "공 색상이 보정되었습니다.")
            
        elif self.defining_goal and self.drag_start:
            x1, y1 = self.drag_start
            x2, y2 = event.x, event.y
            fx1, fy1 = int(x1 * orig_w / disp_w), int(y1 * orig_h / disp_h)
            fx2, fy2 = int(x2 * orig_w / disp_w), int(y2 * orig_h / disp_h)
            
            rect = (min(fx1, fx2), min(fy1, fy2), abs(fx1-fx2), abs(fy1-fy2))
            if rect[2] > 20 and rect[3] > 20: 
                if self.defining_goal == 'ai': self.ai_goal_rect = rect
                elif self.defining_goal == 'p': self.p_goal_rect = rect
            self.defining_goal = None
            self.drag_start = None

    def start_calibration(self):
        self.calibrating = True
        self.btn_calibrate.config(bg="#e67e22")

    def set_speed(self):
        val = simpledialog.askinteger("속도 조절", "직진 속도 (10~100):", initialvalue=self.base_speed)
        if val: self.base_speed = val

    def coach_status_text(self):
        if not self.coach.api_key:
            return "감독: API 키 없음 ([API 키]로 입력)"
        usage = f"\n누적 {self.coach.calls}회 · 약 ${self.coach.cost_usd():.4f}" if self.coach.calls else ""
        if self.coach.error:
            return f"감독: ⚠️ {self.coach.error}{usage}"
        if self.coach.decision:
            d = self.coach.decision
            return f"감독: 전략 {d.strategy} — {d.reason}{usage}"
        return f"감독: 대기 중 ({self.coach.interval_sec:.0f}초마다 판단){usage}"

    def set_api_key(self):
        key = simpledialog.askstring("Claude API 키", "Anthropic API 키를 입력하세요\n(이 PC의 사용자 설정에 저장됩니다):", show="*")
        if key:
            self.coach.set_api_key(key.strip())
            self.config["api_key"] = key.strip()
            save_config(self.config)
            self.coach_label.config(text=self.coach_status_text())

    def set_coach_interval(self):
        val = simpledialog.askinteger("감독 주기", "몇 초마다 Claude 감독에게 물어볼까요? (3~60)",
                                      initialvalue=int(self.coach.interval_sec), minvalue=3, maxvalue=60)
        if val:
            self.coach.interval_sec = val
            self.config["coach_interval"] = val
            save_config(self.config)
            self.coach_label.config(text=self.coach_status_text())

    def set_coach_model(self, label):
        model = next(k for k, m in MODELS.items() if m["label"] == label)
        self.coach.model = model
        self.config["model"] = model
        save_config(self.config)

    def update_strategy_banner(self):
        num = self.strategy.get()
        how = "🧠 Claude 감독이 선택" if self.use_coach.get() else "수동 선택"
        text = f"현재 AI 로봇 전략:  {num}. {STRATEGIES[num]}   ({how})"
        if self.dance_job:
            text = "🎉 골인!  로봇들이 세리머니 춤을 추는 중..."
        elif self.active_mode.get() != "both":
            text = f"현재 AI 로봇 전략:  한 대만 공격 ({'로봇 1' if self.active_mode.get() == 'r1' else '로봇 2'})"
        elif self.is_playing and self.last_orders:
            names = {"r1": f"로봇1(ID{self.robot_marker_ids['r1']})", "r2": f"로봇2(ID{self.robot_marker_ids['r2']})"}
            roles = "   ".join(f"{names[k]}: {ROLE_NAMES[o.role]}" for k, o in sorted(self.last_orders.items()))
            text += f"     ▶ {roles}"
        elif not self.is_playing:
            text += "     (경기 대기 중)"
        if self.use_coach.get() and self.coach.decision and not self.dance_job:
            text += f"\n감독 한마디: {self.coach.decision.reason}"
        self.strategy_banner.config(text=text, bg="#8e44ad" if self.dance_job else "#2c3e50")

    def start_dance(self):
        """골인 세리머니: 제자리에서 좌우로 흔들며 LED 색을 바꾸고 소리를 낸다 (3초)."""
        if self.dance_job:
            self.root.after_cancel(self.dance_job)
        self.dance_step = 0
        self._dance()

    def _dance(self):
        total = DANCE_SECONDS * 1000 // DANCE_STEP_MS
        if self.dance_step >= total or not self.is_playing:
            self.stop_dance()
            return
        i = self.dance_step
        speed = 60 if i % 2 == 0 else -60
        for n, robot in enumerate((self.h1, self.h2)):
            if robot is None: continue
            robot.wheels(speed, -speed)
            robot.leds(DANCE_COLORS[(i + n * 3) % len(DANCE_COLORS)])
            robot.buzzer(DANCE_NOTES[(i + n) % len(DANCE_NOTES)])
        self.dance_step += 1
        self.dance_job = self.root.after(DANCE_STEP_MS, self._dance)

    def stop_dance(self):
        if self.dance_job:
            self.root.after_cancel(self.dance_job)
        self.dance_job = None
        for robot in (self.h1, self.h2):
            if robot is None: continue
            robot.wheels(0, 0)
            robot.leds("off")
            robot.buzzer(0)

    def game_state(self, ball, robots, frame_w, frame_h):
        """감독에게 보낼 경기 상황 (경기장 크기로 나눈 0~1 좌표)."""
        def norm(x, y):
            return {"x": round(x / frame_w, 2), "y": round(y / frame_h, 2)}

        state = {
            "남은시간_초": self.remaining_seconds,
            "점수": {"AI": self.score_ai, "상대": self.score_player},
            "공": norm(*ball),
            "현재전략": self.strategy.get(),
            "로봇": {k: norm(r[0], r[1]) for k, r in robots.items()},
        }
        if self.prev_ball:
            dx, dy = ball[0] - self.prev_ball[0], ball[1] - self.prev_ball[1]
            state["공_이동"] = "상대 골대 쪽" if dx > 3 else ("우리 골대 쪽" if dx < -3 else "거의 정지")
        return state

    def apply_coach_decision(self):
        if self.coach.decision_id != self.coach_seen_id and self.coach.decision:
            self.coach_seen_id = self.coach.decision_id
            if self.use_coach.get():
                self.strategy.set(self.coach.decision.strategy)
        self.coach_label.config(text=self.coach_status_text())

    def set_time(self):
        if self.is_playing: return
        val = simpledialog.askinteger("시간 설정", "경기 분:", initialvalue=self.game_time_minutes)
        if val:
            self.game_time_minutes = val
            self.remaining_seconds = val * 60
            self.update_timer_display()

    def update_timer_display(self):
        mins, secs = divmod(self.remaining_seconds, 60)
        self.timer_label.config(text=f"남은 시간 {mins:02d}:{secs:02d}")

    def update_status_indicators(self):
        for key, label in self.status_labels.items():
            ok = self.detected_status.get(key, False)
            label.config(text="● 연결됨" if ok and key=='camera' else ("● 인식됨" if ok else "● 미인식"), 
                         fg="#2ecc71" if ok else "#e74c3c")

    def check_status(self):
        hw = "정상" if (self.h1 and self.h2) else "실패"
        if self.h1: self.test_buzzer(self.h1)
        if self.h2: self.test_buzzer(self.h2)
        messagebox.showinfo("점검", f"로봇 하드웨어: {hw}")

    def toggle_play(self):
        if self.remaining_seconds <= 0: return
        self.is_playing = not self.is_playing
        if self.is_playing:
            self.btn_start.config(text="정지", bg="#e74c3c")
            self.countdown()
        else:
            self.btn_start.config(text="시작", bg="#7f8c8d")
            if self.timer_id: self.root.after_cancel(self.timer_id)
            self.stop_dance()
            if self.h1: self.h1.stop()
            if self.h2: self.h2.stop()

    def countdown(self):
        if self.is_playing and self.remaining_seconds > 0:
            self.remaining_seconds -= 1
            self.update_timer_display()
            self.timer_id = self.root.after(1000, self.countdown)
        elif self.remaining_seconds <= 0:
            self.toggle_play()

    def move_robot_to_target(self, robot, rx, ry, rangle, tx, ty, is_attacker=True):
        dx = tx - rx
        dy = ty - ry
        
        # [핵심] 수비 로봇이 목표 위치(방어선) 근처에 도착하면 모터를 완전히 정지시켜 맴돌기(자책골) 차단
        if not is_attacker and math.hypot(dx, dy) < 40:
            robot.wheels(0, 0)
            return

        target_angle = math.degrees(math.atan2(dy, dx))
        angle_diff = target_angle - rangle

        while angle_diff > 180: angle_diff -= 360
        while angle_diff < -180: angle_diff += 360

        speed = self.base_speed if is_attacker else int(self.base_speed * 0.7)

        if abs(angle_diff) > 25:
            turn_speed = int(angle_diff * 0.4)
            left_wheel = max(-100, min(100, turn_speed))
            right_wheel = max(-100, min(100, -turn_speed))
            robot.wheels(left_wheel, right_wheel)
        else:
            fine_turn = int(angle_diff * 0.3)
            left_wheel = max(-100, min(100, speed + fine_turn))
            right_wheel = max(-100, min(100, speed - fine_turn))
            robot.wheels(left_wheel, right_wheel)

    def detect_ball(self, frame):
        blurred = cv2.GaussianBlur(frame, (5, 5), 0)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
        self.current_hsv = hsv

        mask = cv2.inRange(hsv, self.ball_lower, self.ball_upper)
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        green = cv2.inRange(hsv, np.array([35, 40, 40]), np.array([90, 255, 255]))  # 경기장 잔디색

        # 노란색 덩어리 중 '동그랗고, 원을 꽉 채우고, 둘레가 잔디색'인 것만 공으로 인정
        # (경기장 밖 나무 판자처럼 색만 비슷한 물체를 걸러냄)
        # 단, 골대 안은 바닥이 잔디색이 아니므로 지정한 골대 영역(여유 20px) 안에서는 잔디색 조건을 빼고 찾는다
        goals = [r for r in (getattr(self, "ai_goal_rect", None), getattr(self, "p_goal_rect", None)) if r]

        def in_goal(x, y, pad=20):
            return any(gx - pad <= x <= gx + gw + pad and gy - pad <= y <= gy + gh + pad for gx, gy, gw, gh in goals)

        best, best_area = None, -1
        for c in contours:
            area = cv2.contourArea(c)
            if area < 40 or area <= best_area:
                continue
            (bx, by), radius = cv2.minEnclosingCircle(c)
            perimeter = cv2.arcLength(c, True)
            circularity = 4 * math.pi * area / (perimeter * perimeter) if perimeter else 0
            fill = area / (math.pi * radius * radius) if radius else 0
            if circularity < 0.65 or fill < 0.6:
                continue
            if not in_goal(bx, by):
                ring = np.zeros(mask.shape, np.uint8)
                cv2.circle(ring, (int(bx), int(by)), int(radius * 2.2), 255, -1)
                cv2.circle(ring, (int(bx), int(by)), int(radius * 1.3), 0, -1)
                green_ratio = cv2.countNonZero(cv2.bitwise_and(green, ring)) / max(1, cv2.countNonZero(ring))
                if green_ratio < 0.3:
                    continue
            best, best_area = (int(bx), int(by), int(radius)), area

        self.detected_status['ball'] = best is not None
        return best if best else (-1, -1, 0)

    def update_frame(self):
        camera = self.camera  # 카메라를 바꾸는 중에는 None
        frame_id, frame, frame_time = camera.latest() if camera else (0, None, 0.0)
        ret = frame is not None and frame_id != self.last_frame_id  # 새 프레임만 처리
        if ret:
            self.last_frame_id = frame_id
            self.camera_lost = False
            self.detected_status['camera'] = True
            frame_h, frame_w = frame.shape[:2]
            self.orig_frame_shape = (frame_h, frame_w)
            
            # 인식은 카메라 원본(raw)으로, 공 원·마커·골대 표시는 화면용 복사본(frame)에만 그린다
            raw = frame
            frame = raw.copy()

            # 1. 공 인식
            ball_x, ball_y, ball_r = self.detect_ball(raw)
            if ball_x != -1:
                self.last_ball = (ball_x, ball_y, ball_r, time.monotonic())
                cv2.circle(frame, (ball_x, ball_y), ball_r, (0, 255, 255), 2)

            # 로봇이 공을 밀면서 잠깐 가려도 멈추지 않도록, 0.7초 안에 본 공의 마지막 위치로 계속 제어
            # (득점 판정은 실제로 보이는 공으로만 한다)
            ctrl_ball = (ball_x, ball_y)
            if ball_x == -1 and self.last_ball and time.monotonic() - self.last_ball[3] < BALL_MEMORY_SEC:
                ctrl_ball = self.last_ball[:2]
                cv2.circle(frame, ctrl_ball, self.last_ball[2], (0, 200, 255), 1)

            # 2. 마커 인식
            gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
            
            if self.is_new_cv2:
                corners, ids, rej = self.detector_orig.detectMarkers(gray)
            else:
                corners, ids, rej = aruco.detectMarkers(gray, self.dict_orig, parameters=self.aruco_params)
                
            if self.show_debug.get():
                if len(rej) > 0:
                    aruco.drawDetectedMarkers(frame, rej, borderColor=(0, 0, 255)) 

            r1_data, r2_data = None, None
            self.detected_status['r1'] = False
            self.detected_status['r2'] = False

            if ids is not None:
                for i, marker_id in enumerate(ids.flatten()):
                    c = corners[i][0]
                    cx, cy = int(np.mean(c[:, 0])), int(np.mean(c[:, 1]))
                    fx, fy = (c[0][0] + c[1][0]) / 2.0, (c[0][1] + c[1][1]) / 2.0
                    angle = math.degrees(math.atan2(fy - cy, fx - cx))

                    cv2.polylines(frame, [c.astype(np.int32)], True, (0, 255, 0), 2)
                    cv2.arrowedLine(frame, (cx, cy), (int(fx), int(fy)), (0, 0, 255), 3, tipLength=0.3)
                    cv2.putText(frame, f"ID:{marker_id}", (cx-10, cy+30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)

                    if marker_id == self.robot_marker_ids['r1']:
                        r1_data = (cx, cy, angle)
                        self.detected_status['r1'] = True
                    elif marker_id == self.robot_marker_ids['r2']:
                        r2_data = (cx, cy, angle)
                        self.detected_status['r2'] = True

            # 3. 골대 렌더링 및 자동 채점
            if self.ai_goal_rect:
                x, y, w, h = self.ai_goal_rect
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 0, 255), 2)
                cv2.putText(frame, "AI", (x, y-5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            if self.p_goal_rect:
                x, y, w, h = self.p_goal_rect
                cv2.rectangle(frame, (x, y), (x+w, y+h), (255, 0, 0), 2)
                cv2.putText(frame, "Player", (x, y-5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)

            if self.is_playing and ball_x != -1 and self.goal_cooldown == 0:
                # 공 전체(원 테두리까지)가 골대 사각형 안에 들어가야 골인
                def ball_fully_inside(rect):
                    x, y, w, h = rect
                    return (x <= ball_x - ball_r and ball_x + ball_r <= x + w
                            and y <= ball_y - ball_r and ball_y + ball_r <= y + h)

                if self.ai_goal_rect and ball_fully_inside(self.ai_goal_rect):
                    self.score_player += 1; self.update_score_display(); self.goal_cooldown = 150
                    self.start_dance()
                elif self.p_goal_rect and ball_fully_inside(self.p_goal_rect):
                    self.score_ai += 1; self.update_score_display(); self.goal_cooldown = 150
                    self.start_dance()
            elif self.goal_cooldown > 0:
                self.goal_cooldown -= 1
                cv2.putText(frame, "GOAL!", (frame_w//2 - 100, frame_h//2), cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 255, 255), 5)

            # 4. AI 전략에 따라 로봇 이동 (화면에 안 보이거나 명령이 없는 로봇은 정지)
            if self.is_playing and ctrl_ball[0] != -1 and self.goal_cooldown == 0:
                mode = self.active_mode.get()
                robots = {}
                if mode in ("r1", "both") and r1_data: robots['r1'] = r1_data
                if mode in ("r2", "both") and r2_data: robots['r2'] = r2_data
                field = Field(frame_w, frame_h, self.ai_goal_rect, self.p_goal_rect)
                orders = self.planner.plan(self.strategy.get(), robots, ctrl_ball, field)
                self.last_orders = orders

                for key, robot in (('r1', self.h1), ('r2', self.h2)):
                    if robot is None: continue
                    order = orders.get(key)
                    if order is None:
                        robot.wheels(0, 0)
                        continue
                    rx, ry, rangle = robots[key]
                    tx, ty = order.target
                    self.move_robot_to_target(robot, rx, ry, rangle, tx, ty, is_attacker=order.is_attacker)
                    color = (255, 255, 0) if order.is_attacker else (0, 255, 255)
                    cv2.putText(frame, order.role.upper(), (int(rx) - 25, int(ry) - 22),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                    if self.show_debug.get():
                        cv2.line(frame, (int(rx), int(ry)), (tx, ty), color, 1)
                        cv2.circle(frame, (tx, ty), 5, color, -1)

                if self.use_coach.get() and mode == "both":
                    self.coach.maybe_request(self.game_state(ctrl_ball, robots, frame_w, frame_h))
            elif not self.dance_job:  # 세리머니 중에는 춤 동작이 바퀴를 움직임
                self.last_orders = {}
                if self.h1: self.h1.wheels(0, 0)
                if self.h2: self.h2.wheels(0, 0)
            if ball_x != -1:
                self.prev_ball = (ball_x, ball_y)
            self.apply_coach_decision()
            self.update_strategy_banner()

            self.update_status_indicators()
            win_w, win_h = self.video_label.winfo_width(), self.video_label.winfo_height()
            self.disp_size = (win_w, win_h) if win_w > 50 else (800, 450)
            
            img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(img_rgb).resize(self.disp_size, Image.LANCZOS)
            imgtk = ImageTk.PhotoImage(image=pil_img)
            self.video_label.imgtk = imgtk
            self.video_label.configure(image=imgtk)
        elif time.monotonic() - frame_time > CAMERA_STALE_SEC:
            # 영상이 끊기면 로봇이 마지막 명령대로 계속 달리지 않도록 즉시 정지 (세리머니 춤은 제자리라 예외)
            if not self.dance_job:
                if self.h1: self.h1.wheels(0, 0)
                if self.h2: self.h2.wheels(0, 0)
            if not self.camera_lost:
                self.camera_lost = True
                self.last_orders = {}
                self.detected_status.update(camera=False, ball=False, r1=False, r2=False)
                self.update_status_indicators()
                if not self.camera_switching:  # 카메라를 바꾸는 중이면 '연결 중' 안내를 그대로 둔다
                    self.strategy_banner.config(
                        text=f"⚠️ {camera_label(self.camera_source)} 영상이 없습니다 — 로봇 정지 (재연결 중 · "
                             "카메라 IP 가 바뀌었다면 [카메라 선택 / 연결]에서 자동 탐색)",
                        bg="#c0392b")

        self.root.after(15, self.update_frame)

    def on_closing(self):
        self.is_playing = False
        try:
            self.stop_dance()
            if self.h1: self.h1.stop()
            if self.h2: self.h2.stop()
            wait(100)
        except: pass
        if self.camera:
            self.camera.stop()
        self.root.destroy()

def redirect_output_to_log():
    """설치판(콘솔 없는 exe)에는 sys.stdout 이 없어 roboid 가 연결 메시지를 쓰다 실패하고 로봇 연결이 끊긴다.
    출력을 %APPDATA%\\HamsterSoccer\\app.log 로 보내 연결을 살리고, 문제가 생기면 로그로 확인할 수 있게 한다."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log = open(CONFIG_PATH.parent / "app.log", "w", encoding="utf-8", buffering=1)
    log.write(f"햄스터봇 AI 로봇축구 v{APP_VERSION} 시작\n")
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log


if __name__ == "__main__":
    redirect_output_to_log()
    root = tk.Tk()
    app = HamsterSoccerApp(root)
    root.mainloop()