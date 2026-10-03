"""在 PyCharm 中同时启动 Django 和 Vite。

Django: http://127.0.0.1:8000
Vite:   http://127.0.0.1:5173

前提：本机已安装 Node.js（npm 可用）与 MySQL，且数据库已 migrate。
PyCharm 的运行控制台是管道，所有输出都带 flush=True，避免"看着在运行但什么都不打印"。
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def log(message: str, error: bool = False) -> None:
    """立即输出（PyCharm 控制台不 flush 会一直看不到内容）。"""
    print(message, file=sys.stderr if error else sys.stdout, flush=True)


def find_npm() -> str | None:
    """定位 npm 可执行文件。

    先按不带扩展名的名字查找（Windows 会依据 PATHEXT 命中 npm.CMD），
    再显式尝试 .cmd/.bat，最后兜底常见安装目录，避免个别环境 PATHEXT
    异常导致 `shutil.which("npm.cmd")` 误判为"未安装 Node"。
    """
    for name in ("npm", "npm.cmd", "npm.bat"):
        found = shutil.which(name)
        if found:
            return found
    for base in (
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("LOCALAPPDATA"),
        os.environ.get("APPDATA"),
        "D:\\A_Software111",  # 本机 Node 的实际安装目录（MSI 自定义路径），可按需删掉
    ):
        if not base:
            continue
        for directory in (Path(base) / "nodejs", Path(base)):
            candidate = directory / "npm.cmd"
            if candidate.is_file():
                return str(candidate)
    return None


def main() -> int:
    npm_command = find_npm()
    if not npm_command:
        log("未找到 npm：请先安装 Node.js，并重启 PyCharm 让新的 PATH 生效。", error=True)
        log("自检方式：在 PyCharm 终端执行 `npm -v`，能输出版本号即正常。", error=True)
        return 1

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    spawned: list[subprocess.Popen] = []

    backend = None
    if port_in_use(8000):
        log("Django 已在 8000 端口运行，跳过启动。")
    else:
        backend = subprocess.Popen(
            [sys.executable, "manage.py", "runserver", "127.0.0.1:8000", "--noreload"],
            cwd=ROOT,
            env=env,
        )
        spawned.append(backend)

    frontend = None
    if port_in_use(5173):
        log("Vite 已在 5173 端口运行，跳过启动。")
    else:
        frontend = subprocess.Popen(
            [npm_command, "run", "dev", "--", "--host", "127.0.0.1"],
            cwd=FRONTEND,
            env=env,
            shell=False,
        )
        spawned.append(frontend)

    log(f"Django: http://127.0.0.1:8000  （{'本次启动' if backend else '已在运行'}）")
    log(f"Vite:   http://127.0.0.1:5173  （{'本次启动' if frontend else '已在运行'}）")

    if not spawned:
        log("两个端口都已被占用：本次没有需要启动的服务，启动器直接退出。")
        log("如果页面打不开，先结束占用 8000 / 5173 的进程（任务管理器里结束 python / node），再重新运行。")
        return 0

    log("按 Ctrl+C 停止由本启动器创建的服务。")

    try:
        announced: set[int] = set()
        while True:
            for name, process in (("Django", backend), ("Vite", frontend)):
                if process is not None and process.poll() is not None and id(process) not in announced:
                    announced.add(id(process))
                    log(f"{name} 进程已退出（返回码 {process.returncode}）。", error=True)
            running = [p for p in (backend, frontend) if p is not None and p.poll() is None]
            if not running:
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        log("\n正在停止服务...")
    finally:
        for process in spawned:
            if process.poll() is None:
                process.terminate()
        for process in spawned:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
