import os
import json
import time
import requests
import datetime
import sys
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL", 
    "https://discord.com/api/webhooks/1515537831999700993/lWDon1h2oKBm7vRjwX5dZmKn1hPbUYFmgxySP-aZERk2mOgbCRiIWNjohRUtmNHJXw3i"
)
LOCAL_CARD_URL = "http://127.0.0.1:8000/static/mobile_card.html"

def generate_screenshot(day="today"):
    print(f"[DISCORD] 正在启动 Playwright 生成天气预报截图 (天数: {day})...")
    os.makedirs("cache", exist_ok=True)
    screenshot_path = f"cache/weather_mobile_{day}.png"
    
    url = LOCAL_CARD_URL
    if day == "tomorrow":
        url = f"{LOCAL_CARD_URL}?day=tomorrow"
        
    with sync_playwright() as p:
        # 启动 headless 浏览器
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = browser.new_context(
            viewport={"width": 430, "height": 950},
            device_scale_factor=2 # 生成 2x 双倍分辨率，保证视网膜屏幕高清显示
        )
        page = context.new_page()
        
        try:
            page.on("console", lambda msg: print(f"[PAGE CONSOLE] {msg.type}: {msg.text}"))
            page.on("pageerror", lambda err: print(f"[PAGE ERROR] {err}"))
            
            page.goto(url, wait_until="networkidle")
            # 额外等待前端接口请求与 SVG 动画绘制完成
            page.wait_for_timeout(2000)
            
            # 定位卡片容器元素
            card_element = page.locator("#mobile-weather-card")
            if card_element.count() > 0:
                card_element.screenshot(path=screenshot_path)
                print(f"[DISCORD] 截图已成功保存至 {screenshot_path}")
                return True
            else:
                print("[DISCORD ERROR] 未能在页面中找到 #mobile-weather-card 元素")
                return False
        except Exception as e:
            print(f"[DISCORD ERROR] 截图过程中发生异常: {e}")
            return False
        finally:
            browser.close()

