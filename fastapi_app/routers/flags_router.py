"""Station status flags — FastAPI version of the `flags` blueprint."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

import ClientsClass as cc
from process_control import controller

router = APIRouter(tags=["flags"])


@router.get("/station1_status", name="flags.station1_status")
async def station1_status():
    return JSONResponse(
        {
            "arrived": cc.your_s1_arrived_flag,   # True / False
            "result": cc.your_s1_result,          # 'PASS' / 'FAIL' / None
            "dummy_number": cc.your_s1_dummy,     # string أو None
            "sku_number": cc.your_s1_sku,         # string أو None
            "process_running": controller.is_running(),
        }
    )


@router.get("/station2_status", name="flags.station2_status")
async def station2_status():
    return JSONResponse(
        {
            "arrived": cc.your_s2_arrived_flag,
            "result": cc.your_s2_result,
            "dummy_number": cc.your_s2_dummy,
            "sku_number": cc.your_s2_sku,
            "process_running": controller.is_running(),
        }
    )
