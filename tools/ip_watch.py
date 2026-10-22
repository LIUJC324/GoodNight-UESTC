"""定时记录出口 IP 和归属地，用来观察校园网 IP 是否动态变化、以及每次变到哪。"""
import csv
import datetime
import os
import time
import sys
import urllib.request

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = os.path.join(APP_DIR, "logs", "ip-log.csv")
INTERVAL_SECONDS = 300


def query_ip() -> tuple[str, str]:
    request = urllib.request.Request(
        "https://myip.ipip.net", headers={"User-Agent": "curl/8"})
    with urllib.request.urlopen(request, timeout=15) as response:
        text = response.read().decode("utf-8", "replace").strip()
    text = text.replace("当前 IP：", "").replace("来自于：", "|")
    parts = [p.strip() for p in text.split("|")]
    ip = parts[0] if parts else ""
    location = parts[1] if len(parts) > 1 else ""
    return ip, location


def main() -> None:
    once = "--once" in sys.argv
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    new_file = not os.path.exists(LOG_PATH)
    while True:
        with open(LOG_PATH, "a", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            if new_file:
                writer.writerow(["时间", "出口 IP", "归属地"])
                new_file = False
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                ip, location = query_ip()
                print("%s  %s  %s" % (stamp, ip, location), flush=True)
            except Exception as exc:
                ip, location = "", "查询失败: %s" % exc
                print("%s  失败: %s" % (stamp, exc), flush=True)
            writer.writerow([stamp, ip, location])
        if once:
            return
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
