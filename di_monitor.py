"""
di_monitor.py  -  مراقب مباشر لكل مداخل الـ Digital Input.

سكريبت مستقل تمامًا: مش بيستورد أي حاجة من المشروع، ومش بيكتب أي أمر
على الموديول — قراءة بس. الهدف منه إنك تتأكدي إن الحساسات نفسها سليمة
قبل ما تحكمي على الكود.

بيبعت أمر Modbus واحد (Read Discrete Inputs) بيرجّع كل المداخل في بايت
واحد، وبيعرض حالتهم لحظة بلحظة مع عدّاد للحواف.

التشغيل:
    python di_monitor.py                 # بيقرا config.json من نفس الفولدر
    python di_monitor.py --ip 192.168.1.30 --port 502
    python di_monitor.py --count 16      # لو عايزة تشوفي مداخل أكتر
    python di_monitor.py --raw           # يطبع الفريم كامل hex كمان

بيقف بـ Ctrl+C وبيطبّع ملخص.

مهم: لازم برنامج البيكو يكون مقفول وانتي بتشغلي دا. الاتنين مع بعض
هيتخانقوا على نفس الموديول.
"""

import argparse
import json
import os
import socket
import sys
import time

DEFAULT_IP = "192.168.1.30"
DEFAULT_PORT = 502

# ----------------------------------------------------------------------
# قراءة الإعدادات من config.json (نفس الملف اللي البرنامج بيستخدمه)
# ----------------------------------------------------------------------


def load_config():
    """بترجع (ip, port, {عنوان: اسم}) من config.json لو موجود."""
    ip, port, names = DEFAULT_IP, DEFAULT_PORT, {}

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as exc:
        print(f"[!] could not read config.json ({exc}) - using defaults")
        return ip, port, names

    try:
        ep = cfg["endpoints"]["io_read"]
        ip, port = ep["ip"], int(ep["port"])
    except Exception:
        pass

    for key, addr in (cfg.get("io_mapping") or {}).items():
        if key.startswith("READ_DI") and isinstance(addr, int):
            names[addr] = key

    return ip, port, names


# ----------------------------------------------------------------------
# Modbus
# ----------------------------------------------------------------------

_tid = 0


def build_read_command(start, count):
    """
    Read Discrete Inputs (FC 02).

        TID(2) + Proto(2) + Length(2) + Unit(1) + FC(1) + Start(2) + Count(2)

    الـ Transaction ID بيزيد كل مرة عشان نقدر نتأكد إن الرد دا رد الطلب
    ده بالظبط، مش رد متأخر من طلب قديم.
    """
    global _tid
    _tid = (_tid % 0xFFFF) + 1
    frame = f"{_tid:04X}" + "0000" + "0006" + "01" + "02"
    frame += f"{start:04X}" + f"{count:04X}"
    return bytes.fromhex(frame), _tid.to_bytes(2, "big")


