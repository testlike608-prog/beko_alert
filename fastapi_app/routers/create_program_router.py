"""Create program CSV page — FastAPI version of the `CreateProgram` blueprint."""

from __future__ import annotations

import os
import re

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

from CreateProgram import PROGRAMS_DIR, _save_csv_file
from helpers import load_tests
from ..core import templates

router = APIRouter(tags=["create_program"])


@router.get("/programs/{filename:path}", name="CreateProgram.download_program")
async def download_program(filename: str):
    # منع أي محاولة للخروج من مجلد البرامج
    safe_name = os.path.basename(filename)
    path = os.path.join(PROGRAMS_DIR, safe_name)
    if not os.path.isfile(path):
        return HTMLResponse("Not found", status_code=404)
    return FileResponse(path, filename=safe_name, media_type="application/octet-stream")


@router.get("/create_program", response_class=HTMLResponse, name="CreateProgram.page_create_program")
async def create_program_page(request: Request):
    return templates.TemplateResponse(
        request,
        "CREATE_PROGRAM_HTML.html",
        {"submitted": False, "errors": None, "tests": load_tests()},
    )


@router.post(
    "/create_program",
    response_class=HTMLResponse,
    name="CreateProgram.page_create_program_post",
)
async def create_program_submit(request: Request):
    tests = load_tests()
    form = await request.form()

    def f(key: str) -> str:
        return (form.get(key) or "").strip()

    sku = f("sku")

    # S1 fields to S1.csv
    ModelName = f("ModelName")
    front_logo = f("front_logo")
    display_logo = f("display_logo")
    color = f("color")
    data_logo = f("data_logo")
    inverter_logo = f("inverter_logo")
    power_logo = f("power_logo")

    # S2 fields to S2.csv
    eva_cover = f("eva_cover")
    drawer_printing = f("drawer_printing")
    color_logo = f("color_logo")
    fan_cover = f("fan_cover")
    shelve_color = f("shelve_color")

    # ------------------------------------------------------------------
    # الاختبارات مبقتش إجبارية.
    #
    # الافتراضي بقى None|00 (نفس اللي الـ UI بيبدأ بيه)، والصف بيتكتب في
    # الـ CSV عادي زي أي اختيار تاني — يعني عدد الصفوف تابت مهما المستخدم
    # ساب كام حقل. اللي فاضل إجباري بس: SKU و Model Name.
    # ------------------------------------------------------------------
    DEFAULT_OPTION = "None|00"

    front_logo = front_logo or DEFAULT_OPTION
    display_logo = display_logo or DEFAULT_OPTION
    color = color or DEFAULT_OPTION
    data_logo = data_logo or DEFAULT_OPTION
    inverter_logo = inverter_logo or DEFAULT_OPTION
    power_logo = power_logo or DEFAULT_OPTION
    eva_cover = eva_cover or DEFAULT_OPTION
    drawer_printing = drawer_printing or DEFAULT_OPTION
    color_logo = color_logo or DEFAULT_OPTION
    fan_cover = fan_cover or DEFAULT_OPTION
    shelve_color = shelve_color or DEFAULT_OPTION

    errors = []
    if not sku:
        errors.append("SKU is required.")
    if not ModelName:
        errors.append("Model Name is required.")

    if errors:
        return templates.TemplateResponse(
            request,
            "CREATE_PROGRAM_HTML.html",
            {
                "errors": errors, "submitted": False, "sku": sku,
                "ModelName": ModelName, "front_logo": front_logo, "display_logo": display_logo,
                "color": color, "data_logo": data_logo, "inverter_logo": inverter_logo,
                "power_logo": power_logo, "eva_cover": eva_cover,
                "drawer_printing": drawer_printing, "color_logo": color_logo,
                "fan_cover": fan_cover, "shelve_color": shelve_color, "tests": tests,
            },
        )

    safe_sku = re.sub(r"[^\w\-]", "", sku)
    filename_s1 = f"{safe_sku}S1.csv"
    filename_s2 = f"{safe_sku}S2.csv"
    path_s1 = os.path.join(PROGRAMS_DIR, filename_s1)
    path_s2 = os.path.join(PROGRAMS_DIR, filename_s2)

    # في نسخة الـ exe المجلد ده ممكن ميكونش موجود. CreateProgram بيعمله
    # وقت الاستيراد، وده تأكيد تاني لو حد مسحه والبرنامج شغال.
    try:
        os.makedirs(PROGRAMS_DIR, exist_ok=True)
    except OSError as exc:  # noqa: BLE001
        print(f"[create_program] تعذّر إنشاء {PROGRAMS_DIR}: {exc}", flush=True)

    try:
        _save_csv_file(path_s1, [
            ("Model Name", ModelName),
            ("Front Logo", front_logo),
            ("Display logo", display_logo),
            ("Color", color),
            ("Data logo", data_logo),
            ("Inverter logo", inverter_logo),
            ("Power logo", power_logo),
        ])
        save_success_s1 = f"S1 saved: {filename_s1}"
    except Exception as exc:  # noqa: BLE001
        save_success_s1 = None
        # كان بيتبلع من غير أي أثر — دلوقتي على الأقل بيظهر في الكونسول
        # وفي صفحة الأخطاء.
        print(f"[create_program] فشل حفظ {path_s1}: {exc}", flush=True)
        errors.append(f"Failed to save {filename_s1}: {exc}")

    try:
        _save_csv_file(path_s2, [
            ("Model Name", ModelName),
            ("Eva cover", eva_cover),
            ("Drawer printing", drawer_printing),
            ("Color logo", color_logo),
            ("Fan cover", fan_cover),
            ("Shelve color", shelve_color),
        ])
        save_success_s2 = f"S2 saved: {filename_s2}"
    except Exception as exc:  # noqa: BLE001
        save_success_s2 = None
        print(f"[create_program] فشل حفظ {path_s2}: {exc}", flush=True)
        errors.append(f"Failed to save {filename_s2}: {exc}")

    # ===============================
    # handle all dynamic tests (fixed + new)
    # ===============================
    for test in tests:
        station = (test.get("station") or "").upper()
        test_name = test.get("name", "")
        field_key = test_name.replace(" ", "_")
        # الاختبار اللي المستخدم مساه زي ما هو بيتكتب None|00 بدل ما يتشال
        # من الملف خالص — عشان أعمدة الـ CSV تفضل تابتة بين البرامج.
        selected_value = form.get(field_key) or DEFAULT_OPTION

        parts = str(selected_value).split("|", 1)
        if len(parts) == 2:
            opt_name, opt_code = parts
        else:
            opt_name, opt_code = parts[0], ""
        target_path = path_s1 if station == "S1" else path_s2
        row = (test_name, f"{opt_name}|{opt_code}" if opt_code else opt_name)

        try:
            _save_csv_file(target_path, [row], append=True)
        except Exception as exc:  # noqa: BLE001
            print(f"Failed saving dynamic test '{test_name}' to {target_path}: {exc}")

    return templates.TemplateResponse(
        request,
        "CREATE_PROGRAM_HTML.html",
        {
            "submitted": True,
            # لو حصل فشل في الحفظ يظهر في نفس بلوك الأخطاء بتاع الصفحة
            # بدل ما المستخدم يفتكر إن كل حاجة اتحفظت.
            "errors": errors or None,
            "sku": sku,
            "ModelName": ModelName,
            "front_logo": front_logo, "display_logo": display_logo, "color": color,
            "data_logo": data_logo, "inverter_logo": inverter_logo, "power_logo": power_logo,
            "eva_cover": eva_cover, "drawer_printing": drawer_printing,
            "color_logo": color_logo, "fan_cover": fan_cover, "shelve_color": shelve_color,
            "save_success_s1": save_success_s1, "save_success_s2": save_success_s2,
            "filename_s1": filename_s1, "filename_s2": filename_s2, "tests": tests,
        },
    )
