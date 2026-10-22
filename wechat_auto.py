#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""晚安成电 · 微信小程序自动签到助手（Windows，零第三方依赖）

思路：先用录制模式把「打开微信小程序 -> 晚安成电 -> 签到」的点击过程录下来，
之后每晚由计划任务回放同样的点击。点击坐标按窗口客户区的相对位置保存，
因此窗口被移动或缩放后仍然可用。

命令：
  py -3 wechat_auto.py list            列出当前可见窗口（排查用）
  py -3 wechat_auto.py record          录制签到流程（F9 开始 / F10 结束）
  py -3 wechat_auto.py test            试运行：只计算点击位置，不真正点击
  py -3 wechat_auto.py run             执行签到（计划任务调用这个）
  py -3 wechat_auto.py shot [文件]      截屏（PNG）
  py -3 wechat_auto.py selftest        自检：鼠标 / 键盘 / 截图
"""

from __future__ import annotations

import argparse
import ctypes
import difflib
import getpass
import json
import logging
import os
import smtplib
import ssl
import struct
import subprocess
import sys
import time
import zlib
from ctypes import wintypes
from datetime import datetime
from email.message import EmailMessage

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
STEPS_PATH = os.path.join(APP_DIR, "steps.json")
STATE_PATH = os.path.join(APP_DIR, "state.json")
EMAIL_STATE_PATH = os.path.join(APP_DIR, "email_state.json")
LOG_DIR = os.path.join(APP_DIR, "logs")

VK_LBUTTON = 0x01
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_F7 = 0x76
VK_F9 = 0x78
VK_F10 = 0x79

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL
user32.SetActiveWindow.argtypes = [wintypes.HWND]
user32.SetActiveWindow.restype = wintypes.HWND
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
user32.GetLastInputInfo.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
kernel32.GetTickCount.restype = wintypes.DWORD
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.restype = wintypes.HGLOBAL
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                            ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.restype = wintypes.BOOL
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.CloseClipboard.restype = wintypes.BOOL

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

try:
    user32.MessageBoxTimeoutW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                          wintypes.UINT, wintypes.WORD, wintypes.DWORD]
    user32.MessageBoxTimeoutW.restype = ctypes.c_int
    HAS_MSGBOXTIMEOUT = True
except AttributeError:  # pragma: no cover
    HAS_MSGBOXTIMEOUT = False


class SignError(RuntimeError):
    pass


LOG = logging.getLogger("wanan")


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def enable_dpi_awareness() -> None:
    """必须在任何窗口/坐标操作之前调用，否则高 DPI 下点击会偏移。"""
    try:
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def virtual_screen() -> tuple[int, int, int, int]:
    return (user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
            user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
            user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
            user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))


def get_window_text(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def get_class_name(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def get_process_name(hwnd) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(handle)
    return ""


def window_rect(hwnd) -> tuple[int, int, int, int]:
    rc = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))
    return rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top


def client_rect(hwnd) -> tuple[int, int, int, int]:
    rc = RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    pt = POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, rc.right - rc.left, rc.bottom - rc.top


def list_windows(include_hidden: bool = False) -> list[dict]:
    windows: list[dict] = []

    @WNDENUMPROC
    def _callback(hwnd, _lparam):
        if not include_hidden and not user32.IsWindowVisible(hwnd):
            return True
        title = get_window_text(hwnd)
        if not title.strip():
            return True
        left, top, width, height = window_rect(hwnd)
        windows.append({
            "hwnd": int(hwnd),
            "title": title,
            "class": get_class_name(hwnd),
            "process": get_process_name(hwnd),
            "rect": [left, top, width, height],
            "minimized": bool(user32.IsIconic(hwnd)),
        })
        return True

    user32.EnumWindows(_callback, 0)
    return windows


def activate_window(hwnd) -> bool:
    if not hwnd:
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    else:
        user32.ShowWindow(hwnd, 5)  # SW_SHOW

    if user32.GetForegroundWindow() == hwnd:
        return True

    current_tid = kernel32.GetCurrentThreadId()
    foreground = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(foreground, None)
    attached = False
    try:
        if fg_tid and fg_tid != current_tid:
            attached = bool(user32.AttachThreadInput(current_tid, fg_tid, True))
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(current_tid, fg_tid, False)

    # 经典技巧：模拟一次 ALT 抬起，绕开前台窗口锁定
    _send_key(VK_MENU, up=True)
    time.sleep(0.08)
    return user32.GetForegroundWindow() == hwnd


def get_cursor_pos() -> tuple[int, int]:
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def is_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def idle_seconds() -> float:
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return 9999.0
    return ((kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF) / 1000.0


# --------------------------------------------------------------------------- #
# 鼠标 / 键盘
# --------------------------------------------------------------------------- #
def _send_input(inp: INPUT) -> None:
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _mouse_input(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> None:
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, None)
    _send_input(inp)


def _send_key(vk: int, up: bool = False) -> None:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, None)
    _send_input(inp)


def send_key(key: str) -> None:
    """支持 enter / esc / tab / space / 方向键 / 单字符。"""
    names = {
        "enter": VK_RETURN, "return": VK_RETURN, "esc": VK_ESCAPE, "escape": VK_ESCAPE,
        "tab": 0x09, "space": 0x20, "backspace": 0x08, "delete": 0x2E,
        "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    }
    vk = names.get(key.lower())
    if vk is None:
        if len(key) == 1:
            send_text(key)
            return
        raise SignError(f"不支持的按键: {key}")
    _send_key(vk, up=False)
    time.sleep(0.02)
    _send_key(vk, up=True)


def send_text(text: str) -> None:
    """直接以 Unicode 方式输入，不经过输入法。"""
    for ch in text:
        for unit in _utf16_units(ch):
            inp = INPUT()
            inp.type = INPUT_KEYBOARD
            inp.ki = KEYBDINPUT(0, unit, KEYEVENTF_UNICODE, 0, None)
            _send_input(inp)
            inp2 = INPUT()
            inp2.type = INPUT_KEYBOARD
            inp2.ki = KEYBDINPUT(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)
            _send_input(inp2)
        time.sleep(0.005)


def _utf16_units(ch: str) -> list[int]:
    data = ch.encode("utf-16-le")
    return [data[i] | (data[i + 1] << 8) for i in range(0, len(data), 2)]


def send_ctrl_v() -> None:
    _send_key(VK_CONTROL, up=False)
    time.sleep(0.02)
    _send_key(0x56, up=False)  # V
    time.sleep(0.02)
    _send_key(0x56, up=True)
    time.sleep(0.02)
    _send_key(VK_CONTROL, up=True)


def click_at(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.06)
    _mouse_input(MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.04)
    _mouse_input(MOUSEEVENTF_LEFTUP)
    time.sleep(0.06)


def mouse_wheel(clicks: int) -> None:
    _mouse_input(MOUSEEVENTF_WHEEL, data=int(clicks) * 120)


def set_clipboard_text(text: str) -> None:
    for _ in range(10):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise SignError("无法打开剪贴板")
    try:
        user32.EmptyClipboard()
        data = text.encode("utf-16-le") + b"\x00\x00"
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise SignError("剪贴板内存分配失败")
        ptr = kernel32.GlobalLock(handle)
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            raise SignError("写入剪贴板失败")
    finally:
        user32.CloseClipboard()


def get_clipboard_text() -> str:
    for _ in range(10):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


# --------------------------------------------------------------------------- #
# 截图（GDI）与 PNG 编码，不依赖 Pillow
# --------------------------------------------------------------------------- #
class ScreenImage:
    def __init__(self, width: int, height: int, rgb: bytes, origin: tuple[int, int]):
        self.width = width
        self.height = height
        self.rgb = rgb
        self.origin = origin

    def sample(self, step: int = 8) -> list[int]:
        """按步长抽样得到灰度序列，用来粗略比较两张截图。"""
        values = []
        stride = self.width * 3
        for y in range(0, self.height, step):
            row = y * stride
            for x in range(0, self.width * 3, step * 3):
                i = row + x
                values.append((self.rgb[i] * 299 + self.rgb[i + 1] * 587 + self.rgb[i + 2] * 114) // 1000)
        return values


def grab_rect(x: int, y: int, width: int, height: int) -> ScreenImage:
    """只截取屏幕上的一块区域，比全屏截图省时省 CPU。"""
    if width <= 0 or height <= 0:
        raise SignError("截图区域尺寸无效")
    screen_dc = user32.GetDC(None)
    if not screen_dc:
        raise SignError("获取屏幕 DC 失败")
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    if not mem_dc or not bitmap:
        raise SignError("创建截图缓冲区失败")
    old = gdi32.SelectObject(mem_dc, bitmap)
    try:
        if not gdi32.BitBlt(mem_dc, 0, 0, width, height, screen_dc, x, y, SRCCOPY):
            raise SignError("截图失败（BitBlt）")
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height  # 负数表示自上而下
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0
        buffer = ctypes.create_string_buffer(width * height * 4)
        if not gdi32.GetDIBits(mem_dc, bitmap, 0, height, buffer,
                               ctypes.byref(bmi), DIB_RGB_COLORS):
            raise SignError("读取截图像素失败")
    finally:
        if old:
            gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)

    bgra = buffer.raw
    rgb = bytearray(width * height * 3)
    rgb[0::3] = bgra[2::4]
    rgb[1::3] = bgra[1::4]
    rgb[2::3] = bgra[0::4]
    return ScreenImage(width, height, bytes(rgb), (x, y))


def grab_screen() -> ScreenImage:
    vx, vy, vw, vh = virtual_screen()
    if vw <= 0 or vh <= 0:
        raise SignError("无法获取屏幕尺寸")
    return grab_rect(vx, vy, vw, vh)


def capture_client(win: dict) -> ScreenImage:
    left, top, width, height = client_rect(win["hwnd"])
    return grab_rect(left, top, width, height)


def crop_image(image: ScreenImage, x: int, y: int, width: int, height: int) -> ScreenImage:
    x = max(0, min(int(x), image.width - 1))
    y = max(0, min(int(y), image.height - 1))
    width = max(1, min(int(width), image.width - x))
    height = max(1, min(int(height), image.height - y))
    stride = image.width * 3
    out = bytearray()
    for row_index in range(y, y + height):
        base = row_index * stride
        out += image.rgb[base + x * 3: base + (x + width) * 3]
    return ScreenImage(width, height, bytes(out), (image.origin[0] + x, image.origin[1] + y))


def encode_png(image: ScreenImage) -> bytes:
    stride = image.width * 3
    raw = bytearray()
    for y in range(image.height):
        raw.append(0)  # filter type 0
        raw += image.rgb[y * stride:(y + 1) * stride]

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload +
                struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", image.width, image.height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) +
            chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


def downscale(image: ScreenImage, factor: int) -> ScreenImage:
    """按整数倍抽样缩小，保存日志截图时省空间。"""
    factor = max(1, int(factor))
    if factor == 1:
        return image
    width = image.width // factor
    height = image.height // factor
    stride = image.width * 3
    out = bytearray()
    for y in range(0, height * factor, factor):
        row = image.rgb[y * stride:(y + 1) * stride]
        red = row[0::factor * 3]
        green = row[1::factor * 3]
        blue = row[2::factor * 3]
        line = bytearray(len(red) * 3)
        line[0::3] = red
        line[1::3] = green
        line[2::3] = blue
        out += line
    return ScreenImage(width, height, bytes(out), image.origin)


def save_screenshot(path: str, scale: int = 2) -> str:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    image = downscale(grab_screen(), scale)
    with open(path, "wb") as fh:
        fh.write(encode_png(image))
    return path


def screen_diff(before: ScreenImage, after: ScreenImage) -> float:
    if (before.width, before.height) != (after.width, after.height):
        return 999.0
    a = before.sample()
    b = after.sample()
    if not a or len(a) != len(b):
        return 0.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


# --------------------------------------------------------------------------- #
# OCR：按文字找位置（Windows 自带 OCR，用于界面位置漂移时兜底）
# --------------------------------------------------------------------------- #
CREATE_NO_WINDOW = 0x08000000
OCR_SCRIPT = os.path.join(APP_DIR, "ocr.ps1")


def ocr_lines(image: ScreenImage) -> list[dict]:
    if not os.path.exists(OCR_SCRIPT):
        return []
    os.makedirs(LOG_DIR, exist_ok=True)
    png_path = os.path.join(LOG_DIR, "ocr-input.png")
    json_path = os.path.join(LOG_DIR, "ocr-output.json")
    with open(png_path, "wb") as fh:
        fh.write(encode_png(image))
    if os.path.exists(json_path):
        try:
            os.remove(json_path)
        except OSError:
            pass
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", OCR_SCRIPT, "-Path", png_path, "-Out", json_path],
                       capture_output=True, timeout=45, creationflags=CREATE_NO_WINDOW)
    except Exception as exc:
        LOG.warning("OCR 调用失败：%s", exc)
        return []
    try:
        with open(json_path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    lines = []
    for item in data:
        words = item.get("words") or []
        if not words:
            continue
        text = "".join(str(word.get("t", "")) for word in words)
        xs = [float(word["x"]) for word in words]
        ys = [float(word["y"]) for word in words]
        xes = [float(word["x"]) + float(word["w"]) for word in words]
        yes = [float(word["y"]) + float(word["h"]) for word in words]
        lines.append({"text": text, "x": min(xs), "y": min(ys),
                      "w": max(xes) - min(xs), "h": max(yes) - min(ys)})
    return lines


def _similar(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if b in a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def find_text_lines(win: dict, text: str, threshold: float = 0.55) -> list[dict]:
    """返回窗口内所有和 text 相似的文字行（屏幕坐标）。"""
    lines = ocr_lines(capture_client(win))
    left, top, _, _ = client_rect(win["hwnd"])
    hits = []
    for line in lines:
        ratio = _similar(line["text"], text)
        if ratio >= threshold:
            hits.append({"x": left + int(line["x"] + line["w"] / 2),
                         "y": top + int(line["y"] + line["h"] / 2),
                         "text": line["text"], "ratio": ratio,
                         "left": left + line["x"], "top": top + line["y"],
                         "w": line["w"], "h": line["h"]})
    return hits


def find_app_in_search(win: dict, keyword: str) -> dict | None:
    """在微信搜索结果里，定位「最近使用过的小程序」那一段里的目标。"""
    lines = ocr_lines(capture_client(win))
    if not lines:
        return None
    left, top, _, _ = client_rect(win["hwnd"])

    def find_header(name: str) -> float | None:
        best = None
        for line in lines:
            if _similar(line["text"], name) >= 0.45:
                if best is None or line["y"] < best:
                    best = line["y"]
        return best

    start = find_header("最近使用过的小程序")
    end = find_header("聊天记录")
    candidates = []
    for line in lines:
        if _similar(line["text"], keyword) < 0.6:
            continue
        y = line["y"]
        if start is not None and y < start:
            continue
        if end is not None and y > end:
            continue
        candidates.append(line)
    if not candidates:
        return None
    chosen = min(candidates, key=lambda l: l["y"])
    return {"x": left + int(chosen["x"] + chosen["w"] / 2),
            "y": top + int(chosen["y"] + chosen["h"] / 2),
            "text": chosen["text"]}


# --------------------------------------------------------------------------- #
# 配置 / 步骤
# --------------------------------------------------------------------------- #
DEFAULT_CONFIG = {
    "wechat_exe": "",
    "process_names": ["WeChat.exe", "Weixin.exe", "WeChatAppEx.exe", "WeChatApp.exe"],
    "main_window_titles": ["微信", "WeChat", "Weixin"],
    "window_wait_seconds": 15,
    "min_step_delay": 0.35,
    "max_step_delay": 8.0,
    "start_idle_seconds": 2.0,
    "start_idle_timeout_seconds": 300,
    "retries": 0,
    "notify_failure": True,
    "notify_success": False,
    "screenshot_scale": 2,
    "keep_logs_days": 30,
    "force_geometry": True,
    "email": {
        "enabled": False,
        "to": "",
        "smtp_host": "",
        "smtp_port": 465,
        "username": "",
        "password": "",
        "use_ssl": True,
        "on_first_failure": True,
        "on_success": False,
        "attach_screenshot": True,
    },
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8-sig") as fh:
                cfg.update(json.load(fh))
        except Exception as exc:
            LOG.warning("读取 config.json 失败，使用默认配置: %s", exc)
    else:
        save_config(cfg)
    return cfg


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def load_steps() -> dict:
    if not os.path.exists(STEPS_PATH):
        raise SignError("还没有录制流程：请先运行 record.bat 录制一次签到过程")
    with open(STEPS_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_steps(data: dict) -> None:
    if os.path.exists(STEPS_PATH):
        backup = os.path.join(
            APP_DIR, "steps-backup-%s.json" % datetime.now().strftime("%Y%m%d-%H%M%S"))
        with open(STEPS_PATH, "r", encoding="utf-8") as fh:
            old = fh.read()
        with open(backup, "w", encoding="utf-8") as fh:
            fh.write(old)
        LOG.info("旧的 steps.json 已备份为 %s", os.path.basename(backup))
    with open(STEPS_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def load_state() -> dict:
    try:
        with open(STATE_PATH, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_state(data: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def wechat_processes(cfg: dict) -> set[str]:
    return {name.lower() for name in cfg.get("process_names", [])}


def find_wechat_windows(cfg: dict, include_hidden: bool = False) -> list[dict]:
    procs = wechat_processes(cfg)
    return [w for w in list_windows(include_hidden) if w["process"].lower() in procs]


def _pick_main(candidates: list[dict], cfg: dict) -> dict | None:
    """挑真正的主窗口：必须够大，标题完全匹配「微信」的优先。"""
    titles = [t.lower() for t in cfg.get("main_window_titles", [])]
    best = None
    best_score = -1
    for win in candidates:
        width, height = win["rect"][2], win["rect"][3]
        if width < 400 or height < 400:
            continue
        title = win["title"].lower()
        if title == "微信":
            score = 3
        elif any(t and title == t for t in titles):
            score = 2
        elif any(t and t in title for t in titles):
            score = 1
        else:
            continue
        if score > best_score:
            best, best_score = win, score
    return best


def main_wechat_window(cfg: dict) -> dict | None:
    """找微信主窗口；如果它被收进托盘（隐藏），顺手把它显示出来。"""
    visible = find_wechat_windows(cfg)
    win = _pick_main(visible, cfg)
    if win:
        return win

    hidden = [w for w in find_wechat_windows(cfg, include_hidden=True)
              if not user32.IsWindowVisible(w["hwnd"])]
    win = _pick_main(hidden, cfg)
    if win:
        LOG.info("微信主窗口在托盘里（隐藏），把它显示出来")
        user32.ShowWindow(win["hwnd"], 9)
        time.sleep(0.8)
        user32.ShowWindow(win["hwnd"], 5)
        time.sleep(0.6)
        win["rect"] = list(window_rect(win["hwnd"]))
        return win

    return visible[0] if visible else None


def resolve_window(step: dict, cfg: dict, timeout: float | None = None) -> dict:
    """按录制时的窗口标题/类名找到目标窗口。"""
    target = step.get("win") or {}
    title = (target.get("title") or "").strip()
    class_name = (target.get("class") or "").strip()
    procs = wechat_processes(cfg)
    timeout = cfg["window_wait_seconds"] if timeout is None else timeout
    deadline = time.time() + max(timeout, 0.5)
    loose: dict | None = None
    class_only: dict | None = None

    while True:
        candidates = [w for w in list_windows() if w["process"].lower() in procs]
        if title:
            for win in candidates:
                if win["title"] == title:
                    return win
            for win in candidates:
                if title in win["title"] or win["title"] in title:
                    loose = loose or win
        if class_name:
            for win in candidates:
                if win["class"] == class_name:
                    class_only = class_only or win
        if loose:
            return loose
        if time.time() >= deadline:
            break
        time.sleep(0.35)

    if class_only:
        LOG.warning("按标题没找到 %r，改用同窗口类的窗口：%s", title, class_only["title"])
        return class_only
    hidden = [w for w in find_wechat_windows(cfg, include_hidden=True)
              if not user32.IsWindowVisible(w["hwnd"])]
    for win in hidden:
        if title and (win["title"] == title or title in win["title"]):
            LOG.info("窗口「%s」在托盘里，正在显示它", title)
            user32.ShowWindow(win["hwnd"], 9)
            time.sleep(0.8)
            win["rect"] = list(window_rect(win["hwnd"]))
            return win
    if title:
        raise SignError(f"找不到窗口「{title}」，请确认微信/小程序仍然打开着")
    raise SignError("步骤里没有窗口信息，无法定位")


def click_point(win: dict, step: dict) -> tuple[int, int]:
    left, top, width, height = client_rect(win["hwnd"])
    offset = step.get("offset") or {}
    if "x" in offset and "y" in offset:
        x = left + int(offset["x"])
        y = top + int(offset["y"])
        x = max(left + 1, min(x, left + width - 2))
        y = max(top + 1, min(y, top + height - 2))
        return x, y
    rel = step.get("rel") or {}
    if width > 0 and height > 0 and "x" in rel and "y" in rel:
        x = left + int(round(float(rel["x"]) * width))
        y = top + int(round(float(rel["y"]) * height))
        x = max(left + 1, min(x, left + width - 2))
        y = max(top + 1, min(y, top + height - 2))
        return x, y
    absolute = step.get("abs") or {}
    if "x" in absolute and "y" in absolute:
        return int(absolute["x"]), int(absolute["y"])
    raise SignError("步骤里没有可用的点击坐标")


# --------------------------------------------------------------------------- #
# 录制
# --------------------------------------------------------------------------- #
def cmd_record(args) -> int:
    cfg = load_config()
    print("=" * 68)
    print("  晚安成电 · 签到流程录制")
    print("=" * 68)
    print("准备：微信已登录、主窗口可见，并先关掉「成电智慧学工」小程序，")
    print("      模拟每晚 22:00 的初始状态。")
    print()
    print("录制开始后，正常完整地做一遍签到：打开小程序 -> 晚安成电 -> 签到。")
    print("程序会自动记录微信窗口内的每次左键点击、回车、Esc。")
    print()
    print("  F9  = 开始录制")
    print("  F10 = 结束并保存")
    print("  F7  = 把剪贴板内容粘贴进当前输入框（同时记录一步）")
    print()

    windows = find_wechat_windows(cfg)
    if not windows:
        print("!! 当前没有检测到微信窗口，请先打开微信再重试。")
        return 2
    print("检测到微信相关窗口：")
    for win in windows:
        print("  - %s  [%s]  %s" % (win["title"], win["process"], win["class"]))
    print()

    print("等待你按 F9 开始 ……（最多等 3 分钟）")
    if not _wait_hotkey(VK_F9, timeout=180):
        print("超时未开始，已退出。")
        return 2

    print("\n● 开始录制，请现在开始操作微信。")
    steps: list[dict] = []
    procs = wechat_processes(cfg)
    last_event = time.perf_counter()
    previous = {"lb": False, "enter": False, "esc": False, "f7": False, "f10": False}
    started = time.perf_counter()

    def add(step: dict) -> None:
        nonlocal last_event
        now = time.perf_counter()
        step["delay"] = round(max(0.0, now - last_event), 3)
        last_event = now
        steps.append(step)
        print("  + [%d] %s" % (len(steps), _describe_step(step)))

    while True:
        foreground = user32.GetForegroundWindow()
        foreground_proc = get_process_name(foreground).lower()
        in_wechat = foreground_proc in procs

        f10 = is_down(VK_F10)
        if f10 and not previous["f10"]:
            break
        previous["f10"] = f10

        f7 = is_down(VK_F7)
        if f7 and not previous["f7"] and in_wechat:
            text = get_clipboard_text().strip()
            if text:
                set_clipboard_text(text)
                send_ctrl_v()
                add({"type": "paste", "text": text, "win": _win_info(foreground)})
            else:
                print("  ! 剪贴板是空的，F7 未记录")
        previous["f7"] = f7

        lb = is_down(VK_LBUTTON)
        if lb and not previous["lb"] and in_wechat:
            x, y = get_cursor_pos()
            left, top, width, height = client_rect(foreground)
            if width > 0 and height > 0:
                rel = {"x": round((x - left) / width, 4), "y": round((y - top) / height, 4)}
                add({"type": "click", "rel": rel, "abs": {"x": x, "y": y},
                     "client": [width, height], "win": _win_info(foreground)})
        previous["lb"] = lb

        for key, vk, name in (("enter", VK_RETURN, "enter"), ("esc", VK_ESCAPE, "esc")):
            down = is_down(vk)
            if down and not previous[key] and in_wechat:
                add({"type": "key", "key": name, "win": _win_info(foreground)})
            previous[key] = down

        time.sleep(0.012)

    elapsed = time.perf_counter() - started
    print("\n● 录制结束：%d 步，用时 %.0f 秒。" % (len(steps), elapsed))
    if not steps:
        print("没有录到任何操作，未保存。请重试。")
        return 2
    if not any(s["type"] == "click" for s in steps):
        print("提示：没有录到点击，流程可能不完整。")

    data = {
        "version": 1,
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "screen": list(virtual_screen()),
        "steps": steps,
    }
    save_steps(data)
    print("已保存到 steps.json")
    print("建议接下来运行 test.bat 先试运行一遍（不会真的点击）。")
    return 0


def _win_info(hwnd) -> dict:
    return {"title": get_window_text(hwnd), "class": get_class_name(hwnd),
            "process": get_process_name(hwnd)}


def _describe_step(step: dict) -> str:
    kind = step.get("type")
    title = (step.get("win") or {}).get("title", "")
    if kind == "click":
        rel = step.get("rel") or {}
        return "点击「%s」相对位置 (%.1f%%, %.1f%%)" % (
            title, rel.get("x", 0) * 100, rel.get("y", 0) * 100)
    if kind == "key":
        return "按键 %s @ 「%s」" % (step.get("key"), title)
    if kind == "paste":
        text = step.get("text", "")
        short = text if len(text) <= 16 else text[:16] + "…"
        return "粘贴文字 %r" % short
    return str(step)


def _wait_hotkey(vk: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_down(vk):
            while is_down(vk):
                time.sleep(0.02)
            return True
        time.sleep(0.02)
    return False


# --------------------------------------------------------------------------- #
# 执行
# --------------------------------------------------------------------------- #
def ensure_wechat(cfg: dict) -> dict:
    win = main_wechat_window(cfg)
    if win:
        return win

    exe = cfg.get("wechat_exe") or detect_wechat_exe()
    if not exe:
        raise SignError("微信没有运行，也找不到微信安装路径。请手动打开微信，"
                        "或在 config.json 的 wechat_exe 里填写微信程序路径")
    LOG.info("微信未运行，正在启动: %s", exe)
    try:
        subprocess.Popen([exe])
    except Exception as exc:
        raise SignError(f"启动微信失败: {exc}") from exc

    deadline = time.time() + 120
    while time.time() < deadline:
        win = main_wechat_window(cfg)
        if win:
            time.sleep(2.0)
            return win
        time.sleep(1.0)
    raise SignError("微信启动后 120 秒内仍没有出现主窗口（可能需要手机确认登录）")


def detect_wechat_exe() -> str:
    try:
        import winreg
    except Exception:
        return ""
    keys = [
        (winreg.HKEY_CURRENT_USER, r"Software\Tencent\WeChat", "InstallPath"),
        (winreg.HKEY_CURRENT_USER, r"Software\Tencent\Weixin", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Tencent\WeChat", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Tencent\WeChat", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Tencent\Weixin", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Tencent\Weixin", "InstallPath"),
    ]
    for root, path, name in keys:
        try:
            with winreg.OpenKey(root, path) as key:
                value, _ = winreg.QueryValueEx(key, name)
                if os.path.isfile(value):
                    return value
                for exe in ("WeChat.exe", "Weixin.exe"):
                    candidate = os.path.join(value, exe)
                    if os.path.isfile(candidate):
                        return candidate
        except OSError:
            continue
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        for sub in (r"Tencent\WeChat\WeChat.exe", r"Tencent\Weixin\Weixin.exe"):
            candidate = os.path.join(base, sub)
            if os.path.isfile(candidate):
                return candidate
    return ""


def wait_until_idle(cfg: dict) -> None:
    need = float(cfg.get("start_idle_seconds", 2.0))
    deadline = time.time() + float(cfg.get("start_idle_timeout_seconds", 300))
    while time.time() < deadline:
        if idle_seconds() >= need:
            return
        time.sleep(0.3)
    LOG.warning("等待用户空闲超时，继续执行")


def find_window_by_title(title: str, cfg: dict) -> dict | None:
    if not title:
        return None
    procs = wechat_processes(cfg)
    loose = None
    for win in list_windows():
        if win["process"].lower() not in procs:
            continue
        if win["title"] == title:
            return win
        if title in win["title"] and loose is None:
            loose = win
    return loose


def raise_window(win: dict) -> None:
    """把窗口提到最前（先置顶再取消置顶），不需要前台权限。"""
    hwnd = win["hwnd"]
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
    user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, flags)   # HWND_TOPMOST
    user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, flags)   # HWND_NOTOPMOST
    time.sleep(0.05)


def ensure_foreground(win: dict, tries: int = 3) -> bool:
    """点击前尽量让目标窗口在前台；抢不到就把它提到最前，保证点得到。"""
    hwnd = win["hwnd"]
    for _ in range(tries):
        if user32.GetForegroundWindow() == hwnd:
            return True
        activate_window(hwnd)
        time.sleep(0.15)
    if user32.GetForegroundWindow() == hwnd:
        return True
    raise_window(win)
    return user32.GetForegroundWindow() == hwnd


def click_relative(win: dict, pos: dict) -> tuple[int, int]:
    """pos 可以是 {"offset": {...}} 或 {"rel": {...}}。"""
    ensure_foreground(win)
    x, y = click_point(win, pos)
    click_at(x, y)
    return x, y


def restore_geometry(win: dict, step: dict, cfg: dict) -> None:
    """把窗口挪回录制时的位置和大小，保证后续绝对坐标不偏。"""
    target = step.get("geometry")
    if not target or not cfg.get("force_geometry", True):
        return
    current = list(window_rect(win["hwnd"]))
    if all(abs(current[i] - int(target[i])) <= 2 for i in range(4)):
        return
    LOG.info("把窗口「%s」恢复为录制时的位置和大小 %s", win["title"], target)
    user32.SetWindowPos(win["hwnd"], 0, int(target[0]), int(target[1]),
                        int(target[2]), int(target[3]), SWP_NOZORDER | SWP_NOACTIVATE)
    time.sleep(0.5)


def send_hotkey(keys: list[str]) -> None:
    vk_map = {"ctrl": VK_CONTROL, "control": VK_CONTROL, "shift": 0x10,
              "alt": VK_MENU, "win": 0x5B}
    vks = []
    for key in keys:
        vk = vk_map.get(key.lower())
        if vk is None:
            if len(key) != 1:
                raise SignError(f"不支持的组合键: {key}")
            vk = ord(key.upper())
        vks.append(vk)
    for vk in vks:
        _send_key(vk, up=False)
        time.sleep(0.02)
    for vk in reversed(vks):
        _send_key(vk, up=True)
        time.sleep(0.02)


def ensure_text_page(win: dict, target: str, back_offset: dict, tries: int = 3) -> bool:
    """确保停留在包含 target 文字的页面；不在就点返回箭头退回去。"""
    for _ in range(tries):
        hits = find_text_lines(win, target, 0.6)
        if hits:
            hit = max(hits, key=lambda item: item["y"])
            LOG.info("页面已就绪（找到「%s」），点击 (%d, %d)", hit["text"], hit["x"], hit["y"])
            activate_window(win["hwnd"])
            click_at(hit["x"], hit["y"])
            time.sleep(1.0)
            return True
        LOG.info("没看到「%s」，点左上角返回", target)
        click_relative(win, {"offset": back_offset})
        time.sleep(1.2)
    return False


def open_miniprogram(step: dict, cfg: dict, dry_run: bool = False) -> None:
    """通过微信搜索打开小程序；结果行位置可能随热搜条数变化，逐行向下重试。"""
    keyword = str(step.get("keyword", ""))
    title = str(step.get("window_title") or keyword)
    result_rel = step.get("result_rel") or {}
    result_offset = step.get("result_offset") or {}
    row_step_rel = float(step.get("row_step_rel", 0.0293))
    row_step_px = float(step.get("row_step_px", 44))
    tries = max(1, int(step.get("tries", 5)))
    search_offset = step.get("search_offset") or {}
    search_rel = step.get("search_rel") or {}

    search_pos = {"offset": search_offset} if search_offset else {"rel": search_rel}

    existing = find_window_by_title(title, cfg)
    if existing:
        close_rel = step.get("close_rel")
        if close_rel and not dry_run:
            LOG.info("关闭上次遗留的小程序窗口，准备重新打开")
            activate_window(existing["hwnd"])
            time.sleep(0.4)
            click_relative(existing, {"rel": close_rel})
            time.sleep(1.5)
        if find_window_by_title(title, cfg):
            LOG.warning("小程序窗口没能关掉，先使用现有窗口")
            activate_window(existing["hwnd"])
            return

    main = main_wechat_window(cfg)
    if not main:
        raise SignError("找不到微信主窗口，无法打开小程序")
    if dry_run:
        LOG.info("将打开小程序「%s」（搜索框 %s，结果位置 %s）", keyword, search_pos,
                 result_offset or result_rel)
        return

    for attempt in range(tries):
        activate_window(main["hwnd"])
        time.sleep(0.3)
        restore_geometry(main, step, cfg)
        ensure_foreground(main)
        click_relative(main, search_pos)
        time.sleep(0.35)
        send_hotkey(["ctrl", "a"])
        time.sleep(0.08)
        paste_text(keyword)
        time.sleep(1.1)
        hit = find_app_in_search(main, keyword)
        if hit:
            LOG.info("按文字定位到小程序入口「%s」(%d, %d)，点击", hit["text"], hit["x"], hit["y"])
            activate_window(main["hwnd"])
            click_at(hit["x"], hit["y"])
        else:
            if result_offset:
                pos = {"offset": {"x": result_offset.get("x", 226),
                                  "y": result_offset.get("y", 493) + attempt * row_step_px}}
            else:
                pos = {"rel": {"x": float(result_rel.get("x", 0.146)),
                               "y": float(result_rel.get("y", 0.328)) + attempt * row_step_rel}}
            LOG.info("OCR 没定位到，按坐标尝试第 %d 行：%s", attempt + 1, pos)
            click_relative(main, pos)
        deadline = time.time() + 6
        while time.time() < deadline:
            win = find_window_by_title(title, cfg)
            if win:
                activate_window(win["hwnd"])
                LOG.info("小程序「%s」已打开", title)
                return
            time.sleep(0.3)
        LOG.warning("第 %d 次没有打开小程序，换个位置再试", attempt + 1)
        send_key("esc")
        time.sleep(0.4)
    raise SignError("多次尝试仍未打开小程序「%s」" % keyword)


def wait_content(win: dict, timeout: float = 10.0, spread: int = 40,
                 min_wait: float = 0.35) -> bool:
    """等窗口内容真正画出来（避免死等固定秒数）。"""
    time.sleep(min_wait)
    deadline = time.time() + timeout
    while True:
        try:
            values = capture_client(win).sample(step=16)
        except Exception:
            values = []
        if values and (max(values) - min(values)) >= spread:
            return True
        if time.time() >= deadline:
            return False
        time.sleep(0.25)


def paste_text(text: str, restore: bool = True) -> None:
    """用剪贴板粘贴，完事把剪贴板内容还回去，尽量不打扰用户。"""
    old = get_clipboard_text() if restore else ""
    set_clipboard_text(text)
    time.sleep(0.12)
    send_ctrl_v()
    time.sleep(0.4)
    if restore and old:
        try:
            set_clipboard_text(old)
        except Exception:
            pass


def wait_stable(win: dict, timeout: float = 15.0, threshold: float = 1.5,
                stable_needed: int = 3, min_spread: int = 30,
                min_wait: float = 0.5) -> bool:
    """等页面真正画完：连续几帧几乎不变，而且不是白屏。"""
    time.sleep(min_wait)
    deadline = time.time() + timeout
    previous = None
    stable = 0
    while time.time() < deadline:
        try:
            current = capture_client(win)
            values = current.sample(step=16)
        except Exception:
            current, values = None, []
        spread = (max(values) - min(values)) if values else 0
        if previous is not None and spread >= min_spread:
            diff = screen_diff(previous, current)
            stable = stable + 1 if diff < threshold else 0
            if stable >= stable_needed:
                return True
        previous = current
        time.sleep(0.35)
    return False


def _is_success_text(text: str) -> bool:
    """判断一行 OCR 文字是不是打卡成功的提示。"""
    text = (text or "").replace(" ", "")
    if not text:
        return False
    # 这些是"还没到时间/说明文字"，一定不是成功
    if "未到" in text or "时间段" in text or "不能及时" in text:
        return False
    if "成功" in text:
        return True
    # "已打卡 / 今日已打卡 / 已签到" 都算成功；
    # 单独的标签「今日打卡」「我的打卡」不含「已」，不会被误判
    if "已打卡" in text or "已签到" in text:
        return True
    return False


def status_looks_signed(win: dict) -> bool:
    """用颜色判断打卡页是不是已经变成「已打卡」样式（文字是画布绘制的，OCR 读不出）。"""
    try:
        image = capture_client(win)
    except Exception:
        return False

    circle = crop_image(image, 120, 430, 180, 230)   # 中间状态圆
    strip = crop_image(image, 20, 690, 380, 40)      # 底部结果条

    def ratio(part: ScreenImage, test) -> float:
        data = part.rgb
        total = max(part.width * part.height, 1)
        hit = 0
        for i in range(0, len(data), 3):
            if test(data[i], data[i + 1], data[i + 2]):
                hit += 1
        return hit / total

    blue = ratio(circle, lambda r, g, b: b > 140 and b - r > 60 and b - g > 60)
    green = ratio(strip, lambda r, g, b: g > 180 and (g - r) > 6 and (g - b) > 6)
    return blue < 0.12 and green > 0.15


def verify_by_text(win: dict, timeout: float = 15.0) -> bool:
    """点击后校验：优先 OCR 找成功提示，其次看状态区颜色是否变成已打卡样式。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1.0)
        if status_looks_signed(win):
            LOG.info("状态区已变成「已打卡」样式（蓝色圆消失、底部出现绿色结果条）")
            return True
        try:
            ensure_foreground(win)
            lines = ocr_lines(capture_client(win))
        except Exception:
            lines = []
        for line in lines:
            if _is_success_text(line["text"]):
                LOG.info("界面出现「%s」，确认打卡成功", line["text"])
                return True
    return False