def send_to_discord(day="today"):
    # 优先使用环境变量或参数传入的 day
    day = os.getenv("PUSH_DAY", day)
    if day not in ["today", "tomorrow"]:
        day = "today"
        
    screenshot_path = f"cache/weather_mobile_{day}.png"
    
    # 1. 尝试生成截图
    has_image = generate_screenshot(day)
    
    # 2. 从本地接口读取当前数据用于富文本拼装
    try:
        r_daily = requests.get("http://127.0.0.1:8000/api/forecast/daily", timeout=5)
        daily_data = r_daily.json()
        r_hourly = requests.get("http://127.0.0.1:8000/api/forecast/hourly", timeout=5)
        hourly_data = r_hourly.json()
    except Exception as e:
        print(f"[DISCORD] 读取本地接口失败，使用兜底文字推送: {e}")
        daily_data = []
        hourly_data = []

    # 3. 提取关键字段
    is_tomorrow = (day == "tomorrow")
    target_idx = 1 if (is_tomorrow and len(daily_data) > 1) else 0
    target_day_data = daily_data[target_idx] if len(daily_data) > target_idx else {}
    
    # 获取对应小时预报
    tomorrow_hours = [h for h in hourly_data if h.get("time_local", "").startswith("明日 ")]
    if is_tomorrow:
        # 明天代表小时数据，取中午 12:00 的预报，没有就取第一个
        noon_hour = next((h for h in tomorrow_hours if "12:00" in h.get("time_local", "")), None)
        curr = noon_hour if noon_hour else (tomorrow_hours[0] if len(tomorrow_hours) > 0 else {})
    else:
        curr = hourly_data[0] if len(hourly_data) > 0 else {}
    
    temp_min = target_day_data.get("temperature_min", "--")
    temp_max = target_day_data.get("temperature_max", "--")
    precip_text = target_day_data.get("precipitation_text", "-")
    wind_speed = target_day_data.get("wind_speed_text", "--") if is_tomorrow else curr.get("wind_speed", "--")
    cape_risk = curr.get("cape_risk", "无风险")
    laundry_idx = target_day_data.get("laundry_index", "极速晾晒 (干燥防霉)")
    heat_alert = target_day_data.get("heat_alert", "温和舒适")
    aqi_mean = target_day_data.get("aqi_mean", 50)
    uv_max = target_day_data.get("uv_max", 2)
    soil_ms = target_day_data.get("soil_moisture_mean", 30)

    # 4. 构建 Discord Embed 负载
    if is_tomorrow:
        title = "🔔 诸暨市明日精细天气预报"
        description = f"中国诸暨市明日气象多源物理模型融合预报已生成！明日气温区间为 **{temp_min}°C** ~ **{temp_max}°C**，体感舒适度预测为：**{heat_alert}**。"
        precip_label = "明日累计降水"
        wind_label = "明日风速/阵风"
    else:
        title = "🔔 诸暨市今日多源气象融合预报"
        description = f"中国诸暨市今日气象多源物理模型融合数据已更新！当前实时气温为 **{curr.get('temperature', '--')}°C**，天气状况：**{curr.get('condition', '--')}** (体感 **{curr.get('apparent_temperature', '--')}°C**)。"
        precip_label = "今日累计降水"
        wind_label = "实时风速/阵风"

    embed = {
        "title": title,
        "description": description,
        "color": 960489, # 对应 0x0ea5e9 天空蓝
        "fields": [
            {
                "name": "🌦️ 气温与降水量",
                "value": f"气温区间: `{temp_min}°C` ~ `{temp_max}°C`\n{precip_label}: `{precip_text}`",
                "inline": True
            },
            {
                "name": "💨 风速与强对流",
                "value": f"{wind_label}: `{wind_speed}`" + (f"\n对流天气风险: **{cape_risk}**" if not is_tomorrow else f"\n对流天气风险: **{cape_risk}**"),
                "inline": True
            },
            {
                "name": "🧺 晾晒与闷热度",
                "value": f"防霉晒衣: **{laundry_idx}**\n体感舒适度: `{heat_alert}`",
                "inline": True
            },
            {
                "name": "😷 健康与土壤",
                "value": f"日均空气质量: `AQI {aqi_mean}`\n最强紫外线: `UV {uv_max}` | 土壤湿度: `{soil_ms}%`",
                "inline": True
            }
        ],
        "footer": {
            "text": "数据源: Meteoblue (mLM/MOS) + ECMWF + GribStream GFS"
        },
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

    payload = {}
    files = {}

    if has_image and os.path.exists(screenshot_path):
        # 如果截图存在，以附件形式发送并嵌入 Embed
        embed["image"] = {"url": f"attachment://weather_{day}.png"}
        payload["embeds"] = [embed]
        
        files = {
            "file": (f"weather_{day}.png", open(screenshot_path, "rb"), "image/png"),
            "payload_json": (None, json.dumps(payload))
        }
        print(f"[DISCORD] 发送带图片微件的 Webhook 消息 (天数: {day})...")
    else:
        # 如果截图失败，降级只发送富文本 Embed
        payload["embeds"] = [embed]
        print(f"[DISCORD] 降级发送纯文本 Embed 的 Webhook 消息 (天数: {day})...")
        files = {
            "payload_json": (None, json.dumps(payload))
        }

    # 5. 发送 POST 请求到 Webhook 地址
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, files=files, timeout=20)
        print(f"[DISCORD] Webhook 返回状态码: {r.status_code}")
        if r.status_code in [200, 204]:
            print(f"[DISCORD] 天气推送成功！(天数: {day})")
            return True
        else:
            print(f"[DISCORD ERROR] 推送失败: {r.text}")
            return False
    except Exception as e:
        print(f"[DISCORD ERROR] Webhook 发送异常: {e}")
        return False

if __name__ == "__main__":
    target_day = "today"
    if len(sys.argv) > 1:
        if sys.argv[1] in ["today", "tomorrow"]:
            target_day = sys.argv[1]
    send_to_discord(target_day)
