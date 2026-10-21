#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""晚安成电 · 图形设置界面

双击 email_setup.bat 打开。可以设置：
  * 失败提醒邮箱（收件地址、SMTP 服务器、授权码）
  * 每天两次自动尝试的时间
  * 保存后自动更新 Windows 计划任务

保存后会写进同目录的 config.json，并调用 install_task.ps1 更新任务时间。
"""

from __future__ import annotations

import os
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from datetime import datetime

APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(APP_DIR, "logs"), exist_ok=True)

try:
    import wechat_auto as core
except Exception:  # noqa: BLE001  启动失败时要能看到原因
    import traceback
    detail = traceback.format_exc()
    with open(os.path.join(APP_DIR, "logs", "gui-error.log"), "a", encoding="utf-8") as fh:
        fh.write(detail + "\n")
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("启动失败", "加载主程序出错：\n\n" + detail[-700:])
    raise SystemExit(1)
INSTALL_SCRIPT = os.path.join(APP_DIR, "install_task.ps1")
CREATE_NO_WINDOW = 0x08000000

FONT = ("Microsoft YaHei UI", 10)
FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")


def guess_smtp(address: str) -> str:
    return core._guess_smtp(address or "")


class SettingsApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("晚安成电 · 设置")
        self.geometry("600x600")
        self.resizable(False, False)
        self.configure(bg="#f5f6f8")

        self.cfg = core.load_config()
        email_cfg = dict(self.cfg.get("email") or {})

        self.var_to = tk.StringVar(value=email_cfg.get("to", ""))
        self.var_user = tk.StringVar(value=email_cfg.get("username", ""))
        self.var_host = tk.StringVar(value=email_cfg.get("smtp_host", ""))
        self.var_port = tk.StringVar(value=str(email_cfg.get("smtp_port", 465)))
        self.var_password = tk.StringVar(value=email_cfg.get("password", ""))
        self.var_enabled = tk.BooleanVar(value=bool(email_cfg.get("enabled", False)))
        self.var_on_success = tk.BooleanVar(value=bool(email_cfg.get("on_success", False)))
        self.var_show_pwd = tk.BooleanVar(value=False)

        steps = self._load_times()
        self.var_time1 = tk.StringVar(value=steps[0])
        self.var_time2 = tk.StringVar(value=steps[1])
        self.var_update_task = tk.BooleanVar(value=True)

        self._build()
        self.status("填写后点「保存并应用」。授权码只保存在本机 config.json 里。")

    # ------------------------------------------------------------------ #
    def _load_times(self) -> tuple[str, str]:
        """从计划任务里读出当前的两次运行时间，读不到就用默认值。"""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-ScheduledTask -TaskName WananChengdianSign).Triggers | "
                 "ForEach-Object { ([datetime]$_.StartBoundary).ToLocalTime().ToString('HH:mm') }"],
                capture_output=True, text=True, timeout=20,
                creationflags=CREATE_NO_WINDOW, encoding="utf-8", errors="replace")
            labels = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
            if len(labels) >= 2:
                return labels[0], labels[1]
        except Exception:
            pass
        return "22:00", "23:25"

    def _build(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#f5f6f8")
        style.configure("TLabel", background="#f5f6f8", font=FONT)
        style.configure("Hint.TLabel", background="#f5f6f8", foreground="#888", font=("Microsoft YaHei UI", 9))
        style.configure("TLabelframe", background="#f5f6f8")
        style.configure("TLabelframe.Label", background="#f5f6f8", font=FONT_BOLD)
        style.configure("TButton", font=FONT)
        style.configure("Accent.TButton", font=FONT_BOLD)

        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="晚安成电 · 自动签到设置", font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w")
        ttk.Label(outer, text="填好邮箱后，22:00 第一次没签上会自动发邮件提醒你。",
                  style="Hint.TLabel").pack(anchor="w", pady=(2, 12))

        # ---------------- 邮箱 ----------------
        mail = ttk.LabelFrame(outer, text=" 失败提醒邮箱 ", padding=12)
        mail.pack(fill="x")

        row = ttk.Frame(mail)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="收件邮箱", width=10).pack(side="left")
        entry_to = ttk.Entry(row, textvariable=self.var_to, font=FONT)
        entry_to.pack(side="left", fill="x", expand=True)
        entry_to.bind("<FocusOut>", self._auto_host)

        row = ttk.Frame(mail)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="发件账号", width=10).pack(side="left")
        ttk.Entry(row, textvariable=self.var_user, font=FONT).pack(side="left", fill="x", expand=True)

        row = ttk.Frame(mail)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="SMTP", width=10).pack(side="left")
        ttk.Entry(row, textvariable=self.var_host, font=FONT).pack(side="left", fill="x", expand=True)
        ttk.Label(row, text="端口").pack(side="left", padx=(8, 4))
        ttk.Entry(row, textvariable=self.var_port, width=6, font=FONT).pack(side="left")

        row = ttk.Frame(mail)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="授权码", width=10).pack(side="left")
        self.entry_pwd = ttk.Entry(row, textvariable=self.var_password, font=FONT, show="*")
        self.entry_pwd.pack(side="left", fill="x", expand=True)
        ttk.Checkbutton(row, text="显示", variable=self.var_show_pwd,
                        command=self._toggle_pwd).pack(side="left", padx=(8, 0))

        row = ttk.Frame(mail)
        row.pack(fill="x", pady=(8, 2))
        ttk.Checkbutton(row, text="启用邮件提醒", variable=self.var_enabled).pack(side="left")
        ttk.Checkbutton(row, text="成功也通知", variable=self.var_on_success).pack(side="left", padx=(16, 0))

        ttk.Label(mail, text="QQ / 163 邮箱要填「SMTP 授权码」，不是登录密码：\n"
                             "QQ邮箱 → 设置 → 账号 → 开启 SMTP → 生成授权码",
                  style="Hint.TLabel").pack(anchor="w", pady=(6, 0))

        # ---------------- 时间 ----------------
        when = ttk.LabelFrame(outer, text=" 自动尝试时间 ", padding=12)
        when.pack(fill="x", pady=12)

        row = ttk.Frame(when)
        row.pack(fill="x")
        ttk.Label(row, text="第一次").pack(side="left")
        ttk.Entry(row, textvariable=self.var_time1, width=8, font=FONT).pack(side="left", padx=(6, 18))
        ttk.Label(row, text="第二次").pack(side="left")
        ttk.Entry(row, textvariable=self.var_time2, width=8, font=FONT).pack(side="left", padx=(6, 0))
        ttk.Label(row, text="（24 小时制 HH:MM）", style="Hint.TLabel").pack(side="left", padx=(10, 0))

        ttk.Checkbutton(when, text="保存后同时更新 Windows 计划任务时间",
                        variable=self.var_update_task).pack(anchor="w", pady=(8, 0))

        # ---------------- 按钮 ----------------
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(4, 8))
        ttk.Button(buttons, text="发送测试邮件", command=self.on_test).pack(side="left")
        ttk.Button(buttons, text="保存", command=lambda: self.on_save(False)).pack(side="left", padx=8)
        ttk.Button(buttons, text="保存并应用", style="Accent.TButton",
                   command=lambda: self.on_save(True)).pack(side="left")

        self.status_label = ttk.Label(outer, text="", style="Hint.TLabel", wraplength=560, justify="left")
        self.status_label.pack(fill="x", pady=(6, 0))

    # ------------------------------------------------------------------ #
    def _toggle_pwd(self) -> None:
        self.entry_pwd.configure(show="" if self.var_show_pwd.get() else "*")

    def _auto_host(self, _event=None) -> None:
        if not self.var_host.get().strip() and "@" in self.var_to.get():
            self.var_host.set(guess_smtp(self.var_to.get()))
        if not self.var_user.get().strip() and "@" in self.var_to.get():
            self.var_user.set(self.var_to.get().strip())

    def status(self, text: str) -> None:
        self.status_label.configure(text=text)
        self.update_idletasks()

    def _collect(self) -> dict | None:
        to = self.var_to.get().strip()
        host = self.var_host.get().strip()
        port_text = self.var_port.get().strip() or "465"
        user = self.var_user.get().strip() or to
        password = self.var_password.get()

        if self.var_enabled.get():
            if "@" not in to:
                messagebox.showwarning("邮箱不对", "请填写正确的收件邮箱地址。")
                return None
            if not host:
                messagebox.showwarning("缺少服务器", "请填写 SMTP 服务器（例如 smtp.qq.com）。")
                return None
            if not password:
                messagebox.showwarning("缺少授权码", "请填写 SMTP 授权码（不是登录密码）。")
                return None
        try:
            port = int(port_text)
        except ValueError:
            messagebox.showwarning("端口不对", "端口要填数字，例如 465。")
            return None

        for label, value in (("第一次", self.var_time1.get().strip()),
                             ("第二次", self.var_time2.get().strip())):
            try:
                datetime.strptime(value, "%H:%M")
            except ValueError:
                messagebox.showwarning("时间不对", "%s时间要写成 HH:MM，例如 22:00。" % label)
                return None

        return {"to": to, "host": host, "port": port, "user": user,
                "password": password, "enabled": self.var_enabled.get(),
                "on_success": self.var_on_success.get()}

    def _apply_config(self, data: dict) -> None:
        email_cfg = dict(self.cfg.get("email") or {})
        email_cfg.update({
            "enabled": data["enabled"],
            "to": data["to"],
            "smtp_host": data["host"],
            "smtp_port": data["port"],
            "username": data["user"],
            "password": data["password"],
            "use_ssl": True,
            "on_first_failure": True,
            "on_success": data["on_success"],
            "attach_screenshot": True,
        })
        self.cfg["email"] = email_cfg
        core.save_config(self.cfg)

    # ------------------------------------------------------------------ #
    def on_test(self) -> None:
        data = self._collect()
        if not data:
            return
        if not data["enabled"]:
            messagebox.showinfo("提示", "请先勾选「启用邮件提醒」。")
            return
        self._apply_config(data)
        self.status("正在发送测试邮件 ……")
        threading.Thread(target=self._test_worker, daemon=True).start()

    def _test_worker(self) -> None:
        ok = core.send_email(self.cfg, "【晚安成电】邮件提醒测试",
                             "这是一封测试邮件：说明失败提醒已经配置成功。")
        self.after(0, lambda: self.status(
            "测试邮件已发送，请查收（收不到先看垃圾箱）。" if ok
            else "发送失败：检查授权码 / 服务器 / 端口，或看 config.json 同目录的日志。"))

    def on_save(self, apply_task: bool) -> None:
        data = self._collect()
        if not data:
            return
        self._apply_config(data)
        self.status("已保存到 config.json。")

        if apply_task and self.var_update_task.get():
            self.status("正在更新计划任务时间 ……")
            threading.Thread(target=self._task_worker,
                             args=(self.var_time1.get().strip(), self.var_time2.get().strip()),
                             daemon=True).start()
        else:
            self.status("已保存。下次运行会使用新的邮箱设置。")

    def _task_worker(self, time1: str, time2: str) -> None:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", INSTALL_SCRIPT, "-Time", time1, "-Time2", time2],
                capture_output=True, text=True, timeout=120,
                creationflags=CREATE_NO_WINDOW, encoding="utf-8", errors="replace")
            output = (result.stdout or "") + (result.stderr or "")
            ok = "已安装" in output or result.returncode == 0
            msg = ("已保存，计划任务已更新为每天 %s 和 %s。" % (time1, time2)
                   if ok else "保存成功，但更新计划任务失败，请右键以管理员身份运行 install_task.bat。")
        except Exception as exc:  # noqa: BLE001
            msg = "保存成功，但更新计划任务出错：%s" % exc
        self.after(0, lambda: self.status(msg))


def main() -> int:
    try:
        app = SettingsApp()
        app.mainloop()
        return 0
    except Exception:  # noqa: BLE001
        import traceback
        detail = traceback.format_exc()
        try:
            with open(os.path.join(APP_DIR, "logs", "gui-error.log"), "a", encoding="utf-8") as fh:
                fh.write(detail + "\n")
        except Exception:
            pass
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("设置界面出错", detail[-900:])
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
