from flask import Blueprint, request, jsonify
import json
import os
import ClientsClass as cc

# 1. تعريف البلو برينت بدل Flask app
flags= Blueprint('flags', __name__)

@flags.route('/station1_status')
def station1_status():
    return jsonify({
        "arrived": cc.your_s1_arrived_flag,   # True / False
        "result": cc.your_s1_result,           # 'pass' / 'fail' / None
        "dummy_number": cc.your_s1_dummy,      # string أو None
        "sku_number": cc.your_s1_sku           # string أو None
    })

@flags.route('/station2_status')
def station2_status():
    return jsonify({
        "arrived": cc.your_s2_arrived_flag,
        "result": cc.your_s2_result,
        "dummy_number": cc.your_s2_dummy,
        "sku_number": cc.your_s2_sku
    })