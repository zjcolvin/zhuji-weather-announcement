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
    def generate_screenshot(day="today"):
        return os.path.exists(f"cache/weather_mobile_{day}.png")

load_dotenv()

LARK_WEBHOOK_URL = os.getenv("LARK_WEBHOOK_URL")
LARK_APP_ID = os.getenv("LARK_APP_ID")
LARK_APP_SECRET = os.getenv("LARK_APP_SECRET")

def upload_image_to_lark_server(file_path):
    """
    通过飞书开放平台上传图片获取 image_key (方案 A)
    需要企业自建应用的 LARK_APP_ID 和 LARK_APP_SECRET
    """
    if not LARK_APP_ID or not LARK_APP_SECRET:
        print("[LARK] 未配置 LARK_APP_ID / LARK_APP_SECRET，跳过飞书图片上传")
        return None
        
    print("[LARK] 检测到自建应用凭证，正在通过飞书官方 API 获取凭证并上传图片...")
    try:
        # 1. 获取 tenant_access_token
        token_url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
        r = requests.post(token_url, json={
            "app_id": LARK_APP_ID,
            "app_secret": LARK_APP_SECRET
        }, timeout=10)
        token_res = r.json()
        if token_res.get("code") != 0:
            print(f"[LARK ERROR] 获取 tenant_access_token 失败: {token_res.get('msg')}")
            return None
        token = token_res.get("tenant_access_token")
        
        # 2. 上传图片文件到飞书
        upload_url = "https://open.larksuite.com/open-apis/im/v1/images"
        headers = {
            "Authorization": f"Bearer {token}"
        }
        with open(file_path, "rb") as f:
            files = {
                "image_type": (None, "message"),
                "image": f
            }
            r = requests.post(upload_url, headers=headers, files=files, timeout=20)
        upload_res = r.json()
        if upload_res.get("code") != 0:
            print(f"[LARK ERROR] 飞书服务器图片上传失败: {upload_res.get('msg')}")
            return None
            
        image_key = upload_res.get("data", {}).get("image_key")
        print(f"[LARK] 飞书官方图床上传成功，获得 image_key: {image_key}")
        return image_key
    except Exception as e:
        print(f"[LARK ERROR] 飞书官方图片上传发生异常: {e}")
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
    
    # 2. 如果配置了自建应用，则尝试上传获取 image_key (方案 A)
    image_key = None
    if has_image and os.path.exists(screenshot_path):
        image_key = upload_image_to_lark_server(screenshot_path)
    
    # 3. 从本地接口读取当前数据用于消息拼装
    try:
        r_daily = requests.get("http://127.0.0.1:8000/api/forecast/daily", timeout=5)
        daily_data = r_daily.json()
        r_hourly = requests.get("http://127.0.0.1:8000/api/forecast/hourly", timeout=5)
        hourly_data = r_hourly.json()
    except Exception as e:
        print(f"[LARK] 读取本地接口失败，使用兜底模拟数据: {e}")
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
    
    if "雨" in condition_lower or "雷" in condition_lower:
        header_template = "orange"
    if "禁止" in laundry_idx:
        header_template = "carmine" # 胭脂红，表现警示

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
            "tag": "markdown",
            "content": f"**预报天数**: <font color=\"green\">**明日 (24小时精细预报)**</font> | **气象状况**: 明日多源物理模型融合已更新"
        })
    else:
        card_elements.append({
            "tag": "markdown",
            "content": f"**实时温度**: <font color=\"green\">**{curr.get('temperature', '--')}°C**</font> (体感 **{curr.get('apparent_temperature', '--')}°C**) | **当前天气**: `{curr.get('condition', '--')}`"
        })
        
    card_elements.append({"tag": "hr"})
    
    # 飞书标准的双栏分栏布局 (column_set) 代替 v1 fields，适配 schema 2.0
    card_elements.append({
        "tag": "column_set",
        "horizontal_spacing": "medium",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [
                    {
                        "tag": "markdown",
                        "content": f"🌡️ **气温区间**\n`{temp_min}°C` ~ `{temp_max}°C`"
                    },
                    {
                        "tag": "markdown",
                        "content": f"🌪️ **风速与对流**\n风力 `{wind_speed}`\n对流 **{cape_risk}**"
                    }
                ]
            },
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [
                    {
                        "tag": "markdown",
                        "content": f"🧺 **防霉晒衣**\n**{laundry_idx}**"
                    },
                    {
                        "tag": "markdown",
                        "content": f"😷 **健康与环境**\nAQI `{aqi_mean}`\n紫外线最高 `UV {uv_max}`"
                    }
                ]
            }
        ]
    })
    
    card_elements.append({"tag": "hr"})
    
    # 如果通过自建应用成功生成了 image_key，则渲染原生的 img 组件 (方案 A)
    # 如果没有自建应用 (方案 B)，则不渲染任何图片组件，避免加载失效
    if image_key:
        card_elements.append({
            "tag": "img",
            "img_key": image_key,
            "alt": {
                "tag": "plain_text",
                "content": "气温与降水曲线趋势图"
            }
        })
        card_elements.append({"tag": "hr"})
    else:
        print("[LARK] 未获得有效的 image_key，卡片将使用极简模式渲染 (无趋势图片)")
        
    # 7 日天气简报
    card_elements.append({
        "tag": "markdown",
        "content": f"📈 **7日天气变化趋势大盘**\n{trend_text}"
    })
    
    card_elements.append({"tag": "hr"})
    
    # 脚注与时间戳 (在 schema 2.0 中使用普通的 markdown 组件设置灰色文本代替 note)
    card_elements.append({
        "tag": "markdown",
        "content": f"<font color=\"grey\">数据源: Meteoblue (mLM/MOS) + ECMWF + GribStream GFS | 更新时间: {time_str}</font>"
    })

    payload = {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
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
            "body": {
                "elements": card_elements
            }
        }
    }

    # 6. 发送 POST 请求到 Webhook 地址
    print(f"[LARK] 正在向飞书/Lark群推送 Card 2.0 消息 (天数: {day})...")
    try:
        headers = {"Content-Type": "application/json; charset=utf-8"}
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
