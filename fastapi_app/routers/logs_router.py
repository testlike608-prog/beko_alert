"""
Logs — تجميع لوجات كل المصادر في مكان واحد للواجهة.

    GET /logs/sources          -> أسماء المصادر المتاحة (تبويب لكل واحد)
    GET /logs?source=&since=   -> الأسطر الجديدة بس من آخر مرة
    GET /logs/files            -> ملفات اللوج اليومية على الديسك

الفكرة: كل TCPClient بيخزّن لوجه في self._log مع عدّاد تصاعدي
(self._log_seq)، والفيجن ماستر بيخزّن لوجه بالـ timestamp. الراوتر ده
بيعرضهم بشكل موحّد.

الـ incremental مهم: الواجهة بتعمل polling كل ثانية تقريبًا، فبدل ما
نبعت الـ 5000 سطر كل مرة، بنبعت اللي بعد آخر seq المتصفح شافه.

متاحة للمستخدم المسجّل دخوله — اللوج بيساعد أي حد على الخط يشوف
المشكلة، مش محتاج صلاحية dev.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import logstore
import vision_master
from process_control import controller

router = APIRouter(prefix="/logs", tags=["logs"])

VISION_SOURCE = "VisionMaster"
MAX_LIMIT = 1000


def _guard(request: Request):
    if not request.session.get("username"):
        return JSONResponse(
            {"ok": False, "message": "Not authenticated"}, status_code=401
        )
    return None


def _client_sources():
    """
    [(الاسم, الكلاينت)] للعملية الشغالة، أو [] لو لسه متشغّلتش.
    البرنامج ممكن يكون متوقف والواجهة مفتوحة — مش خطأ.
    """
    app = controller.app
    if app is None:
        return []
    try:
        return app.client_sources()
    except Exception:
        return []


def _read_client(client, since: int, limit: int):
    """
    بترجّع (أسطر, آخر seq). القراءة تحت القفل بتاع الكلاينت عشان
    ما نقراش القايمة وهي بتتقص.
    """
    with client._log_lock:
        rows = list(client._log)

    out = []
    last = since
    for seq, ts, level, msg in rows:
        if seq <= since:
            continue
        out.append({"seq": seq, "ts": ts, "level": str(level).upper(), "msg": msg})
        last = max(last, seq)

    if len(out) > limit:
        out = out[-limit:]
    return out, last


def _read_vision(since: int, limit: int):
    """
    الفيجن ماستر مبيخزّنش seq، بيخزّن (ts, level, msg) بس. بنستخدم
    الفهرس في القايمة كـ seq — القايمة بتتقص للنص لما تمتلي، فلو
    الفهرس رجع لورا بنرجّع من الأول بدل ما نسكت.
    """
    try:
        ctrl = vision_master.controller
        with ctrl._log_lock:
            rows = list(ctrl._log)
    except Exception:
        return [], since

    if since > len(rows):
        since = 0

    out = []
    for idx in range(since, len(rows)):
        ts, level, msg = rows[idx]
        out.append({"seq": idx + 1, "ts": ts, "level": str(level).upper(), "msg": msg})

    if len(out) > limit:
        out = out[-limit:]
    return out, len(rows)


@router.get("/sources", name="logs.sources")
def logs_sources(request: Request):
    denied = _guard(request)
    if denied is not None:
        return denied

    names = [name for name, _ in _client_sources()]
    names.append(VISION_SOURCE)
    return JSONResponse({
        "ok": True,
        "sources": names,
        "running": controller.is_running(),
        "file_log": logstore.status(),
    })


@router.get("", name="logs.read")
def logs_read(request: Request, source: str = "", since: int = 0, limit: int = 300):
    denied = _guard(request)
    if denied is not None:
        return denied

    limit = max(1, min(limit, MAX_LIMIT))
    since = max(0, since)

    if source == VISION_SOURCE:
        rows, last = _read_vision(since, limit)
        return JSONResponse({"ok": True, "source": source, "since": last, "rows": rows})

    for name, client in _client_sources():
        if name == source:
            rows, last = _read_client(client, since, limit)
            return JSONResponse(
                {"ok": True, "source": source, "since": last, "rows": rows})

    # المصدر مش موجود: غالبًا العملية متوقفة. مش خطأ — قايمة فاضية.
    return JSONResponse({
        "ok": True,
        "source": source,
        "since": since,
        "rows": [],
        "message": "process is not running" if controller.app is None else "unknown source",
    })


@router.get("/files", name="logs.files")
def logs_files(request: Request):
    denied = _guard(request)
    if denied is not None:
        return denied

    return JSONResponse({"ok": True, "files": logstore.files(), **logstore.status()})
