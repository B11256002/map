import os
from flask import Flask, render_template, request, jsonify
from supabase import create_client
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("尚未設定 SUPABASE_URL 或 SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# 🚦 設定全球通用的黃燈秒數
YELLOW_TIME = 3 

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/add-light", methods=["POST"])
def add_light():
    try:
        data = request.get_json()
        name = data.get("name")
        lat = data.get("lat")
        lng = data.get("lng")
        phases = data.get("phases") 

        if not name or not lat or not lng or not phases or not isinstance(phases, list):
            return jsonify({"error": "缺少必要參數或時相格式錯誤"}), 400

        cycle_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        new_light = {
            "name": name,
            "lat": lat,
            "lng": lng,
            "cycle_start": cycle_start,
            "phases": phases 
        }

        response = supabase.table("traffic_lights").insert(new_light).execute()
        return jsonify({"message": "新增成功！", "data": response.data}), 201

    except Exception as e:
        return jsonify({"error": "新增失敗", "details": str(e)}), 500

# app.py 裡面的 /traffic-lights 改成這樣：
@app.route("/traffic-lights")
def traffic_lights():
    try:
        response = supabase.table("traffic_lights").select("*").execute()
        return jsonify(response.data) # 直接把原始資料丟給前端
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/route")
def route():
    start = request.args.get("start")
    end = request.args.get("end")
    if not start or not end: return jsonify({"error": "缺少參數"}), 400
    try:
        res = requests.get(f"https://router.project-osrm.org/route/v1/driving/{start};{end}?overview=full&geometries=geojson", timeout=5)
        res.raise_for_status() 
        return jsonify(res.json())
    except:
        return jsonify({"error": "規劃錯誤"}), 502

if __name__ == "__main__":
    app.run(debug=True)