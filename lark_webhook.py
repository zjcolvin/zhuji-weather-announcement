import os
import sys
import json
import requests
import datetime
from dotenv import load_dotenv

# 导入共享的截图生成函数
try:
    from discord_webhook import generate_screenshot
except ImportError:
    # 兜底：如果无法导入，定义一个空函数
    def generate_screenshot(day="today"):
        return os.path.exists(f"cache/weather_mobile_{day}.png")

load_dotenv()

LARK_WEBHOOK_URL = os.getenv("LARK_WEBHOOK_URL")

def upload_to_catbox(file_path):
    # 优先使用 Catbox (相对稳定)
    print(f"[LARK] 正在上传本地图片 {file_path} 至 Catbox 图床...")
    try:
        url = "https://catbox.moe/user/api.php"
        data = {"reqtype": "fileupload"}
        with open(file_path, "rb") as f:
            files = {"fileToUpload": f}
            r = requests.post(url, data=data, files=files, timeout=15)
        if r.status_code == 200 and r.text.strip().startswith("http"):
            file_url = r.text.strip()
            print(f"[LARK] Catbox 上传成功: {file_url}")
            return file_url
    except Exception as e:
        print(f"[LARK WARNING] Catbox 上传失败或超时: {e}")

    # 备用使用 Litterbox (临时图床，24小时自动清理)
    print(f"[LARK] 正在尝试备用图床 Litterbox (24小时过期)...")
    try:
        url = "https://litterbox.catbox.moe/resources/internals/api.php"
        data = {
            "reqtype": "fileupload",
            "time": "24h"
        }
        with open(file_path, "rb") as f:
            files = {"fileToUpload": f}
            r = requests.post(url, data=data, files=files, timeout=15)
        if r.status_code == 200 and r.text.strip().startswith("http"):
            file_url = r.text.strip()
            print(f"[LARK] Litterbox 备用图床上传成功: {file_url}")
            return file_url
        else:
            print(f"[LARK ERROR] Litterbox 上传失败，HTTP 状态码: {r.status_code}")
            return None
    except Exception as e:
        print(f"[LARK ERROR] Litterbox 上传发生异常: {e}")
        return None

