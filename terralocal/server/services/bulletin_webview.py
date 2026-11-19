"""Local notice using the frozen Android announcement bridge's ready/close contract."""

import base64
import hashlib

from fastapi.responses import HTMLResponse

SCRIPT = """(function () {
  "use strict";
  function post(type) {
    var bridge = window.HGSDK;
    if (!bridge || typeof bridge.postMessage !== "function") return false;
    bridge.postMessage(JSON.stringify({type: type, data: {}}));
    return true;
  }
  function ready() {
    var close = document.getElementById("close-bulletin");
    close.addEventListener("click", function () { post("close"); });
    // Android's onPageFinished does not finish the announcement's loading UI.
    // WebViewJsBridge.ready -> loadingFinishWithBusiness cancels its wait timer.
    if (post("ready")) close.hidden = false;
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ready, {once: true});
  } else {
    ready();
  }
})();"""

PAGE = ("<!doctype html><html lang=zh-CN><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>TerraLocal 公告</title></head><body><h1>TerraLocal</h1>"
        "<p>本地独立存档。当前版本仍在开发，客户端兼容状态请查看管理面板。</p>"
        '<button id="close-bulletin" type="button" hidden>关闭公告</button>'
        "<script>" + SCRIPT + "</script></body></html>")


def bulletin_response() -> HTMLResponse:
    script_hash = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
    return HTMLResponse(PAGE, headers={
        "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": (
            "default-src 'none'; script-src 'sha256-" + script_hash + "'; "
            "base-uri 'none'; object-src 'none'; frame-ancestors 'none'"),
    })
