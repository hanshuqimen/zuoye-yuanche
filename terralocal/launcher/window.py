from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

from terralocal.launcher.client_session import ClientConnectionError
from terralocal.launcher.service import ListenerError, ServerGroup
from terralocal.server.services.tls import CertificateError


def launch(settings):
    root = tk.Tk()
    root.title("TerraLocal")
    root.geometry("680x620")
    root.minsize(620, 580)
    root.configure(bg="#f1f4f8")
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("TFrame", background="#f1f4f8")
    style.configure("TLabel", background="#f1f4f8", foreground="#172b40", font=("Microsoft YaHei UI", 10))
    style.configure("Title.TLabel", font=("Segoe UI", 26, "bold"))
    style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=8)
    frame = ttk.Frame(root, padding=26)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="TERRA LOCAL", style="Title.TLabel").pack(anchor="w")
    folder = ttk.Frame(frame)
    folder.pack(fill="x", pady=(4, 10))
    ttk.Label(folder, text="存档目录").pack(side="left", padx=(0, 8))
    folder_path = tk.StringVar(value=str(settings.data_dir))
    ttk.Entry(folder, textvariable=folder_path, state="readonly").pack(side="left", fill="x", expand=True)
    status = tk.StringVar(value="正在启动服务…")
    ttk.Label(frame, textvariable=status, wraplength=560).pack(anchor="w")
    data_status = tk.StringVar()
    ttk.Label(frame, textvariable=data_status, wraplength=560).pack(anchor="w")
    ttk.Label(frame, text=f"客户端配置  {settings.client_profile}", wraplength=560).pack(anchor="w")
    ttk.Label(frame, text=f"游戏服务  {settings.advertised_url}").pack(anchor="w", pady=(14, 5))
    ttk.Label(frame, text=f"管理面板  http://{settings.admin_host}:{settings.admin_port}").pack(anchor="w")
    ttk.Separator(frame).pack(fill="x", pady=18)
    ttk.Label(frame, text="连接测试客户端 · 本地账号").pack(anchor="w", pady=(0, 6))
    selected = ttk.Combobox(frame, state="disabled", width=40)
    selected.pack(fill="x")
    connection_status = tk.StringVar(value="服务启动后可选择账号，连接 TerraLocal 测试实例。")
    connection_label = ttk.Label(frame, textvariable=connection_status, wraplength=560)
    connection_buttons = ttk.Frame(frame)
    connection_buttons.pack(fill="x", pady=10)
    connection_label.pack(anchor="w", pady=(0, 8))
    ttk.Label(frame, text="连接其他账号会重新打开游戏。取消自动连接后，已有游戏会话仍可继续。",
              foreground="#66788c", wraplength=560).pack(anchor="w")
    ttk.Label(frame, text="开发版本：完整游玩与长期稳定性验收尚未完成。", foreground="#936514",
              wraplength=560).pack(anchor="w", pady=16)
    buttons = ttk.Frame(frame)
    buttons.pack(side="bottom", fill="x", pady=(8, 0))
    group, events = ServerGroup(settings), queue.Queue()
    state = {"ready": False, "closing": False, "backing_up": False, "accounts": [], "notice": None}

    def worker():
        try:
            group.start()
            events.put(("ready", "服务运行中"))
        except (ListenerError, CertificateError) as exc:
            events.put(("error", str(exc)))
        except Exception:
            events.put(("error", "服务启动失败，请检查设置、端口及服务日志。"))

    def connect_action(command):
        if not state["ready"] or state["closing"] or group.client is None:
            return
        try:
            account_id = None
            if command == "bind":
                index = selected.current()
                if index < 0 or index >= len(state["accounts"]):
                    raise ClientConnectionError("BOUND_ACCOUNT_MISSING", "请选择本地账号；新账号可在管理面板创建。")
                account_id = state["accounts"][index]["id"]
            group.client.request(command, account_id)
            state["notice"] = None
            connection_status.set("正在处理连接操作…")
        except ClientConnectionError as error:
            state["notice"] = str(error)
            connection_status.set(str(error))
            connection_label.configure(foreground="#a43935")

    bind_button = ttk.Button(connection_buttons, text="连接所选账号", command=lambda: connect_action("bind"))
    bind_button.pack(side="left", padx=(0, 8))
    retry_button = ttk.Button(connection_buttons, text="重新连接", command=lambda: connect_action("retry"))
    retry_button.pack(side="left", padx=(0, 8))
    disconnect_button = ttk.Button(connection_buttons, text="取消自动连接", command=lambda: connect_action("disconnect"))
    disconnect_button.pack(side="left")

    def backup_worker():
        try:
            result = group.create_backup()
            message = f"备份已保存 · {result['name']}"
        except Exception as error:
            logging.getLogger("terralocal").error("手动备份失败 %s", type(error).__name__)
            message = "备份失败，请检查数据目录和服务日志。"
        events.put(("backup-finished", message))

    def backup():
        if not state["ready"] or state["closing"] or state["backing_up"]:
            return
        state["backing_up"] = True
        status.set("服务运行中 · 正在备份…")
        set_buttons()
        try:
            threading.Thread(target=backup_worker, name="terralocal-manual-backup", daemon=True).start()
        except RuntimeError:
            events.put(("backup-finished", "备份任务无法启动，请重试。"))

    def set_buttons():
        enabled = state["ready"] and not state["closing"]
        for button in (bind_button, retry_button, disconnect_button, management_button):
            button.configure(state="normal" if enabled else "disabled")
        backup_button.configure(state="normal" if enabled and not state["backing_up"] else "disabled")
        selected.configure(state="readonly" if enabled else "disabled")
        stop_button.configure(state="disabled" if state["closing"] else "normal")

    def stop_worker(failure):
        try:
            group.stop()
            if failure:
                events.put(("failure-cleaned", failure + " 端口和存档锁已释放，请关闭窗口后重新启动。"))
            else:
                events.put(("stopped", None))
        except Exception:
            events.put(("stop-error", "后台任务尚未完全停止，请稍后再次点击停止。"))

    def stop(failure=None):
        if state["closing"]:
            return
        state["closing"], state["ready"] = True, False
        data_status.set("")
        if failure:
            status.set(failure + " 正在释放端口和存档锁…")
        elif state["backing_up"]:
            status.set("等待备份完成后停止服务…")
        else:
            status.set("正在保存并停止服务…")
        set_buttons()
        group.request_stop()
        threading.Thread(target=stop_worker, args=(failure,), name="terralocal-stop", daemon=True).start()

    management_button = ttk.Button(buttons, text="打开管理面板", command=lambda: webbrowser.open(
        f"http://{settings.admin_host}:{settings.admin_port}"))
    management_button.pack(side="left", padx=(0, 10))
    backup_button = ttk.Button(buttons, text="备份", command=backup)
    backup_button.pack(side="left")
    stop_button = ttk.Button(buttons, text="停止", command=stop)
    stop_button.pack(side="right")
    root.protocol("WM_DELETE_WINDOW", stop)

    def check():
        while True:
            try:
                event, message = events.get_nowait()
            except queue.Empty:
                break
            if event == "stopped":
                root.destroy()
                return
            if event == "backup-finished":
                state["backing_up"] = False
                if state["ready"] and not state["closing"]:
                    status.set(f"服务运行中 · {message}")
                continue
            if event in {"stop-error", "failure-cleaned"}:
                state["closing"] = False
                status.set(message)
            elif not state["closing"]:
                state["ready"] = event == "ready"
                status.set(message)
                if state["ready"]:
                    data = group.runtime.data
                    summary = ("游戏数据尚未导入或选择" if data is None else
                               f"游戏数据已加载  {len(data.manifest['tables'])} 张表 · {data.manifest['hash'][:12]}")
                    data_status.set(f"存档库已打开  ·  {summary}")
        if state["ready"] and (name := group.failed_listener()):
            stop(f"{name}意外停止。")
        if state["ready"] and group.client:
            snapshot = group.client.snapshot()
            rows = snapshot["accounts"]
            if rows != state["accounts"]:
                previous = selected.current()
                selected_id = state["accounts"][previous]["id"] if 0 <= previous < len(state["accounts"]) else None
                selected.configure(values=[row["name"] for row in rows])
                state["accounts"] = rows
                index = next((i for i, row in enumerate(rows) if row["id"] == selected_id), None)
                if index is None:
                    index = next((i for i, row in enumerate(rows) if row["name"] == snapshot["account_name"]), 0)
                if rows:
                    selected.current(index)
                else:
                    selected.set("")
            if state["notice"] is None:
                text = snapshot["message"]
                if snapshot["account_name"]:
                    text = snapshot["account_name"] + " · " + text
                connection_status.set(text)
                connection_label.configure(foreground="#a43935" if snapshot["phase"] == "error" else "#172b40")
        set_buttons()
        root.after(250, check)

    threading.Thread(target=worker, name="terralocal-start", daemon=True).start()
    check()
    root.mainloop()
