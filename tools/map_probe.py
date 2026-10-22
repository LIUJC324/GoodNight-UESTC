"""用 PrintWindow 抓小程序窗口（不受遮挡影响），裁出地图区域放大保存。"""
import ctypes
from ctypes import wintypes

import wechat_auto as w

w.enable_dpi_awareness()
u = w.user32
g = w.gdi32
u.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
u.GetWindowDC.argtypes = [wintypes.HWND]
u.GetWindowDC.restype = wintypes.HDC
u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]


def grab_window(hwnd):
    left, top, width, height = w.window_rect(hwnd)
    hdc = u.GetWindowDC(hwnd)
    mem = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, width, height)
    old = g.SelectObject(mem, bmp)
    try:
        u.PrintWindow(hwnd, mem, 2)
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
    return w.ScreenImage(width, height, bytes(rgb), (left, top))


def upscale(image, factor):
    out = bytearray()
    stride = image.width * 3
    for y in range(image.height):
        row = image.rgb[y * stride:(y + 1) * stride]
        expanded = bytearray()
        for x in range(image.width):
            expanded += row[x * 3:x * 3 + 3] * factor
        out += expanded * factor
    return w.ScreenImage(image.width * factor, image.height * factor, bytes(out), image.origin)


mp = [x for x in w.list_windows() if x["title"] == "成电智慧学工"][0]
img = grab_window(mp["hwnd"])
crop = w.crop_image(img, 10, 60, 400, 260)
big = upscale(crop, 2)
path = "logs/map_zoom2.png"
open(path, "wb").write(w.encode_png(big))
print("saved", path, big.width, big.height)
