import os
"""临时探路工具：激活窗口 / 点击 / 截图 / 列窗口（复用 wechat_auto 的函数）。"""
import ctypes
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wechat_auto as w

w.enable_dpi_awareness()


def find(substr: str):
    for win in w.list_windows():
        if substr.lower() in win["title"].lower():
            return win
    return None


def main() -> int:
    cmd = sys.argv[1]
    if cmd == "shot":
        path = sys.argv[2] if len(sys.argv) > 2 else "logs/step.png"
        w.save_screenshot(path, 1)
        print("saved", path)
    elif cmd == "zoom":
        x, y, cw, ch, factor = (int(v) for v in sys.argv[2:7])
        path = sys.argv[7]
        img = w.grab_screen()
        stride = img.width * 3
        out = bytearray()
        for yy in range(y, y + ch):
            base = yy * stride
            row = img.rgb[base + x * 3: base + (x + cw) * 3]
            expanded = bytearray()
            for xx in range(cw):
                expanded += row[xx * 3:xx * 3 + 3] * factor
            out += expanded * factor
        zoomed = w.ScreenImage(cw * factor, ch * factor, bytes(out), img.origin)
        with open(path, "wb") as fh:
            fh.write(w.encode_png(zoomed))
        print("zoomed", path, cw * factor, ch * factor)
    elif cmd == "crop":
        x, y, cw, ch = (int(v) for v in sys.argv[2:6])
        path = sys.argv[6]
        img = w.grab_screen()
        stride = img.width * 3
        out = bytearray()
        for yy in range(y, y + ch):
            base = yy * stride
            out += img.rgb[base + x * 3: base + (x + cw) * 3]
        cropped = w.ScreenImage(cw, ch, bytes(out), img.origin)
        with open(path, "wb") as fh:
            fh.write(w.encode_png(cropped))
        print("cropped", path, cw, ch)
    elif cmd == "top":
        win = find(sys.argv[2])
        if not win:
            print("not found:", sys.argv[2])
            return 1
        w.user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        w.user32.SetWindowPos(win["hwnd"], -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004)
        print("topmost", win["title"], win["hwnd"])
    elif cmd == "actclick":
        win = find(sys.argv[2])
        if not win:
            print("not found:", sys.argv[2])
            return 1
        x, y = int(sys.argv[3]), int(sys.argv[4])
        for _ in range(3):
            w.activate_window(win["hwnd"])
            if w.user32.GetForegroundWindow() in (win["hwnd"],):
                break
            time.sleep(0.2)
        w.click_at(x, y)
        print("clicked", x, y, "fg_ok", w.user32.GetForegroundWindow() == win["hwnd"])
    elif cmd == "click":
        x, y = int(sys.argv[2]), int(sys.argv[3])
        w.click_at(x, y)
        print("clicked", x, y)
    elif cmd == "move":
        x, y = int(sys.argv[2]), int(sys.argv[3])
        w.user32.SetCursorPos(x, y)
        print("moved", x, y)
    elif cmd == "act":
        win = find(sys.argv[2])
        if not win:
            print("not found:", sys.argv[2])
            return 1
        ok = w.activate_window(win["hwnd"])
        print("activated", win["title"], win["class"], ok)
    elif cmd == "list":
        for win in w.list_windows():
            if "weixin" in win["process"].lower() or "wechat" in win["process"].lower():
                print(win["hwnd"], win["process"], win["class"], repr(win["title"]),
                      win["rect"], "min" if win["minimized"] else "")
    elif cmd == "win":
        win = find(sys.argv[2])
        if not win:
            print("not found")
            return 1
        left, top, width, height = w.client_rect(win["hwnd"])
        print(win["title"], "|", win["class"], "|client", left, top, width, height,
              "|rect", win["rect"])
    elif cmd == "key":
        w.send_key(sys.argv[2])
        print("key", sys.argv[2])
    else:
        print("unknown command")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

