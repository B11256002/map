import os
from flask import Flask, render_template, request, jsonify
from supabase import create_client
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv

# pip install python-dotenv requests flask supabase

# 載入 .env 檔案中的環境變數
load_dotenv()

app = Flask(__name__)

# 從環境變數讀取機密資訊 (避免寫死在程式碼中)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# 確保金鑰存在，否則啟動時直接報錯
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("尚未設定 SUPABASE_URL 或 SUPABASE_KEY 環境變數")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ... 前面的程式碼保持不變 ...

# ... 前面的程式碼保持不變 ...

@app.route("/add-light", methods=["POST"])
def add_light():
    try:
        # 從前端接收 JSON 資料
        data = request.get_json()
        name = data.get("name")
        lat = data.get("lat")
        lng = data.get("lng")
        red_time = int(data.get("red_time", 30))
        green_time = int(data.get("green_time", 30))

        # 基礎防呆驗證
        if not name or not lat or not lng:
            return jsonify({"error": "缺少必要參數 (名稱或經緯度)"}), 400

        # 自動產生「現在」作為週期開始時間 (使用 UTC 時間並轉為 ISO 格式)
        cycle_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 準備要寫入 Supabase 的資料
        new_light = {
            "name": name,
            "lat": lat,
            "lng": lng,
            "red_time": red_time,
            "green_time": green_time,
            "cycle_start": cycle_start
        }

        # 寫入 Supabase 資料庫
        response = supabase.table("traffic_lights").insert(new_light).execute()

        return jsonify({"message": "新增成功！", "data": response.data}), 201

    except Exception as e:
        return jsonify({"error": "新增失敗", "details": str(e)}), 500

# ... 後面的 /route 與 app.run() 保持不變 ...

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/traffic-lights")
def traffic_lights():
    try:
        # 嘗試從資料庫抓取資料
        response = supabase.table("traffic_lights").select("*").execute()
        data = response.data
    except Exception as e:
        # 資料庫連線或查詢失敗時的處理
        return jsonify({"error": "無法連接到資料庫", "details": str(e)}), 500

    # 取得當下時間，並強制加上 UTC 時區 (解決時區報錯問題)
    now = datetime.now(timezone.utc)
    result = []

    for light in data:
        try:
            # 處理 Supabase 回傳的時間格式 (替換 Z 為 +00:00 確保 Python 能正確解析為 UTC)
            start_str = light["cycle_start"].replace("Z", "+00:00")
            start_time = datetime.fromisoformat(start_str)

            # 如果解析出來的時間沒有時區資訊 (Naive)，強制賦予 UTC 時區
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)

            # 計算已經過幾秒
            elapsed = (now - start_time).total_seconds()

            red_time = light["red_time"]
            green_time = light["green_time"]

            # 一個完整週期
            total = red_time + green_time

            # 避免除以零的錯誤 (防呆機制)
            if total <= 0:
                continue

            # 目前在週期哪裡
            current = elapsed % total

            # 判斷紅燈 or 綠燈
            if current < red_time:
                status = "red"
                remain = int(red_time - current)
            else:
                status = "green"
                remain = int(total - current)

            result.append({
                "name": light["name"],
                "lat": light["lat"],
                "lng": light["lng"],
                "status": status,
                "remain": remain
            })
            
        except KeyError as e:
            # 略過資料表欄位缺少的錯誤資料
            print(f"資料缺少必要欄位: {e}")
            continue
        except Exception as e:
            print(f"計算燈號發生錯誤: {e}")
            continue

    return jsonify(result)

@app.route("/route")
def route():
    start = request.args.get("start")
    end = request.args.get("end")

    # 輸入驗證：確保有提供起終點
    if not start or not end:
        return jsonify({"error": "缺少 'start' 或 'end' 參數"}), 400

    url = f"https://router.project-osrm.org/route/v1/driving/{start};{end}?overview=full&geometries=geojson"

    try:
        # 加入 timeout=5，避免 OSRM 伺服器無回應時把 Flask 卡死
        response = requests.get(url, timeout=5)
        
        # 如果 HTTP 狀態碼不是 200 (例如 400, 500)，會自動拋出例外
        response.raise_for_status() 
        
        return jsonify(response.json())
        
    except requests.exceptions.Timeout:
        return jsonify({"error": "路徑規劃服務回應超時 (Timeout)"}), 504
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "路徑規劃服務發生錯誤", "details": str(e)}), 502

if __name__ == "__main__":
    app.run(debug=True)