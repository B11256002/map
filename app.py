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
    raise ValueError("尚未設定 SUPABASE_URL 或 SUPABASE_KEY 環境變數")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

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
        phases = data.get("phases") # 接收前端傳來的 JSON 陣列

        # 基礎防呆：確保有名字、座標，且時相必須是陣列格式
        if not name or not lat or not lng or not phases or not isinstance(phases, list):
            return jsonify({"error": "缺少必要參數或時相格式錯誤"}), 400

        cycle_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        new_light = {
            "name": name,
            "lat": lat,
            "lng": lng,
            "cycle_start": cycle_start,
            "phases": phases # 直接寫入 Supabase 的 JSONB 欄位
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
        return jsonify({"error": "無法連接到資料庫", "details": str(e)}), 500

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

            # 1. 計算總週期
            total_time = sum(p.get("green_time", 0) for p in phases)
            if total_time <= 0: continue

            current_time_in_cycle = elapsed % total_time

            # 2. 找出現在是哪個時相 (誰是綠燈)
            accumulated = 0
            active_idx = 0
            for i, p in enumerate(phases):
                if current_time_in_cycle < accumulated + p["green_time"]:
                    active_idx = i
                    break
                accumulated += p["green_time"]

            # 當前綠燈剩餘時間
            active_rem = (accumulated + phases[active_idx]["green_time"]) - current_time_in_cycle

            # 3. 結算所有方向的狀態與秒數
            processed_phases = []
            for i, p in enumerate(phases):
                if i == active_idx:
                    # 綠燈方向
                    processed_phases.append({
                        "direction": p["direction"],
                        "status": "green",
                        "remain": int(active_rem)
                    })
                else:
                    # 紅燈方向：需要等待「當前綠燈剩餘時間」+「中間其他方向的綠燈時間」
                    wait_time = active_rem
                    curr_walk = (active_idx + 1) % len(phases)
                    while curr_walk != i:
                        wait_time += phases[curr_walk]["green_time"]
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
                "phases": processed_phases # 回傳計算完畢的陣列
            })
            
        except Exception as e:
            print(f"計算燈號發生錯誤: {e}")
            continue

    return jsonify(result)

@app.route("/route")
def route():
    start = request.args.get("start")
    end = request.args.get("end")
    if not start or not end:
        return jsonify({"error": "缺少 'start' 或 'end' 參數"}), 400

    url = f"https://router.project-osrm.org/route/v1/driving/{start};{end}?overview=full&geometries=geojson"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status() 
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": "路徑規劃服務發生錯誤"}), 502

if __name__ == "__main__":
    app.run(debug=True)