def find_checkin_button(win: dict) -> tuple[int, int, str] | None:
    """在页面里找「打卡/签到」按钮文字，作为坐标点不中时的兜底。"""
    lines = ocr_lines(capture_client(win))
    left, top, _, _ = client_rect(win["hwnd"])
    best = None
    for line in lines:
        text = line["text"].replace(" ", "")
        if "打卡" not in text and "签到" not in text:
            continue
        if len(text) > 6:  # 按钮标签很短，长句多半是提示/说明
            continue
        if any(bad in text for bad in ("今日", "今打卡", "未到", "时间段", "记录", "我的",
                                       "规则", "通知", "服务号", "提醒")):
            continue
        if line["h"] < 11:
            continue
        if best is None or line["h"] > best["h"]:
            best = line
    if not best:
        return None
    return (left + int(best["x"] + best["w"] / 2),
            top + int(best["y"] + best["h"] / 2), best["text"])


def click_verify(step: dict, win: dict, dry_run: bool = False) -> bool:
    """点击打卡：先点录制位置，不成就按 OCR 找按钮、再点一次。"""
    x, y = click_point(win, step)
    if dry_run:
        LOG.info("将点击 (%d, %d) 并检查结果", x, y)
        return False

    attempts = [(x, y, "录制位置")]
    LOG.info("点击打卡 (%d, %d)  @ %s", x, y, win["title"])
    click_at(x, y)
    if verify_by_text(win, float(step.get("timeout", 10.0))):
        return True

    # 兜底一：按文字找「打卡」按钮再点
    try:
        button = find_checkin_button(win)
    except Exception:
        button = None
    if button and abs(button[0] - x) + abs(button[1] - y) > 12:
        LOG.info("按文字找到按钮「%s」(%d, %d)，再点一次", button[2], button[0], button[1])
        activate_window(win["hwnd"])
        click_at(button[0], button[1])
        if verify_by_text(win, float(step.get("retry_timeout", 8.0))):
            return True

    # 兜底二：原位置再点一次（有些页面第二次点击才响应）
    LOG.info("再点一次录制位置 (%d, %d)", x, y)
    activate_window(win["hwnd"])
    click_at(x, y)
    if verify_by_text(win, float(step.get("retry_timeout", 8.0))):
        return True

    raise SignError("多次点击后仍没看到打卡成功的提示，等下一次自动尝试")