def send_to_lark(day="today"):
    # 优先使用环境变量或参数传入的 day
    day = os.getenv("PUSH_DAY", day)
    if day not in ["today", "tomorrow"]:
        day = "today"
        
    if not LARK_WEBHOOK_URL:
        print("[LARK ERROR] LARK_WEBHOOK_URL 未在环境变量或 .env 文件中配置")
        return False

    screenshot_path = f"cache/weather_mobile_{day}.png"
    
    # 1. 生成截图
    has_image = generate_screenshot(day)
    
    # 2. 上传到临时图床以获取公网 URL (飞书消息卡片 markdown 引入外部图片要求公网链接)
    image_url = None
    if has_image and os.path.exists(screenshot_path):
        image_url = upload_to_catbox(screenshot_path)
    
    # 3. 从本地接口读取当前数据用于消息拼装
    try:
        r_daily = requests.get("http://127.0.0.1:8000/api/forecast/daily", timeout=5)
        daily_data = r_daily.json()
        r_hourly = requests.get("http://127.0.0.1:8000/api/forecast/hourly", timeout=5)
        hourly_data = r_hourly.json()
    except Exception as e:
        print(f"[LARK] 读取本地接口失败，使用空/缺省数据: {e}")
        daily_data = []
        hourly_data = []

    # 4. 提取关键字段
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

    # 确定消息卡片头部配色模板 (template)
    header_template = "blue"
    condition_lower = curr.get("condition", "").lower()
    
    # 如果有雨/强对流或者禁止晾晒，采用警告色
    if "雨" in condition_lower or "雷" in condition_lower:
        header_template = "orange"
    if "禁止" in laundry_idx:
        header_template = "carmine" # 胭脂红，表现警示或雨天

    # 构建 7 日大盘极简 Markdown 列表
    trend_lines = []
    for d in daily_data[:7]:
        w = d.get("weekday", "")
        t_n = d.get("temperature_min", "--")
        t_x = d.get("temperature_max", "--")
        p_t = d.get("precipitation_text", "0.0 mm")
        cond_text = d.get("condition_text", "晴")
        trend_lines.append(f"• **{w}**: `{t_n}°C` ~ `{t_x}°C` | {cond_text} ({p_t})")
    trend_text = "\n".join(trend_lines)

    # 5. 组装飞书 v2 版消息卡片 JSON
    title_text = "🔔 诸暨市明日精细天气预报" if is_tomorrow else "🌤️ 诸暨今日多源气象融合预报"
    time_str = datetime.datetime.now().strftime("%m-%d %H:%M")
    
    card_elements = []
    
    # 实时温度小结
    if is_tomorrow:
        card_elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**预报天数**: <font color='green'>**明日 (24小时精细预报)**</font> | **气象状况**: 明日多源物理模型融合已更新"
            }
        })
    else:
        card_elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**实时温度**: <font color='green'>**{curr.get('temperature', '--')}°C**</font> (体感 **{curr.get('apparent_temperature', '--')}°C**) | **当前天气**: `{curr.get('condition', '--')}`"
            }
        })
        
    card_elements.append({"tag": "hr"})
    
    # 四宫格核心指标 Grid Fields
    card_elements.append({
        "tag": "div",
        "fields": [
            {
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"🌡️ **气温区间**\n`{temp_min}°C` ~ `{temp_max}°C`"
                }
            },
            {
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"🧺 **防霉晒衣**\n**{laundry_idx}**"
                }
            },
            {
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"🌪️ **风速与对流**\n风力 `{wind_speed}` | 对流 **{cape_risk}**"
                }
            },
            {
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"😷 **健康与环境**\nAQI `{aqi_mean}` | 紫外线最高 `UV {uv_max}`"
                }
            }
        ]
    })
    
    card_elements.append({"tag": "hr"})
    
    # 嵌入截图趋势图
    if image_url:
        card_elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"📊 **气温与降水曲线趋势图 (手机卡片)**:\n![天气趋势]({image_url})"
            }
        })
        card_elements.append({"tag": "hr"})
    else:
        print("[LARK WARNING] 缺少公网图片 URL，卡片将不显示截图组件")
        
    # 7 日天气简报
    card_elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": f"📈 **7日天气变化趋势大盘**\n{trend_text}"
        }
    })
    
    card_elements.append({"tag": "hr"})
    
    # 脚注与时间戳
    card_elements.append({
        "tag": "note",
        "elements": [
            {
                "tag": "plain_text",
                "content": f"数据源: Meteoblue (mLM/MOS) + ECMWF + GribStream GFS | 更新时间: {time_str}"
            }
        ]
    })

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {
                "wide_screen_mode": True,
                "enable_forward": True
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": title_text
                },
                "template": header_template
            },
            "elements": card_elements
        }
    }

    # 6. 发送 POST 请求到 Webhook 地址
    print(f"[LARK] 正在发送 Webhook 消息至飞书/Lark (天数: {day})...")
    try:
        headers = {"Content-Type": "application/json"}
        r = requests.post(LARK_WEBHOOK_URL, headers=headers, data=json.dumps(payload), timeout=25)
        print(f"[LARK] Webhook 返回状态码: {r.status_code}")
        print(f"[LARK] 响应数据: {r.text}")
        if r.status_code == 200:
            print(f"[LARK] 天气推送成功！(天数: {day})")
            return True
        else:
            print(f"[LARK ERROR] 推送失败，返回: {r.text}")
            return False
    except Exception as e:
        print(f"[LARK ERROR] Webhook 发送发生异常: {e}")
        return False

if __name__ == "__main__":
    target_day = "today"
    if len(sys.argv) > 1:
        if sys.argv[1] in ["today", "tomorrow"]:
            target_day = sys.argv[1]
    send_to_lark(target_day)
