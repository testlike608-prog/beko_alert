"""
logstore
--------
ملف لوج يومي جنب الـ exe.

ليه؟ اللوج اللي في الرامة (TCPClient._log و VisionMasterController._log)
محدود بعدد أسطر وبيتقص لما يمتلي، وبيضيع خالص لما البرنامج يتقفل. يعني
لو الخط وقف الساعة 3 الفجر وحد قفل البرنامج الصبح، الدليل راح.

الملف ده بيكتب كل سطر لوج على الديسك:

    <BASE_DIR>/logs/beko-2026-09-22.log

ملف لكل يوم، وبيمسح الملفات الأقدم من RETENTION_DAYS تلقائيًا.

مبادئ التصميم:
  - الكتابة مش المفروض توقف السيكونس أبدًا. أي استثناء هنا بيتبلع،
    والكتابة بتحصل في ثريد لوحده من كيو، فالـ _log_add بترجع فورًا.
  - الكيو محدود. لو البرنامج بيولّد لوج أسرع من الديسك، بنرمي الأقدم
    ونسجّل كام سطر اترمى بدل ما الرامة تكبر من غير حد.
  - بيشتغل عادي لو الفولدر مش قابل للكتابة — بيوقف الكتابة وبس.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from datetime import datetime, timedelta

RETENTION_DAYS = 14
MAX_PENDING = 20000          # أسطر مستنية الكتابة قبل ما نبدأ نرمي
FLUSH_EVERY = 0.5            # ثانية


def _base_dir() -> str:
    """
    نفس منطق helpers.BASE_DIR: جنب الـ exe مش جوه الحزمة.
    مكرر هنا عن قصد عشان الموديول ده ما يعتمدش على أي حاجة تانية
    (helpers بتستورد ClientsClass، وده كان هيعمل دايرة).
    """
    try:
        return os.path.normpath(__compiled__.containing_dir)  # type: ignore[name-defined]  # noqa: F821
    except NameError:
        return os.path.dirname(os.path.abspath(__file__))


LOG_DIR = os.path.join(_base_dir(), "logs")


class _LogStore:
    def __init__(self):
        self._queue: "queue.Queue[tuple]" = queue.Queue(maxsize=MAX_PENDING)
        self._thread = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._handle = None
        self._handle_day = None
        self._dropped = 0
        self._disabled = False
        self._last_error = None

    # ------------------------------------------------------------------
    # الواجهة العامة
    # ------------------------------------------------------------------
    def write(self, source: str, level: str, msg: str):
        """بتضيف سطر للكيو وبترجع فورًا. مبترميش استثناءات أبدًا."""
        if self._disabled:
            return
        self._ensure_thread()
        try:
            self._queue.put_nowait((time.time(), source, level, msg))
        except queue.Full:
            # الديسك مش لاحق — نرمي الأقدم عشان الرامة ما تكبرش
            try:
                self._queue.get_nowait()
                self._queue.put_nowait((time.time(), source, level, msg))
            except Exception:
                pass
            self._dropped += 1
        except Exception:
            pass

    def status(self) -> dict:
        return {
            "dir": LOG_DIR,
            "file": self._path_for(datetime.now()),
            "pending": self._queue.qsize(),
            "dropped": self._dropped,
            "disabled": self._disabled,
            "last_error": self._last_error,
        }

    def files(self) -> list:
        """ملفات اللوج الموجودة، الأحدث الأول."""
        try:
            names = [n for n in os.listdir(LOG_DIR)
                     if n.startswith("beko-") and n.endswith(".log")]
        except Exception:
            return []
        out = []
        for name in sorted(names, reverse=True):
            full = os.path.join(LOG_DIR, name)
            try:
                out.append({"name": name, "bytes": os.path.getsize(full)})
            except Exception:
                pass
        return out

    def stop(self):
        self._stop.set()

    # ------------------------------------------------------------------
    # الداخل
    # ------------------------------------------------------------------
    def _ensure_thread(self):
        if self._thread is not None and self._thread.is_alive():
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="beko-logstore", daemon=True)
            self._thread.start()

    def _path_for(self, when: datetime) -> str:
        return os.path.join(LOG_DIR, f"beko-{when:%Y-%m-%d}.log")

    def _open_for(self, when: datetime):
        day = when.date()
        if self._handle is not None and self._handle_day == day:
            return self._handle

        if self._handle is not None:
            try:
                self._handle.close()
            except Exception:
                pass
            self._handle = None

        os.makedirs(LOG_DIR, exist_ok=True)
        self._handle = open(self._path_for(when), "a", encoding="utf-8")
        self._handle_day = day
        self._purge_old()
        return self._handle

    def _purge_old(self):
        """مسح الملفات الأقدم من RETENTION_DAYS."""
        cutoff = datetime.now().date() - timedelta(days=RETENTION_DAYS)
        try:
            names = os.listdir(LOG_DIR)
        except Exception:
            return
        for name in names:
            if not (name.startswith("beko-") and name.endswith(".log")):
                continue
            try:
                stamp = datetime.strptime(name[5:-4], "%Y-%m-%d").date()
            except ValueError:
                continue
            if stamp < cutoff:
                try:
                    os.remove(os.path.join(LOG_DIR, name))
                except Exception:
                    pass

    def _run(self):
        last_flush = time.time()
        while not self._stop.is_set():
            try:
                try:
                    item = self._queue.get(timeout=FLUSH_EVERY)
                except queue.Empty:
                    item = None

                if item is not None:
                    ts, source, level, msg = item
                    when = datetime.fromtimestamp(ts)
                    handle = self._open_for(when)
                    # تنظيف بسيط: سطر واحد لكل رسالة عشان الملف يفضل قابل للفلترة
                    clean = str(msg).replace("\r", " ").replace("\n", " ")
                    handle.write(f"{when:%Y-%m-%d %H:%M:%S.%f}"[:-3]
                                 + f" [{level}] [{source}] {clean}\n")

                now = time.time()
                if self._handle is not None and now - last_flush >= FLUSH_EVERY:
                    self._handle.flush()
                    last_flush = now

            except Exception as exc:
                # فشل الكتابة مش المفروض يوقف البرنامج — بنقفل الكتابة وبس
                self._last_error = str(exc)
                self._disabled = True
                try:
                    if self._handle is not None:
                        self._handle.close()
                except Exception:
                    pass
                self._handle = None
                return

        try:
            if self._handle is not None:
                self._handle.flush()
                self._handle.close()
        except Exception:
            pass


store = _LogStore()


def write(source: str, level: str, msg: str):
    store.write(source, level, msg)


def status() -> dict:
    return store.status()


def files() -> list:
    return store.files()
