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

@app.route("/traffic-lights")
def traffic_lights():
    try:
        response = supabase.table("traffic_lights").select("*").execute()
        data = response.data
    except Exception as e:
        return jsonify({"error": "無法連接資料庫"}), 500

    now = datetime.now(timezone.utc)
    result = []

    for light in data:
        try:
            start_str = light["cycle_start"].replace("Z", "+00:00")
            start_time = datetime.fromisoformat(start_str)
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)

            elapsed = (now - start_time).total_seconds()
            phases = light.get("phases", [])
            if not phases: continue

            # 1. 計算總週期 (每個綠燈都要加上固定的黃燈時間)
            total_time = sum(p.get("green_time", 0) + YELLOW_TIME for p in phases)
            if total_time <= 0: continue

            current_time_in_cycle = elapsed % total_time

            # 2. 找出現在是哪個時相運作中
            accumulated = 0
            active_idx = 0
            for i, p in enumerate(phases):
                phase_duration = p["green_time"] + YELLOW_TIME
                if current_time_in_cycle < accumulated + phase_duration:
                    active_idx = i
                    break
                accumulated += phase_duration

            # 計算該時相已經經過了幾秒
            time_in_active_phase = current_time_in_cycle - accumulated
            active_green_time = phases[active_idx]["green_time"]

            # 判斷是處於該時相的「綠燈期」還是「黃燈期」
            if time_in_active_phase < active_green_time:
                active_status = "green"
                active_rem = active_green_time - time_in_active_phase
            else:
                active_status = "yellow"
                active_rem = (active_green_time + YELLOW_TIME) - time_in_active_phase

            # 3. 結算所有方向的狀態
            processed_phases = []
            for i, p in enumerate(phases):
                if i == active_idx:
                    # 亮綠燈或黃燈的方向
                    processed_phases.append({
                        "direction": p["direction"],
                        "status": active_status,
                        "remain": int(active_rem)
                    })
                else:
                    # 紅燈方向：需要等「目前時相剩下的時間」+「中間其他時相的全部時間(綠+黃)」
                    wait_time = (active_green_time + YELLOW_TIME) - time_in_active_phase
                    curr_walk = (active_idx + 1) % len(phases)
                    while curr_walk != i:
                        wait_time += phases[curr_walk]["green_time"] + YELLOW_TIME
                        curr_walk = (curr_walk + 1) % len(phases)
                    
                    processed_phases.append({
                        "direction": p["direction"],
                        "status": "red",
                        "remain": int(wait_time)
                    })

            result.append({
                "name": light["name"],
                "lat": light["lat"],
                "lng": light["lng"],
                "phases": processed_phases 
            })
            
        except Exception as e:
            continue

    return jsonify(result)

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