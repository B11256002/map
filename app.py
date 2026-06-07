import os
from flask import Flask, render_template, request, jsonify
from supabase import create_client
from datetime import datetime, timezone, timedelta
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

@app.route("/upload-telemetry", methods=["POST"])
def upload_telemetry():
    try:
        data = request.get_json()
        device_id = data.get("device_id")
        light_name = data.get("light_name")
        direction_angle = data.get("direction") # 這裡是數字字串，例如 "0" 或 "90"
        event = data.get("event")

        if not all([device_id, light_name, event]):
            return jsonify({"error": "缺少必要參數"}), 400

        # 1. 寫入遙測數據 (Telemetry)
        current_time = datetime.now(timezone.utc)
        payload = {
            "device_id": device_id,
            "light_name": light_name,
            "direction": direction_angle,
            "event": event,
            "created_at": current_time.isoformat()
        }
        supabase.table("telemetry_data").insert(payload).execute()

        # ==========================================
        # 🌟 核心魔法：動態校正演算法 (Dynamic Calibration)
        # ==========================================
        if event == "pass" and direction_angle:
            angle = float(direction_angle)
            
            # (A) 將 360 度轉換為精準的「單向」與「雙向」關鍵字
            # 我們設定 +/- 45 度的容錯範圍
            if 45 <= angle < 135:
                # 朝東：代表西往東開
                keywords = ["西往東", "東西"]
            elif 135 <= angle < 225:
                # 朝南：代表北往南開
                keywords = ["北往南", "南北"]
            elif 225 <= angle < 315:
                # 朝西：代表東往西開
                keywords = ["東往西", "東西"]
            else:
                # 朝北 (315~360 或 0~45)：代表南往北開
                keywords = ["南往北", "南北"]

            # (B) 從資料庫抓取該路口的設定
            light_res = supabase.table("traffic_lights").select("*").eq("name", light_name).execute()
            if light_res.data:
                light = light_res.data[0]
                phases = light.get("phases", [])
                
                # (C) 智慧比對：只要時相名稱包含我們推測的關鍵字，就判定命中！
                target_idx = -1
                for i, p in enumerate(phases):
                    # any() 會檢查 keywords 裡的詞，有沒有出現在 p["direction"] 裡面
                    if any(kw in p["direction"] for kw in keywords):
                        target_idx = i
                        break
                
                if target_idx != -1:
                    # (D) 計算從週期開始，到這個「目標時相」亮綠燈，中間經過了幾秒？
                    offset_to_green = 0
                    for i in range(target_idx):
                        offset_to_green += phases[i]["green_time"] + YELLOW_TIME

                    if event == "pass":
                        # 【校正為綠燈】假設「現在」是該方向綠燈亮起的第 2 秒
                        new_cycle_start = current_time - timedelta(seconds=(offset_to_green + 2))
                        action_msg = "🟢 綠燈"

                    elif event == "stop":
                        # 【校正為紅燈】既然車子停了，代表該方向的綠燈「剛剛結束」，下一個方向的綠燈亮起了。
                        # 所以我們要把時間軸，推移到該方向的「綠燈+黃燈」剛好跑完的那一秒。
                        target_phase_duration = phases[target_idx]["green_time"] + YELLOW_TIME
                        offset_to_red = offset_to_green + target_phase_duration

                        # 假設紅燈剛亮起 1 秒
                        new_cycle_start = current_time - timedelta(seconds=(offset_to_red + 1))
                        action_msg = "🔴 紅燈"
                    
                    # (E) 更新資料庫！寫入新的時間基準點
                    new_time_str = new_cycle_start.strftime("%Y-%m-%dT%H:%M:%SZ")
                    supabase.table("traffic_lights").update({"cycle_start": new_time_str}).eq("name", light_name).execute()
                    
                    print(f"✨ 觸發自動校正！路口: {light_name} | {keywords[0]} 強制切換為 {action_msg}")

        return jsonify({"message": "遙測資料接收成功，並執行校正評估"}), 201

    except Exception as e:
        print(f"遙測接收或校正失敗: {e}")
        return jsonify({"error": "伺服器錯誤", "details": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)