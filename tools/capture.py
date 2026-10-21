import os
"""用 PrintWindow 抓取指定窗口的真实内容（即使被别的窗口挡住）。"""
import ctypes
import sys
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wechat_auto as w

w.enable_dpi_awareness()
u = w.user32
g = w.gdi32

u.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
u.PrintWindow.restype = wintypes.BOOL
u.GetWindowDC.argtypes = [wintypes.HWND]
u.GetWindowDC.restype = wintypes.HDC
u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]


def capture(hwnd, path):
    left, top, width, height = w.window_rect(hwnd)
    hdc = u.GetWindowDC(hwnd)
    mem = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, width, height)
    old = g.SelectObject(mem, bmp)
    try:
        ok = u.PrintWindow(hwnd, mem, 2)  # PW_RENDERFULLCONTENT
        bmi = w.BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(w.BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0
        buf = ctypes.create_string_buffer(width * height * 4)
        g.GetDIBits(mem, bmp, 0, height, buf, ctypes.byref(bmi), 0)
    finally:
        g.SelectObject(mem, old)
        g.DeleteObject(bmp)
        g.DeleteDC(mem)
        u.ReleaseDC(hwnd, hdc)

    bgra = buf.raw
    rgb = bytearray(width * height * 3)
    rgb[0::3] = bgra[2::4]
    rgb[1::3] = bgra[1::4]
    rgb[2::3] = bgra[0::4]
    image = w.ScreenImage(width, height, bytes(rgb), (left, top))
    with open(path, "wb") as fh:
        fh.write(w.encode_png(image))
    print("printwindow", ok, width, height, path)


def main():
    title = sys.argv[1]
    path = sys.argv[2]
    for win in w.list_windows():
        if title in win["title"]:
            capture(win["hwnd"], path)
            print("title", win["title"], "rect", win["rect"], "process", win["process"])
            return 0
    print("not found")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