def recv_exactly(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionResetError("module closed the connection")
        buf += chunk
    return buf


def read_frame(sock):
    """بتقرا فريم Modbus كامل بالطول المكتوب في الهيدر."""
    head = recv_exactly(sock, 6)
    length = int.from_bytes(head[4:6], "big")
    if not (1 <= length <= 253):
        raise ValueError(f"bad MBAP length {length}")
    return head + recv_exactly(sock, length)


def read_inputs(sock, start, count):
    """
    بترجّع (dict{عنوان: 0/1}, raw_frame) أو (None, سبب الفشل).
    """
    cmd, expected_tid = build_read_command(start, count)
    sock.sendall(cmd)

    for _ in range(8):
        resp = read_frame(sock)
        if resp[:2] == expected_tid:
            break
        # رد متأخر من طلب قديم - نرميه ونكمّل
    else:
        return None, "could not resync (transaction id mismatch)"

    fc = resp[7]
    if fc == 0x82:
        return None, f"modbus exception {resp[8]:#04x} (address range too wide?)"
    if fc != 0x02:
        return None, f"unexpected function code {fc:#04x}"

    byte_count = resp[8]
    data = resp[9:9 + byte_count]
    if len(data) != byte_count:
        return None, "short frame"

    # أول بايت فيه أقل العناوين، وأقل بِت فيه هو عنوان البداية
    bits = int.from_bytes(data, "little")
    return {start + i: (bits >> i) & 1 for i in range(count)}, resp


# ----------------------------------------------------------------------
# العرض
# ----------------------------------------------------------------------


def label(addr, names):
    name = names.get(addr)
    return f"DI@{addr}" + (f" ({name})" if name else "")


def main():
    cfg_ip, cfg_port, names = load_config()

    ap = argparse.ArgumentParser(description="Live monitor for all digital inputs")
    ap.add_argument("--ip", default=cfg_ip)
    ap.add_argument("--port", type=int, default=cfg_port)
    ap.add_argument("--start", type=int, default=0, help="first input address")
    ap.add_argument("--count", type=int, default=None,
                    help="how many inputs to read (default: covers config.json)")
    ap.add_argument("--interval", type=float, default=0.1, help="seconds between reads")
    ap.add_argument("--raw", action="store_true", help="also print the raw hex frame")
    args = ap.parse_args()

    count = args.count
    if count is None:
        count = (max(names) - args.start + 1) if names else 8
    count = max(1, min(count, 64))

    print(f"connecting to {args.ip}:{args.port} ...")
    try:
        sock = socket.create_connection((args.ip, args.port), timeout=2)
    except Exception as exc:
        print(f"[x] connection failed: {exc}")
        print("    - is the beko program still running? close it first.")
        print("    - is the I/O module powered and on the same subnet?")
        return 1
    sock.settimeout(2)
    print(f"connected. reading {count} inputs from address {args.start}")
    if names:
        print("mapping: " + ", ".join(f"{a}={n}" for a, n in sorted(names.items())))
    print("press Ctrl+C to stop\n")

    addresses = list(range(args.start, args.start + count))
    header = "  ".join(f"{a:>2}" for a in addresses)
    print(f"{'byte':>6}  {'bits':>16}   {header}")
    print("-" * (26 + 4 * count))

    last = None
    edges = {a: {"rise": 0, "fall": 0} for a in addresses}
    reads = fails = 0
    started = time.time()

    try:
        while True:
            try:
                state, info = read_inputs(sock, args.start, count)
            except socket.timeout:
                fails += 1
                print("  ... timeout (no reply within 2s)")
                time.sleep(args.interval)
                continue
            except Exception as exc:
                print(f"  ... read error: {exc}")
                break

            if state is None:
                fails += 1
                print(f"  ... {info}")
                time.sleep(args.interval)
                continue

            reads += 1

            if last is not None:
                for a in addresses:
                    if state[a] == 1 and last[a] == 0:
                        edges[a]["rise"] += 1
                        print(f"  >>> RISING  EDGE on {label(a, names)}   "
                              f"(#{edges[a]['rise']})")
                    elif state[a] == 0 and last[a] == 1:
                        edges[a]["fall"] += 1
                        print(f"  <<< falling edge on {label(a, names)}")

            byte0 = sum((state[a] << i) for i, a in enumerate(addresses)) & 0xFF
            row = "  ".join(f"{state[a]:>2}" for a in addresses)
            line = f"{byte0:>#6x}  {byte0:>16_b}   {row}"
            if args.raw:
                line += f"   raw={info.hex()}"
            print(line)

            last = state
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n\nstopped by user")
    finally:
        try:
            sock.close()
        except Exception:
            pass

    elapsed = time.time() - started
    print("\n" + "=" * 50)
    print(f"duration      : {elapsed:.1f}s")
    print(f"good reads    : {reads}"
          + (f"  ({reads / elapsed:.1f}/s)" if elapsed > 0 else ""))
    print(f"failed reads  : {fails}")
    print()
    for a in addresses:
        r, f = edges[a]["rise"], edges[a]["fall"]
        if r or f:
            print(f"  {label(a, names):<22} rising={r:<4} falling={f}")
    print("=" * 50)
    print()
    print("ماذا تتوقعين:")
    print("  - حساس فاضي ومحدش قدامه  -> 0 ثابت، صفر حواف")
    print("  - تلاجة واقفة قدام الحساس -> 1 ثابت، حافة صاعدة واحدة بس")
    print("  - لو البِت بيتذبذب والتلاجة ساكنة -> المشكلة في الحساس أو")
    print("    التوصيلة نفسها، مش في الكود، ومحتاجة debounce")
    return 0


if __name__ == "__main__":
    sys.exit(main())