def execute_steps(steps: list[dict], cfg: dict, dry_run: bool = False) -> dict:
    total = len(steps)
    result = {"verified": False}
    for index, step in enumerate(steps, 1):
        kind = step.get("type")
        delay = float(step.get("delay", 0.0))
        delay = max(cfg["min_step_delay"], min(delay, cfg["max_step_delay"]))
        if index == 1:
            delay = min(delay, 1.0)
        time.sleep(delay)

        if kind == "wait":
            time.sleep(float(step.get("seconds", 1.0)))
            continue
        if kind == "shot":
            if not dry_run:
                save_screenshot(os.path.join(LOG_DIR, "step-%d-%s.png" % (
                    index, datetime.now().strftime("%H%M%S"))), 2)
            continue
        if kind == "open_miniprogram":
            LOG.info("[%d/%d] 打开小程序「%s」", index, total, step.get("keyword"))
            open_miniprogram(step, cfg, dry_run)
            continue

        try:
            win = resolve_window(step, cfg)
        except SignError:
            if step.get("optional"):
                LOG.info("[%d/%d] 跳过（窗口不存在）：%s", index, total, _describe_step(step))
                continue
            raise

        if not activate_window(win["hwnd"]):
            time.sleep(0.3)
            activate_window(win["hwnd"])

        if kind in ("click", "scroll", "click_verify"):
            restore_geometry(win, step, cfg)

        if kind == "wait_content":
            if dry_run:
                LOG.info("[%d/%d] 等待「%s」页面加载", index, total, win["title"])
                continue
            LOG.info("[%d/%d] 等待「%s」页面加载完成……", index, total, win["title"])
            if not wait_content(win, float(step.get("timeout", 10.0)),
                                int(step.get("spread", 40))):
                LOG.warning("等待页面加载超时（%.0f 秒），继续往下走", float(step.get("timeout", 10.0)))

        elif kind == "wait_stable":
            if dry_run:
                LOG.info("[%d/%d] 等待「%s」画面稳定", index, total, win["title"])
                continue
            LOG.info("[%d/%d] 等待「%s」画面稳定……", index, total, win["title"])
            if not wait_stable(win, float(step.get("timeout", 15.0)),
                               float(step.get("threshold", 1.5)),
                               int(step.get("stable_needed", 3)),
                               int(step.get("min_spread", 30))):
                LOG.warning("等待画面稳定超时（%.0f 秒），继续往下走", float(step.get("timeout", 15.0)))

        elif kind == "ensure_text":
            target = str(step.get("text", ""))
            LOG.info("[%d/%d] 确认页面停在「%s」", index, total, target)
            if not dry_run and not ensure_text_page(
                    win, target, step.get("back_offset") or {"x": 22, "y": 45},
                    int(step.get("tries", 3))):
                LOG.warning("没能在「%s」页面，继续尝试", target)

        elif kind == "click_text":
            target = str(step.get("text", ""))
            timeout = float(step.get("timeout", 6.0))
            deadline = time.time() + timeout
            hit = None
            while time.time() < deadline:
                try:
                    hits = find_text_lines(win, target, float(step.get("threshold", 0.6)))
                except Exception:
                    hits = []
                if hits:
                    hit = max(hits, key=lambda item: item["ratio"])
                    break
                time.sleep(0.6)
            if hit:
                LOG.info("[%d/%d] 找到并点击「%s」(%d, %d)", index, total,
                         hit["text"], hit["x"], hit["y"])
                if not dry_run:
                    activate_window(win["hwnd"])
                    click_at(hit["x"], hit["y"])
            else:
                LOG.info("[%d/%d] 页面上没有「%s」，跳过这一步", index, total, target)
                if not step.get("optional", True):
                    raise SignError("没有在页面上找到「%s」" % target)

        elif kind == "verify_success":
            if dry_run:
                LOG.info("[%d/%d] 校验打卡是否成功", index, total)
                continue
            LOG.info("[%d/%d] 校验打卡结果……", index, total)
            if not verify_by_text(win, float(step.get("timeout", 12.0))):
                raise SignError("没有看到打卡成功的提示")
            result["verified"] = True

        elif kind == "click_verify":
            LOG.info("[%d/%d] 点击打卡并校验结果", index, total)
            if click_verify(step, win, dry_run):
                result["verified"] = True

        elif kind == "click":
            x, y = click_point(win, step)
            if dry_run:
                LOG.info("[%d/%d] 将点击 (%d, %d)  @ %s", index, total, x, y, win["title"])
                continue
            LOG.info("[%d/%d] 点击 (%d, %d)  @ %s", index, total, x, y, win["title"])
            click_at(x, y)

        elif kind == "key":
            LOG.info("[%d/%d] 按键 %s @ %s", index, total, step.get("key"), win["title"])
            if not dry_run:
                send_key(str(step.get("key", "enter")))

        elif kind == "hotkey":
            keys = step.get("keys") or []
            LOG.info("[%d/%d] 组合键 %s @ %s", index, total, "+".join(keys), win["title"])
            if not dry_run:
                send_hotkey([str(k) for k in keys])

        elif kind == "paste":
            text = str(step.get("text", ""))
            LOG.info("[%d/%d] 粘贴文字（%d 字）@ %s", index, total, len(text), win["title"])
            if not dry_run:
                paste_text(text, restore=bool(step.get("restore_clipboard", True)))

        elif kind == "scroll":
            x, y = click_point(win, step)
            clicks = int(step.get("clicks", -3))
            LOG.info("[%d/%d] 滚动 %d @ (%d, %d)", index, total, clicks, x, y)
            if not dry_run:
                user32.SetCursorPos(x, y)
                time.sleep(0.1)
                mouse_wheel(clicks)

        else:
            LOG.warning("[%d/%d] 未知步骤类型 %r，跳过", index, total, kind)
    return result


