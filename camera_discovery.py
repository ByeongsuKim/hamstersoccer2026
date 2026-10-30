"""
카메라 자동 탐색: PC 가 연결된 네트워크의 IP 카메라와 PC 에 꽂힌 USB 카메라를 찾아 후보 목록을 만듭니다.

노트북마다 카메라 IP 가 달라질 수 있어, 주소를 몰라도 고를 수 있게 하기 위함입니다.
  IP 카메라 : 네트워크(어댑터마다 주소 254개)에서 카메라 포트가 열린 기기를 찾고, 실제로 영상이 나오는지 확인
  USB 카메라: 0~4번을 열어 보고 영상이 나오는 것만 후보로
학교·회사 네트워크에서 보안 장비에 걸리지 않도록 포트는 카메라 포트 하나만 확인합니다.
"""
import ipaddress
import socket
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import cv2
import numpy as np

CAMERA_PORTS = (9527,)
STREAM_PATH = "/videostream.cgi?loginuse=admin&loginpas=admin"
USB_INDEXES = range(5)


@dataclass
class CameraCandidate:
    source: object                 # IP 카메라 주소(str) 또는 USB 카메라 번호(int)
    label: str
    snapshot: np.ndarray | None = None
    in_use: bool = False           # 지금 앱이 쓰고 있는 카메라 (다시 열면 충돌하므로 확인하지 않음)


def stream_url(ip, port):
    return f"http://{ip}:{port}{STREAM_PATH}"


def local_networks():
    """PC 의 IPv4 네트워크 목록. 범위가 넓어도 자기 주소 주변 /24(254개)만 탐색한다."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetIPAddress -AddressFamily IPv4 | ForEach-Object { $_.IPAddress + '|' + $_.InterfaceAlias }"],
            capture_output=True, text=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        rows = [line.split("|", 1) for line in out.stdout.splitlines() if "|" in line]
    except (OSError, subprocess.SubprocessError):
        rows = [(ip, "") for ip in socket.gethostbyname_ex(socket.gethostname())[2]]
    nets = {}
    for ip, alias in rows:
        ip = ip.strip()
        if ip.startswith(("127.", "169.254.")):
            continue
        nets[ipaddress.ip_network(f"{ip}/24", strict=False)] = (ip, alias.strip())
    return nets   # {네트워크: (내 주소, 어댑터 이름)}


def _port_open(ip, port, timeout=0.4):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def grab_mjpeg_frame(url, timeout=3.0):
    """MJPEG 영상에서 JPEG 한 장을 꺼내 이미지로. 영상이 아니면 None."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = b""
            while len(data) < 3_000_000:
                chunk = resp.read(32768)
                if not chunk:
                    break
                data += chunk
                start = data.find(b"\xff\xd8")
                end = data.find(b"\xff\xd9", start + 2) if start >= 0 else -1
                if end > 0:
                    img = cv2.imdecode(np.frombuffer(data[start:end + 2], np.uint8), cv2.IMREAD_COLOR)
                    return img
    except (OSError, ValueError):
        return None
    return None


def scan_ip_cameras(current_source=None, progress=None):
    nets = local_networks()
    targets = [(str(host), port, alias) for net, (my_ip, alias) in nets.items()
               for host in net.hosts() if str(host) != my_ip for port in CAMERA_PORTS]
    if progress:
        progress(f"네트워크 {len(nets)}개에서 IP 카메라 찾는 중... ({len(targets)}곳 확인)")
    with ThreadPoolExecutor(max_workers=64) as ex:
        opened = [t for t, ok in zip(targets, ex.map(lambda t: _port_open(t[0], t[1]), targets)) if ok]

    found = []
    for ip, port, alias in opened:
        url = stream_url(ip, port)
        where = f" — {alias}" if alias else ""
        if url == current_source:
            found.append(CameraCandidate(url, f"📡 IP 카메라 {ip}:{port}{where} (지금 사용 중)", in_use=True))
            continue
        if progress:
            progress(f"{ip}:{port} 영상 확인 중...")
        img = grab_mjpeg_frame(url)
        state = "영상 확인됨" if img is not None else "포트는 열렸지만 영상 확인 실패"
        found.append(CameraCandidate(url, f"📡 IP 카메라 {ip}:{port}{where} ({state})", img))
    return found


def scan_usb_cameras(current_source=None, progress=None):
    found = []
    for i in USB_INDEXES:
        if i == current_source:
            found.append(CameraCandidate(i, f"🎥 USB 카메라 {i}번 (지금 사용 중)", in_use=True))
            continue
        if progress:
            progress(f"USB 카메라 {i}번 확인 중...")
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        try:
            if not cap.isOpened():
                continue
            img = None
            for _ in range(10):   # 켜진 직후 몇 장은 검게 나오는 카메라가 있어 여러 장 읽음
                ok, frame = cap.read()
                if ok:
                    img = frame
            if img is None:
                continue
            h, w = img.shape[:2]
            note = ", 화면이 매우 어두움" if float(img[::8, ::8].mean()) < 10 else ""
            found.append(CameraCandidate(i, f"🎥 USB 카메라 {i}번 ({w}x{h}{note})", img))
        finally:
            cap.release()
    return found


def scan_all(current_source=None, progress=None):
    return scan_ip_cameras(current_source, progress) + scan_usb_cameras(current_source, progress)
