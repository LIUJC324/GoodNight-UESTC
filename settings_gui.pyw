#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""晚安成电 · 图形控制台

双击 scripts 目录下的 settings.bat 打开。可以：
  * 切换运行模式：自动签到 / 邮件提醒 / 全部停止
  * 设置启用日期区间（从…到…，留空表示不限）
  * 设置签到时间、提醒时间
  * 配置提醒邮箱并发送测试邮件
  * 一键同步 Windows 计划任务（安装、启停）

所有设置写进同目录的 config.json；任务调用 install_task.ps1 / install_remind.ps1。
"""

from __future__ import annotations

import os
import subprocess
import sys
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

INSTALL_SIGN = os.path.join(APP_DIR, "install_task.ps1")
INSTALL_REMIND = os.path.join(APP_DIR, "install_remind.ps1")
TASK_SIGN = "WananChengdianSign"
TASK_REMIND = "WananChengdianRemind"
CREATE_NO_WINDOW = 0x08000000

FONT = ("Microsoft YaHei UI", 10)
FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")

MODE_LABELS = {
    "sign": "自动签到（电脑模拟点击）",
    "remind": "邮件提醒（到点发信，手机签）",
    "off": "全部停止",
}


def guess_smtp(address: str) -> str:
    return core._guess_smtp(address or "")


def run_powershell(script: str, timeout: int = 120) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW,
            encoding="utf-8", errors="replace")
        return result.returncode == 0, (result.stdout or "") + (result.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def run_ps_file(path: str, args: list[str], timeout: int = 120) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path] + args,
            capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW,
            encoding="utf-8", errors="replace")
        return result.returncode == 0, (result.stdout or "") + (result.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def task_states() -> dict[str, str]:
    states = {}
    for name in (TASK_SIGN, TASK_REMIND):
        ok, output = run_powershell(
            "(Get-ScheduledTask -TaskName '%s' -ErrorAction SilentlyContinue).State" % name, timeout=30)
        text = (output or "").strip().splitlines()
        states[name] = text[0].strip() if ok and text else "未安装"
    return states


def task_times(name: str, fallback: tuple[str, str]) -> tuple[str, str]:
    ok, output = run_powershell(
        "(Get-ScheduledTask -TaskName '%s' -ErrorAction SilentlyContinue).Triggers | "
        "ForEach-Object { ([datetime]$_.StartBoundary).ToLocalTime().ToString('HH:mm') }" % name,
        timeout=30)
    labels = [line.strip() for line in (output or "").splitlines() if line.strip()]
    if ok and len(labels) >= 2:
        return labels[0], labels[1]
    return fallback


class ControlApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("晚安成电 · 控制台")
        self.geometry("660x760")
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

        self.var_mode = tk.StringVar(value=self.cfg.get("mode", "remind"))
        self.var_from = tk.StringVar(value=self.cfg.get("active_from", ""))
        self.var_to_date = tk.StringVar(value=self.cfg.get("active_to", ""))
        self.var_no_limit = tk.BooleanVar(
            value=not (self.cfg.get("active_from") or self.cfg.get("active_to")))

        sign_times = task_times(TASK_SIGN, ("22:00", "23:25"))
        remind_times = task_times(TASK_REMIND, ("22:00", "23:15"))
        self.var_sign1 = tk.StringVar(value=sign_times[0])
        self.var_sign2 = tk.StringVar(value=sign_times[1])
        self.var_remind1 = tk.StringVar(value=remind_times[0])
        self.var_remind2 = tk.StringVar(value=remind_times[1])

        self._build()
        self.refresh_status()
        self.status("设置改完点「保存并应用」，会自动同步 Windows 计划任务。")

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#f5f6f8")
        style.configure("TLabel", background="#f5f6f8", font=FONT)
        style.configure("Hint.TLabel", background="#f5f6f8", foreground="#888",
                        font=("Microsoft YaHei UI", 9))
        style.configure("TLabelframe", background="#f5f6f8")
        style.configure("TLabelframe.Label", background="#f5f6f8", font=FONT_BOLD)
        style.configure("TButton", font=FONT)
        style.configure("Accent.TButton", font=FONT_BOLD)

        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="晚安成电 · 控制台",
                  font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w")
        ttk.Label(outer, text="一个界面管理运行模式、启用日期、时间和提醒邮箱。",
                  style="Hint.TLabel").pack(anchor="w", pady=(2, 10))

        # ---------------- 运行控制 ----------------
        control = ttk.LabelFrame(outer, text=" 运行控制 ", padding=10)
        control.pack(fill="x")

        modes = ttk.Frame(control)
        modes.pack(fill="x")
        for index, (value, label) in enumerate(MODE_LABELS.items()):
            ttk.Radiobutton(modes, text=label, value=value, variable=self.var_mode,
                            command=self._on_mode_change).grid(
                row=index, column=0, sticky="w", pady=1)

        dates = ttk.Frame(control)
        dates.pack(fill="x", pady=(8, 0))
        ttk.Label(dates, text="启用日期").pack(side="left")
        ttk.Entry(dates, textvariable=self.var_from, width=12, font=FONT).pack(side="left", padx=(6, 4))
        ttk.Label(dates, text="到").pack(side="left")
        ttk.Entry(dates, textvariable=self.var_to_date, width=12, font=FONT).pack(side="left", padx=(4, 10))
        ttk.Checkbutton(dates, text="不限日期", variable=self.var_no_limit,
                        command=self._on_no_limit).pack(side="left")
        ttk.Label(control, text="格式 YYYY-MM-DD；到期后任务会自动跳过，不会误发。",
                  style="Hint.TLabel").pack(anchor="w", pady=(2, 0))

        state_row = ttk.Frame(control)
        state_row.pack(fill="x", pady=(8, 0))
        self.status_tasks = ttk.Label(state_row, text="任务状态：读取中……")
        self.status_tasks.pack(side="left")
        ttk.Button(state_row, text="刷新状态", command=self.refresh_status).pack(side="right")

        # ---------------- 时间 ----------------
        when = ttk.LabelFrame(outer, text=" 时间设置（24 小时制 HH:MM） ", padding=10)
        when.pack(fill="x", pady=10)

        row = ttk.Frame(when)
        row.pack(fill="x")
        ttk.Label(row, text="签到时间", width=9).pack(side="left")
        ttk.Entry(row, textvariable=self.var_sign1, width=7, font=FONT).pack(side="left")
        ttk.Label(row, text="和").pack(side="left", padx=4)
        ttk.Entry(row, textvariable=self.var_sign2, width=7, font=FONT).pack(side="left")

        row = ttk.Frame(when)
        row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, text="提醒时间", width=9).pack(side="left")
        ttk.Entry(row, textvariable=self.var_remind1, width=7, font=FONT).pack(side="left")
        ttk.Label(row, text="和").pack(side="left", padx=4)
        ttk.Entry(row, textvariable=self.var_remind2, width=7, font=FONT).pack(side="left")

        # ---------------- 邮箱 ----------------
        mail = ttk.LabelFrame(outer, text=" 提醒邮箱 ", padding=10)
        mail.pack(fill="x")

        row = ttk.Frame(mail)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="收件邮箱", width=9).pack(side="left")
        entry_to = ttk.Entry(row, textvariable=self.var_to, font=FONT)
        entry_to.pack(side="left", fill="x", expand=True)
        entry_to.bind("<FocusOut>", self._auto_host)

        row = ttk.Frame(mail)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="发件账号", width=9).pack(side="left")
        ttk.Entry(row, textvariable=self.var_user, font=FONT).pack(side="left", fill="x", expand=True)

        row = ttk.Frame(mail)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="SMTP", width=9).pack(side="left")
        ttk.Entry(row, textvariable=self.var_host, font=FONT).pack(side="left", fill="x", expand=True)
        ttk.Label(row, text="端口").pack(side="left", padx=(8, 4))
        ttk.Entry(row, textvariable=self.var_port, width=6, font=FONT).pack(side="left")

        row = ttk.Frame(mail)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="授权码", width=9).pack(side="left")
        self.entry_pwd = ttk.Entry(row, textvariable=self.var_password, font=FONT, show="*")
        self.entry_pwd.pack(side="left", fill="x", expand=True)
        ttk.Checkbutton(row, text="显示", variable=self.var_show_pwd,
                        command=self._toggle_pwd).pack(side="left", padx=(8, 0))

        row = ttk.Frame(mail)
        row.pack(fill="x", pady=(6, 2))
        ttk.Checkbutton(row, text="启用邮件", variable=self.var_enabled).pack(side="left")
        ttk.Checkbutton(row, text="成功也通知", variable=self.var_on_success).pack(side="left", padx=(16, 0))

        # ---------------- 按钮 ----------------
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(12, 4))
        ttk.Button(buttons, text="发送测试邮件", command=self.on_test).pack(side="left")
        ttk.Button(buttons, text="立即发提醒", command=self.on_remind_now).pack(side="left", padx=6)
        ttk.Button(buttons, text="保存", command=lambda: self.on_save(False)).pack(side="right", padx=6)
        ttk.Button(buttons, text="保存并应用", style="Accent.TButton",
                   command=lambda: self.on_save(True)).pack(side="right")

        self.status_label = ttk.Label(outer, text="", style="Hint.TLabel",
                                      wraplength=620, justify="left")
        self.status_label.pack(fill="x", pady=(4, 0))

    # ------------------------------------------------------------------ #
    def _on_mode_change(self) -> None:
        mode = self.var_mode.get()
        self.status("已选择：%s。点「保存并应用」后生效。" % MODE_LABELS.get(mode, mode))

    def _on_no_limit(self) -> None:
        if self.var_no_limit.get():
            self.var_from.set("")
            self.var_to_date.set("")

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

    def refresh_status(self) -> None:
        states = task_states()
        sign = states.get(TASK_SIGN, "未知")
        remind = states.get(TASK_REMIND, "未知")
        self.status_tasks.configure(
            text="任务状态：签到=%s   提醒=%s" % (sign, remind))

    # ------------------------------------------------------------------ #
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

        for label, value in (("签到第一次", self.var_sign1.get().strip()),
                             ("签到第二次", self.var_sign2.get().strip()),
                             ("提醒第一次", self.var_remind1.get().strip()),
                             ("提醒第二次", self.var_remind2.get().strip())):
            try:
                datetime.strptime(value, "%H:%M")
            except ValueError:
                messagebox.showwarning("时间不对", "%s要写成 HH:MM，例如 22:00。" % label)
                return None

        start = "" if self.var_no_limit.get() else self.var_from.get().strip()
        end = "" if self.var_no_limit.get() else self.var_to_date.get().strip()
        for label, value in (("开始日期", start), ("结束日期", end)):
            if not value:
                continue
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                messagebox.showwarning("日期不对", "%s要写成 YYYY-MM-DD，例如 2026-10-23。" % label)
                return None
        if start and end and start > end:
            messagebox.showwarning("日期顺序不对", "开始日期不能晚于结束日期。")
            return None

        return {
            "to": to, "host": host, "port": port, "user": user,
            "password": password, "enabled": self.var_enabled.get(),
            "on_success": self.var_on_success.get(),
            "mode": self.var_mode.get(), "from": start, "to_date": end,
        }

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
        self.cfg["mode"] = data["mode"]
        self.cfg["active_from"] = data["from"]
        self.cfg["active_to"] = data["to_date"]
        core.save_config(self.cfg)

    # ------------------------------------------------------------------ #
    def on_test(self) -> None:
        data = self._collect()
        if not data:
            return
        if not data["enabled"]:
            messagebox.showinfo("提示", "请先勾选「启用邮件」。")
            return
        self._apply_config(data)
        self.status("正在发送测试邮件 ……")
        threading.Thread(target=self._test_worker, daemon=True).start()

    def _test_worker(self) -> None:
        ok = core.send_email(self.cfg, "【晚安成电】邮件测试",
                             "这是一封测试邮件：说明提醒邮箱已经配置成功。")
        self.after(0, lambda: self.status(
            "测试邮件已发送，请查收（收不到先看垃圾箱）。" if ok
            else "发送失败：检查授权码 / 服务器 / 端口。"))

    def on_remind_now(self) -> None:
        data = self._collect()
        if not data:
            return
        self._apply_config(data)
        self.status("正在发送提醒邮件 ……")
        threading.Thread(target=self._remind_worker, daemon=True).start()

    def _remind_worker(self) -> None:
        try:
            result = subprocess.run(
                [sys.executable, os.path.join(APP_DIR, "wechat_auto.py"), "remind"],
                capture_output=True, timeout=90, creationflags=CREATE_NO_WINDOW,
                encoding="utf-8", errors="replace")
            output = (result.stdout or "") + (result.stderr or "")
            ok = "已发送" in output
            msg = "提醒邮件已发送。" if ok else ("发送失败：" + output.strip()[-160:])
        except Exception as exc:  # noqa: BLE001
            msg = "发送失败：%s" % exc
        self.after(0, lambda: self.status(msg))

    def on_save(self, apply_task: bool) -> None:
        data = self._collect()
        if not data:
            return
        self._apply_config(data)
        self.status("已保存到 config.json。")
        if apply_task:
            self.status("正在同步计划任务 ……")
            threading.Thread(target=self._sync_worker, args=(data,), daemon=True).start()
        else:
            self.status("已保存。下次运行会使用新的设置。")

    def _sync_worker(self, data: dict) -> None:
        mode = data["mode"]
        messages = []
        ok1, out1 = run_ps_file(INSTALL_SIGN, ["-Time", self.var_sign1.get().strip(),
                                              "-Time2", self.var_sign2.get().strip()])
        ok2, out2 = run_ps_file(INSTALL_REMIND, ["-Time1", self.var_remind1.get().strip(),
                                                "-Time2", self.var_remind2.get().strip()])
        if not ok1:
            messages.append("签到任务安装失败：" + out1.strip()[-120:])
        if not ok2:
            messages.append("提醒任务安装失败：" + out2.strip()[-120:])

        enable_sign = mode == "sign"
        enable_remind = mode == "remind"
        for name, enable in ((TASK_SIGN, enable_sign), (TASK_REMIND, enable_remind)):
            verb = "Enable" if enable else "Disable"
            run_powershell("%s-ScheduledTask -TaskName '%s' -ErrorAction SilentlyContinue | Out-Null"
                           % (verb, name), timeout=30)

        states = task_states()
        summary = "模式：%s；签到=%s，提醒=%s。" % (
            MODE_LABELS.get(mode, mode), states.get(TASK_SIGN), states.get(TASK_REMIND))
        if messages:
            summary += " " + " ".join(messages)
        self.after(0, lambda: (self.refresh_status(), self.status(summary)))


def main() -> int:
    try:
        app = ControlApp()
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
            messagebox.showerror("控制台出错", detail[-900:])
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