def lower_process_priority() -> None:
    """降到低于正常优先级，避免和前台程序抢 CPU 造成卡顿。"""
    try:
        kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.SetPriorityClass.restype = wintypes.BOOL
        kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x00004000)  # BELOW_NORMAL
    except Exception:
        pass


def email_config(cfg: dict) -> dict:
    return cfg.get("email") or {}


def email_ready(cfg: dict) -> bool:
    conf = email_config(cfg)
    return bool(conf.get("enabled") and conf.get("to") and conf.get("smtp_host")
                and conf.get("username") and conf.get("password"))


def send_email(cfg: dict, subject: str, body: str, attachment: str | None = None) -> bool:
    """用配置里的 SMTP 账号发一封邮件（标准库实现，无第三方依赖）。"""
    conf = email_config(cfg)
    if not email_ready(cfg):
        LOG.warning("邮件提醒还没配置好，跳过发送")
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = conf.get("username", "")
    message["To"] = conf.get("to", "")
    message.set_content(body)

    if attachment and conf.get("attach_screenshot", True) and os.path.exists(attachment):
        try:
            with open(attachment, "rb") as fh:
                message.add_attachment(fh.read(), maintype="image", subtype="png",
                                       filename=os.path.basename(attachment))
        except Exception as exc:
            LOG.warning("邮件附件读取失败：%s", exc)

    host = conf.get("smtp_host", "")
    port = int(conf.get("smtp_port") or 465)
    try:
        if conf.get("use_ssl", True):
            server = smtplib.SMTP_SSL(host, port, timeout=25,
                                      context=ssl.create_default_context())
            with server:
                server.login(conf.get("username", ""), conf.get("password", ""))
                server.send_message(message)
        else:
            server = smtplib.SMTP(host, port, timeout=25)
            with server:
                server.starttls(context=ssl.create_default_context())
                server.login(conf.get("username", ""), conf.get("password", ""))
                server.send_message(message)
        LOG.info("提醒邮件已发送到 %s", conf.get("to"))
        return True
    except Exception as exc:
        LOG.error("发送邮件失败：%s", exc)
        return False


def _load_email_state() -> dict:
    try:
        with open(EMAIL_STATE_PATH, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_email_state(state: dict) -> None:
    try:
        with open(EMAIL_STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    except Exception:
        pass


def notify_failure_email(cfg: dict, message: str, screenshot: str | None = None) -> None:
    """第一次失败时发一封邮件（同一天只发一次）。"""
    conf = email_config(cfg)
    if not conf.get("enabled") or not email_ready(cfg):
        return
    if not conf.get("on_first_failure", True):
        return

    today = datetime.now().strftime("%Y-%m-%d")
    state = _load_email_state()
    if state.get("failure_date") == today:
        LOG.info("今天已经发过失败提醒邮件，不重复发送")
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    subject = "【晚安成电】%s 自动签到没有成功" % now
    body = "\n".join([
        "自动签到这次没有成功。",
        "",
        "时间：%s" % now,
        "原因：%s" % message,
        "",
        "程序会继续按计划重试（22:15、22:30、22:45、23:00、23:15）。",
        "如果你已经手动签到，可以忽略这封邮件。",
        "",
        "打卡时间：每天 21:00–23:30",
        "截图：%s" % (screenshot or "（无）"),
        "日志目录：%s" % LOG_DIR,
    ])
    if send_email(cfg, subject, body, screenshot):
        state["failure_date"] = today
        state["failure_time"] = now
        state["failure_reason"] = message
        _save_email_state(state)


def notify_success_email(cfg: dict, message: str, screenshot: str | None = None) -> None:
    if not email_config(cfg).get("on_success"):
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    body = "\n".join([
        "自动签到已成功。",
        "",
        "时间：%s" % now,
        "说明：%s" % message,
        "",
        "截图：%s" % (screenshot or "（无）"),
    ])
    send_email(cfg, "【晚安成电】%s 打卡成功" % now, body, screenshot)


def notify(title: str, message: str, warn: bool = True, timeout_ms: int = 60000) -> None:
    if not HAS_MSGBOXTIMEOUT:
        return
    flags = 0x00040000 | 0x00010000  # MB_TOPMOST | MB_SETFOREGROUND
    flags |= 0x00000030 if warn else 0x00000040  # MB_ICONWARNING / INFORMATION
    try:
        user32.MessageBoxTimeoutW(None, message, title, flags, 0, timeout_ms)
    except Exception:
        pass


def prune_logs(cfg: dict) -> None:
    """清理过期日志，避免截图越攒越多。"""
    days = int(cfg.get("keep_logs_days", 30))
    if days <= 0 or not os.path.isdir(LOG_DIR):
        return
    limit = time.time() - days * 86400
    for name in os.listdir(LOG_DIR):
        path = os.path.join(LOG_DIR, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < limit:
                os.remove(path)
        except OSError:
            pass


def cmd_run(args) -> int:
    cfg = load_config()
    prune_logs(cfg)
    data = load_steps()
    steps = data.get("steps") or []
    if not steps:
        raise SignError("steps.json 里没有步骤，请重新录制")

    today = datetime.now().strftime("%Y-%m-%d")
    state = load_state()
    if not getattr(args, "dry_run", False) and not getattr(args, "force", False) \
            and state.get("date") == today and state.get("signed"):
        LOG.info("今天已经打卡成功（%s），本次跳过，不再打扰", state.get("signed_at"))
        return 0

    recorded_screen = data.get("screen") or []
    current_screen = list(virtual_screen())
    if recorded_screen:
        if len(recorded_screen) == 2:
            same_screen = list(recorded_screen) == [current_screen[2], current_screen[3]]
        else:
            same_screen = list(recorded_screen) == current_screen
        if not same_screen:
            message = ("屏幕分辨率和录制时不同（录制 %s，当前 %s）。"
                       "为避免在错误位置乱点，本次直接跳过。" % (recorded_screen, current_screen))
            LOG.error(message)
            if cfg.get("abort_on_screen_mismatch", True):
                notify_failure_email(cfg, message)
                return 1
            LOG.warning("仍按当前分辨率继续，点击位置可能偏移")

    if getattr(args, "dry_run", False):
        LOG.info("=== 试运行（不会真正点击）===")
        for step in steps:
            if step.get("type") == "open_miniprogram":
                open_miniprogram(step, cfg, dry_run=True)
            elif step.get("type") in ("click", "scroll"):
                win = resolve_window(step, cfg)
                x, y = click_point(win, step)
                LOG.info("%s -> (%d, %d)", _describe_step(step), x, y)
            else:
                LOG.info("%s", _describe_step(step))
        LOG.info("试运行结束，共 %d 步", len(steps))
        return 0

    win = ensure_wechat(cfg)
    LOG.info("微信窗口：%s [%s]", win["title"], win["process"])
    if not activate_window(win["hwnd"]):
        LOG.warning("未能把微信切到前台，仍继续尝试")
    time.sleep(1.0)
    if not getattr(args, "no_wait_idle", False):
        wait_until_idle(cfg)

    try:
        before = grab_screen()
    except Exception:
        before = None

    attempts = 1 + max(0, int(cfg.get("retries", 1)))
    status = "fail"
    message = ""
    verified = False
    for attempt in range(1, attempts + 1):
        LOG.info("=== 第 %d/%d 次执行签到 ===", attempt, attempts)
        try:
            result = execute_steps(steps, cfg)
            verified = bool(result.get("verified"))
            status = "ok"
            message = "打卡点击已生效" if verified else "点击流程执行完毕（未校验到界面变化）"
            break
        except SignError as exc:
            message = str(exc)
            LOG.error("第 %d 次执行失败：%s", attempt, exc)
        except Exception as exc:  # noqa: BLE001
            message = f"{type(exc).__name__}: {exc}"
            LOG.exception("第 %d 次执行异常", attempt)
        save_screenshot(os.path.join(LOG_DIR, "fail-%s-%d.png" % (
            datetime.now().strftime("%Y%m%d-%H%M%S"), attempt)),
            int(cfg.get("screenshot_scale", 2)))
        if attempt < attempts:
            time.sleep(20)
            main_win = main_wechat_window(cfg)
            if main_win:
                activate_window(main_win["hwnd"])
            time.sleep(2)

    if status == "ok" and verified:
        save_state({"date": today, "signed": True,
                    "signed_at": datetime.now().isoformat(timespec="seconds")})
        LOG.info("已记录今日打卡成功，后续的定时尝试会直接跳过")

    try:
        after = grab_screen()
        changed = screen_diff(before, after) if before else None
    except Exception:
        changed = None
    if changed is not None:
        LOG.info("执行前后画面差异：%.2f", changed)
        if changed < 1.0:
            LOG.warning("画面几乎没有变化，可能点击没有生效，请查看截图确认")

    final_shot = save_screenshot(os.path.join(
        LOG_DIR, "last-%s.png" % datetime.now().strftime("%Y%m%d-%H%M%S")),
        int(cfg.get("screenshot_scale", 2)))
    LOG.info("结束截图：%s", final_shot)

    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "message": message,
        "verified": verified,
        "screen_changed": changed,
        "screenshot": final_shot,
        "steps": len(steps),
    }
    with open(os.path.join(APP_DIR, "last_run.json"), "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)

    LOG.info("结果：%s（%s）", status, message)
    if status == "ok":
        if cfg.get("notify_success"):
            notify("晚安成电自动签到", "签到流程已完成。\n" + message, warn=False)
        notify_success_email(cfg, message, final_shot)
    else:
        notify_failure_email(cfg, message, final_shot)
        # 配了邮件就以邮件为准；没配邮件时，只在当天没有后续重试机会时弹窗
        quiet_after = str(cfg.get("notify_failure_after", "23:00"))
        if cfg.get("notify_failure", True) and not email_ready(cfg) \
                and datetime.now().strftime("%H:%M") >= quiet_after:
            notify("晚安成电自动签到失败", message + "\n\n截图：" + final_shot, warn=True)
        else:
            LOG.info("失败已记录（有邮件提醒时不再弹窗）")
    return 0 if status == "ok" else 1


def _guess_smtp(addr: str) -> str:
    domain = addr.split("@")[-1].lower().strip()
    table = {
        "qq.com": "smtp.qq.com", "foxmail.com": "smtp.qq.com",
        "163.com": "smtp.163.com", "126.com": "smtp.126.com",
        "gmail.com": "smtp.gmail.com", "outlook.com": "smtp.office365.com",
        "hotmail.com": "smtp.office365.com", "live.com": "smtp.office365.com",
        "sina.com": "smtp.sina.com", "aliyun.com": "smtp.aliyun.com",
        "139.com": "smtp.139.com", "189.cn": "smtp.189.cn",
    }
    return table.get(domain, "smtp." + domain if domain else "smtp.qq.com")


def cmd_email_setup(args) -> int:
    cfg = load_config()
    conf = dict(cfg.get("email") or {})
    print("=" * 62)
    print("  配置失败提醒邮件（22:00 第一次没签上时发信给你）")
    print("=" * 62)
    print("  * 用你自己的邮箱发给自己，不需要任何第三方服务。")
    print("  * QQ / 163 邮箱要填「SMTP 授权码」，不是登录密码：")
    print("      QQ邮箱 ：设置 → 账号 → 开启 SMTP 服务 → 生成授权码")
    print("      163邮箱：设置 → POP3/SMTP/IMAP → 开启 → 设置授权码")
    print("  * 授权码会保存在本机 config.json 里，请勿把该文件发给别人。")
    print()

    to = input("收件邮箱（提醒发到这个地址）[%s]: " % (conf.get("to") or "")).strip() or conf.get("to", "")
    if not to:
        print("必须填写收件邮箱。")
        return 2
    guess = conf.get("smtp_host") or _guess_smtp(to)
    host = input("SMTP 服务器 [%s]: " % guess).strip() or guess
    port = input("端口 [%s]: " % (conf.get("smtp_port") or 465)).strip() or str(conf.get("smtp_port") or 465)
    user = (input("发件账号（通常和收件邮箱相同）[%s]: " % (conf.get("username") or to)).strip()
            or conf.get("username") or to)
    password = getpass.getpass("授权码/密码（输入时不显示）: ").strip()
    if not password:
        password = conf.get("password", "")
    if not password:
        print("必须填写授权码/密码。")
        return 2

    conf.update({
        "enabled": True,
        "to": to,
        "smtp_host": host,
        "smtp_port": int(port),
        "username": user,
        "password": password,
        "use_ssl": True,
        "on_first_failure": True,
        "on_success": bool(conf.get("on_success", False)),
        "attach_screenshot": True,
    })
    cfg["email"] = conf
    save_config(cfg)

    print("\n正在发送测试邮件 ……")
    if send_email(cfg, "【晚安成电】邮件提醒测试",
                  "这是一封测试邮件：说明失败提醒已经配置成功。"):
        print("测试邮件已发送，请查收（收不到就看下垃圾箱）。")
        return 0
    print("测试发送失败：请检查授权码、服务器、端口或网络。")
    return 1


def cmd_email_test(args) -> int:
    cfg = load_config()
    if not email_ready(cfg):
        print("还没有配置邮件，请先运行 email_setup.bat")
        return 2
    ok = send_email(cfg, "【晚安成电】邮件提醒测试",
                    "这是一封测试邮件：说明失败提醒已经配置成功。")
    print("测试邮件已发送" if ok else "发送失败，详见日志")
    return 0 if ok else 1


def cmd_list(args) -> int:
    cfg = load_config()
    windows = find_wechat_windows(cfg) if args.wechat else list_windows()
    if not windows:
        print("没有匹配的窗口。")
        return 1
    print("%-10s %-16s %-5s %-34s %s" % ("HWND", "PROCESS", "MIN", "CLASS", "TITLE"))
    for win in windows:
        print("%-10s %-16s %-5s %-34s %s" % (
            win["hwnd"], win["process"], "yes" if win["minimized"] else "",
            win["class"][:34], win["title"]))
    if args.wechat:
        main_win = main_wechat_window(cfg)
        print("\n微信主窗口：", main_win["title"] if main_win else "未找到")
    return 0


def cmd_shot(args) -> int:
    path = args.path or os.path.join(LOG_DIR, "shot-%s.png" % datetime.now().strftime("%Y%m%d-%H%M%S"))
    save_screenshot(path)
    print("已保存截图：", path)
    return 0


def cmd_selftest(args) -> int:
    print("自检开始……")
    ok = True
    x, y = get_cursor_pos()
    user32.SetCursorPos(x + 1, y)
    time.sleep(0.1)
    if get_cursor_pos() != (x + 1, y):
        print("  [FAIL] 鼠标定位")
        ok = False
    else:
        print("  [OK]   鼠标定位")
    user32.SetCursorPos(x, y)

    image = grab_screen()
    values = image.sample(step=24)
    spread = (max(values) - min(values)) if values else 0
    if spread < 3:
        print("  [WARN] 截图几乎纯色，可能锁屏或截图被阻止（差异 %d）" % spread)
    else:
        print("  [OK]   截图 %dx%d（亮度差 %d）" % (image.width, image.height, spread))

    target = os.path.join(LOG_DIR, "selftest_input.txt")
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(target, "w", encoding="utf-8"):
        pass
    subprocess.Popen(["notepad.exe", target])
    win = None
    try:
        deadline = time.time() + 15
        while time.time() < deadline:
            for candidate in list_windows():
                if "selftest_input" in candidate["title"]:
                    win = candidate
                    break
            if win:
                break
            time.sleep(0.3)
        if not win:
            print("  [FAIL] 无法打开记事本做输入测试")
            return 1
        activate_window(win["hwnd"])
        time.sleep(0.6)
        if user32.GetForegroundWindow() != win["hwnd"]:
            print("  [FAIL] 无法把记事本切到前台（当前前台：%s）" %
                  get_window_text(user32.GetForegroundWindow()))
            return 1
        left, top, width, height = client_rect(win["hwnd"])
        click_at(left + width // 2, top + height // 2)
        sample = "自检 OK 123 ABC"
        send_text(sample)
        time.sleep(0.4)
        _send_key(VK_CONTROL, up=False)
        _send_key(0x41, up=False)
        _send_key(0x41, up=True)
        _send_key(VK_CONTROL, up=True)
        time.sleep(0.2)
        _send_key(VK_CONTROL, up=False)
        _send_key(0x43, up=False)
        _send_key(0x43, up=True)
        _send_key(VK_CONTROL, up=True)
        time.sleep(0.4)
        got = get_clipboard_text()
        if sample in got:
            print("  [OK]   键盘输入 + 剪贴板（读到 %r）" % got[:40])
        else:
            print("  [FAIL] 键盘输入校验，读到 %r" % got[:80])
            ok = False
    finally:
        if win:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(win["hwnd"], ctypes.byref(pid))
            if pid.value:
                subprocess.run(["taskkill", "/PID", str(pid.value), "/F"],
                               capture_output=True, check=False)

    print("自检结果：", "通过" if ok else "有问题")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def setup_logging(verbose: bool) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    logfile = os.path.join(LOG_DIR, "run-%s.log" % datetime.now().strftime("%Y%m%d"))
    handlers: list[logging.Handler] = [logging.FileHandler(logfile, encoding="utf-8")]
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        handlers=handlers,
        force=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wechat_auto.py", description="晚安成电自动签到助手")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="执行签到")
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--force", action="store_true", help="忽略今天已成功的记录，强制再跑")
    run_parser.add_argument("--no-notify", action="store_true", help="不弹提示框")
    run_parser.add_argument("--no-wait-idle", action="store_true", help="不等用户停止操作（测试用）")
    sub.add_parser("record", help="录制签到流程")
    test_parser = sub.add_parser("test", help="试运行，不点击")
    test_parser.add_argument("--dry-run", action="store_true", default=True)
    sub.add_parser("selftest", help="鼠标/键盘/截图自检")
    sub.add_parser("email-setup", help="配置失败提醒邮件")
    sub.add_parser("email-test", help="发一封测试邮件")
    shot_parser = sub.add_parser("shot", help="截屏")
    shot_parser.add_argument("path", nargs="?")
    list_parser = sub.add_parser("list", help="列出窗口")
    list_parser.add_argument("--wechat", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    enable_dpi_awareness()
    lower_process_priority()
    # 输出被重定向（例如写进文件）时统一用 UTF-8，避免中文乱码
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    setup_logging(args.verbose)

    if sys.stdout is None:  # pythonw 下没有控制台
        sys.stdout = open(os.path.join(LOG_DIR, "console-%s.log" %
                                       datetime.now().strftime("%Y%m%d")), "a", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = sys.stdout

    try:
        if args.command == "record":
            return cmd_record(args)
        if args.command == "run":
            return cmd_run(args)
        if args.command == "test":
            args.dry_run = True
            return cmd_run(args)
        if args.command == "shot":
            return cmd_shot(args)
        if args.command == "list":
            return cmd_list(args)
        if args.command == "selftest":
            return cmd_selftest(args)
        if args.command == "email-setup":
            return cmd_email_setup(args)
        if args.command == "email-test":
            return cmd_email_test(args)
    except SignError as exc:
        LOG.error("%s", exc)
        try:
            if args.command == "run":
                email_cfg = load_config()
                notify_failure_email(email_cfg, str(exc))
                if email_cfg.get("notify_failure", True) and not email_ready(email_cfg) and \
                        datetime.now().strftime("%H:%M") >= str(email_cfg.get("notify_failure_after", "23:00")):
                    notify("晚安成电自动签到失败", str(exc), warn=True)
        except Exception:
            pass
        return 1
    except KeyboardInterrupt:
        return 130
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
