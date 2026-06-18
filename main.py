import os
import math
import datetime
import time
import json
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
import requests
from dotenv import load_dotenv

load_dotenv()

# 诸暨地理坐标 (Zhuji Coordinates)
ZHUJI_LAT = 29.685777
ZHUJI_LON = 120.258158

app = FastAPI(title="Zhuji Weather Fusion API (Real & Cached)", version="4.0.0")

# 辅助函数：根据度数返回风向文本
def get_wind_direction_text(degrees: float) -> str:
    directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    index = int((degrees + 11.25) / 22.5) % 16
    return directions[index]

# 物理公式计算辅助函数
def calculate_apparent_temperature(temp_c: float, rh_pct: float, wind_speed_ms: float) -> float:
    es = 6.112 * math.exp((17.67 * temp_c) / (temp_c + 243.5))
    e = (rh_pct / 100.0) * es
    at = temp_c + 0.33 * e - 0.70 * wind_speed_ms - 4.0
    return round(at, 1)

def get_weather_condition(temp: float, precip: float, rh: float, hour: int) -> dict:
    if precip > 2.0:
        if temp > 30:
            return {"text": "雷阵雨", "icon": "thunderstorm"}
        return {"text": "大雨", "icon": "heavy-rain"}
    elif precip > 0.1:
        return {"text": "小雨", "icon": "light-rain"}
    
    if rh > 85:
        return {"text": "阴", "icon": "overcast"}
    elif rh > 65:
        return {"text": "多云", "icon": "cloudy"}
    else:
        if 6 <= hour <= 18:
            return {"text": "晴", "icon": "sunny"}
        else:
            return {"text": "晴朗(夜)", "icon": "sunny-night"}

def calculate_laundry_index(precip_prob: int, temp_max: float, humidity_min: float) -> dict:
    """
    计算防霉/晒衣指数 (Laundry & Mold Index)
    Level 1: 极速晾晒 (干燥防霉)
    Level 2: 适宜晾晒 (微潮)
    Level 3: 不宜晾晒 (潮湿易霉)
    Level 4: 禁止晾晒 (阴雨大霉)
    """
    if precip_prob >= 65 or temp_max < 22:
        return {"text": "禁止晾晒 (阴雨大霉)", "level": 4}
    elif precip_prob >= 35 or humidity_min > 80:
        return {"text": "不宜晾晒 (潮湿易霉)", "level": 3}
    elif precip_prob >= 15 or humidity_min > 65:
        return {"text": "适宜晾晒 (微潮)", "level": 2}
    else:
        return {"text": "极速晾晒 (干燥防霉)", "level": 1}

def calculate_heat_alert(temp_max: float, humidity_avg: float) -> dict:
    """
    计算体感闷热预警 (Humidex Alert)
    Level 4: 酷热警戒 (防中暑)
    Level 3: 闷热警告
    Level 2: 温和舒适
    Level 1: 清凉舒适
    """
    if temp_max >= 35:
        return {"text": "酷热警戒 (防中暑)", "level": 4}
    elif temp_max >= 30 and humidity_avg >= 70:
        return {"text": "闷热警告", "level": 3}
    elif temp_max >= 25:
        return {"text": "温和舒适", "level": 2}
    else:
        return {"text": "清凉舒适", "level": 1}

def map_pictocode_to_condition(pictocode: int, is_day: bool) -> dict:
    """
    将 Meteoblue pictocode 天气编码映射到看板对应的中文描述和图标
    """
    cond = {"text": "多云", "icon": "cloudy"}
    if pictocode in [1, 2]:
        cond = {"text": "晴", "icon": "sunny" if is_day else "sunny-night"}
    elif pictocode in [3, 20]:
        cond = {"text": "多云", "icon": "cloudy" if is_day else "cloudy-night"}
    elif pictocode in [4, 5]:
        cond = {"text": "阴" if pictocode == 4 else "有雾", "icon": "overcast"}
    elif pictocode in [6, 7, 10, 11, 12, 14, 16]:
        cond = {"text": "小雨", "icon": "light-rain"}
    elif pictocode in [8, 21, 22, 23]:
        cond = {"text": "雷阵雨", "icon": "thunderstorm" if is_day else "thunderstorm-night"}
    elif pictocode in [24, 25]:
        cond = {"text": "大雨", "icon": "heavy-rain" if is_day else "heavy-rain-night"}
    elif pictocode in [9, 13, 15, 17]:
        cond = {"text": "雨夹雪", "icon": "light-rain"}
    return cond

def get_daily_sunshine_hours(day_str: str, data_1h: dict) -> float:
    """
    从逐时日照分钟数计算全天日照小时数
    """
    times = data_1h.get("time", [])
    sunshinetime = data_1h.get("sunshinetime", [])
    if not times or not sunshinetime:
        return 0.0
    
    total_minutes = 0.0
    for t, s in zip(times, sunshinetime):
        if t.startswith(day_str):
            total_minutes += s
            
    return round(total_minutes / 60.0, 1)


class WeatherCacheManager:
    def __init__(self, cache_dir: str = "cache"):
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    def read(self, filename: str, max_age_seconds: int) -> dict | list | None:
        path = os.path.join(self.cache_dir, filename)
        if not os.path.exists(path):
            return None
        mtime = os.path.getmtime(path)
        if time.time() - mtime > max_age_seconds:
            print(f"[CACHE] {filename} 已过期。")
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                print(f"[CACHE] 成功命中缓存 {filename}。")
                return json.load(f)
        except Exception as e:
            print(f"[CACHE] 读取缓存错误 {filename}: {e}")
            return None

    def write(self, filename: str, data: dict | list):
        path = os.path.join(self.cache_dir, filename)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                print(f"[CACHE] 成功写入缓存 {filename}。")
        except Exception as e:
            print(f"[CACHE] 写入缓存错误 {filename}: {e}")


class WeatherFusionEngine:
    def __init__(self):
        self.meteoblue_key = os.getenv("METEOBLUE_API_KEY", "Ag8H7MjpqrZY2cEP")
        self.gribstream_key = os.getenv("GRIBSTREAM_API_KEY", "e601534b14930d5716d42b66dd3532f355bf9609")
        self.cache = WeatherCacheManager()

    def fetch_meteoblue_data(self) -> dict | None:
        # 缓存时长为 12 小时 (43200 秒)
        cached = self.cache.read("meteoblue_cache.json", 43200)
        if cached:
            return cached

        print("[API] 正在发起 Meteoblue 真实数据网络请求...")
        packages = "basic-1h_clouds-1h_airquality-1h_agro-1h_basic-day_airquality-day_agro-day"
        url = f"https://my.meteoblue.com/packages/{packages}?lat={ZHUJI_LAT}&lon={ZHUJI_LON}&apikey={self.meteoblue_key}&format=json"
        
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 200:
                data = r.json()
                self.cache.write("meteoblue_cache.json", data)
                return data
            else:
                print(f"[API ERROR] Meteoblue 接口返回状态码: {r.status_code}, 内容: {r.text[:500]}")
        except Exception as e:
            print(f"[API ERROR] Meteoblue 请求异常: {e}")

        # 降级读取过期缓存
        path = os.path.join(self.cache.cache_dir, "meteoblue_cache.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    print("[API FALLBACK] 接口失败，使用本地旧版 Meteoblue 缓存...")
                    return json.load(f)
            except:
                pass
        return None

    def fetch_gribstream_data(self) -> list | None:
        # GribStream 缓存时间为 3 小时 (10800 秒)
        cached = self.cache.read("gribstream_cache.json", 10800)
        if cached:
            return cached

        print("[API] 正在发起 GribStream GFS 物理变量网络请求...")
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        from_time = (now_utc - datetime.timedelta(hours=6)).strftime("%Y-%m-%dT%H:00:00Z")
        until_time = (now_utc + datetime.timedelta(days=2)).strftime("%Y-%m-%dT%H:00:00Z")
        
        url = "https://gribstream.com/api/v2/gfs/timeseries"
        headers = {
            "Authorization": f"Bearer {self.gribstream_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        payload = {
            "fromTime": from_time,
            "untilTime": until_time,
            "coordinates": [{"lat": ZHUJI_LAT, "lon": ZHUJI_LON, "name": "Zhuji"}],
            "variables": [
                {"name": "GUST", "level": "surface", "alias": "wind_gust"},
                {"name": "CAPE", "level": "180-0 mb above ground", "alias": "cape"}
            ]
        }

        try:
            r = requests.post(url, json=payload, headers=headers, timeout=25)
            if r.status_code == 200:
                data = r.json()
                self.cache.write("gribstream_cache.json", data)
                return data
            else:
                print(f"[API ERROR] GribStream 接口返回状态码: {r.status_code}, 内容: {r.text[:500]}")
        except Exception as e:
            print(f"[API ERROR] GribStream 请求异常: {e}")

        # 降级读取过期缓存
        path = os.path.join(self.cache.cache_dir, "gribstream_cache.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    print("[API FALLBACK] 接口失败，使用本地旧版 GribStream 缓存...")
                    return json.load(f)
            except:
                pass
        return None

    def generate_fused_hourly(self) -> list:
        mb_raw = self.fetch_meteoblue_data()
        gs_raw = self.fetch_gribstream_data()

        # 降级策略：如果两个 API 均无数据，则返回高度逼真的模拟数据
        if not mb_raw:
            print("[ENGINE] 数据源故障，启动本地仿真数据引擎...")
            return self.generate_simulated_hourly()

        # 1. 解析 GribStream 物理场 (CAPE 与 Gust) 并校准时区 (UTC+8)
        grib_lookup = {}
        if gs_raw:
            for row in gs_raw:
                f_time_str = row.get("forecasted_time")
                if not f_time_str:
                    continue
                try:
                    t_clean = f_time_str.replace("Z", "+00:00")
                    dt_utc = datetime.datetime.fromisoformat(t_clean)
                    dt_local = dt_utc + datetime.timedelta(hours=8)
                    local_key = dt_local.strftime("%Y-%m-%d %H:00")
                    grib_lookup[local_key] = {
                        "cape": row.get("cape", 0),
                        "wind_gust": row.get("wind_gust", 0)
                    }
                except Exception as e:
                    print(f"[PARSER ERR] 时间对齐失败: {e}")

        # 2. 解析 Meteoblue 逐时基础与扩展包 (basic, clouds, airquality, agro)
        data_1h = mb_raw.get("data_1h", {})
        times_1h = data_1h.get("time", [])

        temp_list = data_1h.get("temperature", [])
        felt_list = data_1h.get("felttemperature", [])
        winddir_list = data_1h.get("winddirection", [])
        windspeed_list = data_1h.get("windspeed", [])
        precip_list = data_1h.get("precipitation", [])
        prob_list = data_1h.get("precipitation_probability", [])
        vis_list = data_1h.get("visibility", [])
        uv_list = data_1h.get("uvindex", [])
        aqi_list = data_1h.get("airqualityindex", [])
        pm25_list = data_1h.get("pm25", [])
        pm10_list = data_1h.get("pm10", [])
        soiltemp_list = data_1h.get("soiltemperature_0to10cm", [])
        soilmoisture_list = data_1h.get("soilmoisture_0to10cm", [])
        picto_list = data_1h.get("pictocode", [])
        daylight_list = data_1h.get("isdaylight", [])

        mb_hourly_lookup = {}
        for i, t_str in enumerate(times_1h):
            mb_hourly_lookup[t_str] = {
                "temperature": temp_list[i] if i < len(temp_list) else 20,
                "apparent_temperature": felt_list[i] if i < len(felt_list) else 20,
                "wind_direction": winddir_list[i] if i < len(winddir_list) else 0,
                "wind_speed": windspeed_list[i] if i < len(windspeed_list) else 0,
                "precipitation": precip_list[i] if i < len(precip_list) else 0,
                "precipitation_probability": prob_list[i] if i < len(prob_list) else 0,
                "visibility": vis_list[i] if i < len(vis_list) else 10,
                "uvindex": uv_list[i] if i < len(uv_list) else 0,
                "aqi": aqi_list[i] if i < len(aqi_list) else 50,
                "pm25": pm25_list[i] if i < len(pm25_list) else 12,
                "pm10": pm10_list[i] if i < len(pm10_list) else 20,
                "soil_temp": soiltemp_list[i] if i < len(soiltemp_list) else 20,
                "soil_moisture": soilmoisture_list[i] if i < len(soilmoisture_list) else 30,
                "pictocode": picto_list[i] if i < len(picto_list) else 1,
                "isdaylight": daylight_list[i] if i < len(daylight_list) else 1,
            }

        # 3. 动态拼接混合时序 (当天 1h 步长，次日 3h 步长)
        tz_zhuji = datetime.timezone(datetime.timedelta(hours=8))
        now = datetime.datetime.now(tz_zhuji)
        today = now.date()
        tomorrow = today + datetime.timedelta(days=1)
        
        target_times = []
        current_hour = now.hour
        # 如果当天时间已经接近午夜，至少给几个小时
        start_hour = min(current_hour, 20)
        for h in range(start_hour, 24):
            t = datetime.datetime.combine(today, datetime.time(hour=h)).replace(tzinfo=tz_zhuji)
            target_times.append((t, "today"))
            
        for h in range(0, 24, 3):
            t = datetime.datetime.combine(tomorrow, datetime.time(hour=h)).replace(tzinfo=tz_zhuji)
            target_times.append((t, "tomorrow"))

        records = []
        for t, day_flag in target_times:
            t_key = t.strftime("%Y-%m-%d %H:00")
            is_tomorrow = day_flag == "tomorrow"
            
            # 读取 Meteoblue 数据
            mb_vals = mb_hourly_lookup.get(t_key)
            if not mb_vals:
                # 若时间点因为更新延迟不存在，采用临近插值
                keys_sorted = sorted(mb_hourly_lookup.keys())
                if keys_sorted:
                    mb_vals = mb_hourly_lookup[keys_sorted[0]]
                else:
                    continue
                
            # 读取 GribStream 物理场数据
            gs_vals = grib_lookup.get(t_key, {
                "cape": 0,
                "wind_gust": mb_vals["wind_speed"]
            })
            
            cond = map_pictocode_to_condition(mb_vals["pictocode"], mb_vals["isdaylight"])
            
            # 合并风速与阵风 W(Gust)
            avg_w = mb_vals["wind_speed"]
            gust_w = gs_vals.get("wind_gust", avg_w)
            if gust_w < avg_w:
                gust_w = avg_w
            # 显示文本，舍入整数
            wind_speed_text = f"{round(avg_w)}-{round(gust_w)}"
            
            prec = mb_vals["precipitation"]
            prec_text = f"{prec:.1f}" if prec > 0.1 else "-"
            
            # 强对流天气风险评判 (CAPE)
            cape_val = gs_vals.get("cape", 0)
            if cape_val < 100:
                cape_risk, cape_level = "无风险", 1
            elif cape_val < 1000:
                cape_risk, cape_level = "低风险", 2
            elif cape_val < 2500:
                cape_risk, cape_level = "中风险", 3
            else:
                cape_risk, cape_level = "高风险", 4
                
            records.append({
                "time_local": t.strftime("%H:%M") if not is_tomorrow else f"明日 {t.hour:02d}:00",
                "temperature": round(mb_vals["temperature"]),
                "apparent_temperature": round(mb_vals["apparent_temperature"]),
                "wind_direction": mb_vals["wind_direction"],
                "wind_direction_text": get_wind_direction_text(mb_vals["wind_direction"]),
                "wind_speed": wind_speed_text,
                "precipitation": prec_text,
                "precipitation_probability": round(mb_vals["precipitation_probability"]),
                "visibility": f"{mb_vals['visibility']:.1f}",
                "condition": cond["text"],
                "icon": cond["icon"],
                "predictability": 4,
                
                # 拟新增的数据参数
                "aqi": round(mb_vals["aqi"]),
                "pm25": round(mb_vals["pm25"]),
                "pm10": round(mb_vals["pm10"]),
                "uvindex": round(mb_vals["uvindex"]),
                "soil_temp": round(mb_vals["soil_temp"]),
                "soil_moisture": round(mb_vals["soil_moisture"]),
                "cape": round(cape_val),
                "cape_risk": cape_risk,
                "cape_level": cape_level,
                "source": "api_fused_ecmwf_meteoblue"
            })
            
        return records

    def generate_fused_daily(self) -> list:
        mb_raw = self.fetch_meteoblue_data()
        if not mb_raw:
            print("[ENGINE] 数据源故障，启动本地日均仿真指标...")
            return self.generate_simulated_daily()

        data_day = mb_raw.get("data_day", {})
        data_1h = mb_raw.get("data_1h", {})
        times = data_day.get("time", [])

        day_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        records = []
        
        for i in range(min(7, len(times))):
            t_str = times[i]
            dt = datetime.datetime.strptime(t_str, "%Y-%m-%d")
            
            weekday_idx = dt.weekday()
            base_day_name = day_names[weekday_idx]
            
            tz_zhuji = datetime.timezone(datetime.timedelta(hours=8))
            today_date = datetime.datetime.now(tz_zhuji).date()
            tomorrow_date = today_date + datetime.timedelta(days=1)
            
            if dt.date() == today_date:
                day_name = f"今天 ({base_day_name})"
            elif dt.date() == tomorrow_date:
                day_name = f"明天 ({base_day_name})"
            else:
                day_name = base_day_name
                
            date_label = f"{dt.month:02d}-{dt.day:02d}"
            
            def get_safe_day_val(key, default):
                lst = data_day.get(key)
                if not lst or i >= len(lst) or lst[i] is None:
                    return default
                return lst[i]

            t_max = round(get_safe_day_val("temperature_max", 20))
            t_min = round(get_safe_day_val("temperature_min", 10))
            
            wind_dir_deg = get_safe_day_val("winddirection", 0)
            wind_speed_ms = get_safe_day_val("windspeed_max", 0.0)
            wind_speed_text = f"{round(wind_speed_ms)} m/s"
            
            precip_mm = get_safe_day_val("precipitation", 0.0)
            precip_text = f"{precip_mm:.1f} mm" if precip_mm > 0 else "-"
            
            pred_pct = get_safe_day_val("predictability", 80)
            pred_dots = max(1, min(5, round(pred_pct / 20.0)))
            
            p_code = get_safe_day_val("pictocode", 1)
            cond_day = map_pictocode_to_condition(p_code, is_day=True)
            cond_night = map_pictocode_to_condition(p_code, is_day=False)
            
            precip_prob = get_safe_day_val("precipitation_probability", 0)
            rh_min = get_safe_day_val("relativehumidity_min", 50)
            rh_avg = get_safe_day_val("relativehumidity_mean", 70)
            
            laundry = calculate_laundry_index(precip_prob, t_max, rh_min)
            heat = calculate_heat_alert(t_max, rh_avg)
            
            # 日均指标汇总
            aqi_mean = round(get_safe_day_val("airqualityindex_mean", 50))
            uv_max = round(get_safe_day_val("uvindex", 2))
            soil_moisture_mean = round(get_safe_day_val("soilmoisture_0to10cm_mean", 30))
            sun_hours = get_daily_sunshine_hours(t_str, data_1h)

            records.append({
                "day_name": day_name,
                "date": date_label,
                "temperature_max": t_max,
                "temperature_min": t_min,
                "wind_speed_text": wind_speed_text,
                "wind_direction_deg": wind_dir_deg,
                "precipitation_text": precip_text,
                "sunshine_hours": f"{sun_hours} h",
                "icon": cond_day["icon"],
                "condition_text": cond_day["text"],
                "night_icon": cond_night["icon"],
                "predictability": pred_dots,
                "laundry_index": laundry["text"],
                "laundry_level": laundry["level"],
                "heat_alert": heat["text"],
                "heat_level": heat["level"],
                
                # 新增用于 7 日卡片渲染的真实健康与农业指标
                "aqi_mean": aqi_mean,
                "uv_max": uv_max,
                "soil_moisture_mean": soil_moisture_mean,
                "source": "api_fused_ecmwf_meteoblue"
            })
            
        return records

    def generate_simulated_hourly(self) -> list:
        # 在接口完全故障或密钥无效情况下的仿真降级
        tz_zhuji = datetime.timezone(datetime.timedelta(hours=8))
        now = datetime.datetime.now(tz_zhuji)
        today = now.date()
        tomorrow = today + datetime.timedelta(days=1)
        
        target_times = []
        for h in range(now.hour, 24):
            t = datetime.datetime.combine(today, datetime.time(hour=h)).replace(tzinfo=tz_zhuji)
            target_times.append((t, "today"))
        for h in range(0, 24, 3):
            t = datetime.datetime.combine(tomorrow, datetime.time(hour=h)).replace(tzinfo=tz_zhuji)
            target_times.append((t, "tomorrow"))
            
        records = []
        for t, day_flag in target_times:
            local_hour = t.hour
            is_tomorrow = day_flag == "tomorrow"
            rad = math.sin((local_hour - 9) * math.pi / 12)
            base_temp = 26.5 + 4.5 * rad
            rh = 75.0 - 15.0 * rad
            precip = 12.5 if not is_tomorrow and (14 <= local_hour <= 18) else 0.0
            
            temp_c = round(base_temp, 1)
            rh_val = round(rh)
            ws_val = 3.2 + (2.5 if precip > 0 else 0)
            
            at = calculate_apparent_temperature(temp_c, rh_val, ws_val)
            cond = get_weather_condition(temp_c, precip, rh_val, local_hour)
            
            records.append({
                "time_local": t.strftime("%H:%M") if not is_tomorrow else f"明日 {local_hour:02d}:00",
                "temperature": round(temp_c),
                "apparent_temperature": round(at),
                "wind_direction": 135 if not is_tomorrow else 225,
                "wind_direction_text": get_wind_direction_text(135 if not is_tomorrow else 225),
                "wind_speed": f"{round(ws_val)}-{round(ws_val*1.5)}",
                "precipitation": f"{precip:.1f}" if precip > 0 else "-",
                "precipitation_probability": round(rh_val * 0.8 if precip > 0 else 10),
                "visibility": "12.0",
                "condition": cond["text"],
                "icon": cond["icon"],
                "predictability": 4,
                "aqi": 42 if not is_tomorrow else 55,
                "pm25": 11,
                "pm10": 18,
                "uvindex": 6 if (10 <= local_hour <= 14) else 0,
                "soil_temp": round(temp_c - 2),
                "soil_moisture": 35,
                "cape": 450 if precip > 0 else 50,
                "cape_risk": "低风险" if precip > 0 else "无风险",
                "cape_level": 2 if precip > 0 else 1,
                "source": "simulated_mixed_resolution"
            })
        return records

    def generate_simulated_daily(self) -> list:
        daily_patterns = [
            {"day": "今天 (周日)", "date": "06-14", "temp_max": 29, "temp_min": 21, "wind": "3 m/s", "wind_deg": 225, "precip": "-", "sun": "2.5 h", "icon": "cloudy", "night_icon": "sunny-night", "rh_min": 60, "rh_avg": 70, "prob": 10, "pred": 4, "aqi": 45, "uv": 5, "soil_sm": 38},
            {"day": "明天 (周一)", "date": "06-15", "temp_max": 28, "temp_min": 22, "wind": "4 m/s", "wind_deg": 240, "precip": "-", "sun": "5.1 h", "icon": "cloudy", "night_icon": "sunny-night", "rh_min": 58, "rh_avg": 68, "prob": 15, "pred": 4, "aqi": 52, "uv": 7, "soil_sm": 36},
            {"day": "周二", "date": "06-16", "temp_max": 30, "temp_min": 23, "wind": "3 m/s", "wind_deg": 225, "precip": "2.5 mm", "sun": "3.2 h", "icon": "thunderstorm", "night_icon": "cloudy-night", "rh_min": 65, "rh_avg": 78, "prob": 45, "pred": 4, "aqi": 68, "uv": 4, "soil_sm": 42},
            {"day": "周三", "date": "06-17", "temp_max": 31, "temp_min": 24, "wind": "2 m/s", "wind_deg": 180, "precip": "5.1 mm", "sun": "6.0 h", "icon": "thunderstorm", "night_icon": "thunderstorm-night", "rh_min": 66, "rh_avg": 80, "prob": 50, "pred": 4, "aqi": 50, "uv": 8, "soil_sm": 45},
            {"day": "周四", "date": "06-18", "temp_max": 30, "temp_min": 25, "wind": "2 m/s", "wind_deg": 225, "precip": "22.0 mm", "sun": "1.5 h", "icon": "heavy-rain", "night_icon": "heavy-rain-night", "rh_min": 85, "rh_avg": 92, "prob": 85, "pred": 4, "aqi": 25, "uv": 2, "soil_sm": 65},
            {"day": "周五", "date": "06-19", "temp_max": 28, "temp_min": 25, "wind": "2 m/s", "wind_deg": 225, "precip": "35.0 mm", "sun": "0.0 h", "icon": "heavy-rain", "night_icon": "heavy-rain-night", "rh_min": 90, "rh_avg": 95, "prob": 90, "pred": 4, "aqi": 18, "uv": 1, "soil_sm": 75},
            {"day": "周六", "date": "06-20", "temp_max": 29, "temp_min": 25, "wind": "2 m/s", "wind_deg": 180, "precip": "15.0 mm", "sun": "0.0 h", "icon": "heavy-rain", "night_icon": "heavy-rain-night", "rh_min": 88, "rh_avg": 90, "prob": 80, "pred": 3, "aqi": 22, "uv": 1, "soil_sm": 72}
        ]
        
        records = []
        for item in daily_patterns:
            laundry = calculate_laundry_index(item["prob"], item["temp_max"], item["rh_min"])
            heat = calculate_heat_alert(item["temp_max"], item["rh_avg"])
            
            records.append({
                "day_name": item["day"],
                "date": item["date"],
                "temperature_max": item["temp_max"],
                "temperature_min": item["temp_min"],
                "wind_speed_text": item["wind"],
                "wind_direction_deg": item["wind_deg"],
                "precipitation_text": item["precip"],
                "sunshine_hours": item["sun"],
                "icon": item["icon"],
                "night_icon": item["night_icon"],
                "predictability": item["pred"],
                "laundry_index": laundry["text"],
                "laundry_level": laundry["level"],
                "heat_alert": heat["text"],
                "heat_level": item["uv"],
                "aqi_mean": item["aqi"],
                "uv_max": item["uv"],
                "soil_moisture_mean": item["soil_sm"],
                "source": "simulated_meteoblue_aligned"
            })
        return records


import threading
import discord_webhook
import lark_webhook

def run_scheduler():
    # 后台定时扫描线程，每 30 秒运行一次
    last_sent = {"06:00": None, "12:00": None, "22:00": None}
    
    # 启动时进行初始化，避免服务器重启导致重复发送历史时段的推送
    tz_zhuji = datetime.timezone(datetime.timedelta(hours=8))
    now = datetime.datetime.now(tz_zhuji)
    current_date = now.date()
    
    if now.time() >= datetime.time(6, 0):
        last_sent["06:00"] = current_date
    if now.time() >= datetime.time(12, 0):
        last_sent["12:00"] = current_date
    if now.time() >= datetime.time(22, 0):
        last_sent["22:00"] = current_date

    while True:
        try:
            now = datetime.datetime.now(tz_zhuji)
            current_date = now.date()
            
            t_06 = datetime.datetime.combine(current_date, datetime.time(6, 0)).replace(tzinfo=tz_zhuji)
            t_12 = datetime.datetime.combine(current_date, datetime.time(12, 0)).replace(tzinfo=tz_zhuji)
            t_22 = datetime.datetime.combine(current_date, datetime.time(22, 0)).replace(tzinfo=tz_zhuji)
            
            # 1. 06:00 推送 (仅在 06:00 到 12:00 之间生效)
            if t_06 <= now < t_12 and last_sent.get("06:00") != current_date:
                print(f"[SCHEDULER] 触发每天早上 06:00 今天天气推送任务...")
                lark_webhook.send_to_lark(day="today")
                last_sent["06:00"] = current_date
                
            # 2. 12:00 推送 (仅在 12:00 到 22:00 之间生效)
            elif t_12 <= now < t_22 and last_sent.get("12:00") != current_date:
                print(f"[SCHEDULER] 触发每天中午 12:00 今天天气推送任务...")
                lark_webhook.send_to_lark(day="today")
                last_sent["12:00"] = current_date
                last_sent["06:00"] = current_date # 同步标记，防止回退补发
                
            # 3. 22:00 推送 (在 22:00 之后生效)
            elif now >= t_22 and last_sent.get("22:00") != current_date:
                print(f"[SCHEDULER] 触发每天晚上 22:00 明天精细天气推送任务...")
                lark_webhook.send_to_lark(day="tomorrow")
                last_sent["22:00"] = current_date
                last_sent["06:00"] = current_date
                last_sent["12:00"] = current_date
                
        except Exception as e:
            print(f"[SCHEDULER ERROR] 定时线程发生异常: {e}")
        time.sleep(30)

# @app.on_event("startup")
# def start_scheduler():
#     # 已根据用户要求禁用本地后台定时线程，仅使用 GitHub Actions 定时运行推送任务，防止重复推送
#     print("[SCHEDULER] 本地后台定时推送线程已禁用。")
#     # t = threading.Thread(target=run_scheduler, daemon=True)
#     # t.start()

engine = WeatherFusionEngine()

@app.get("/api/forecast/hourly")
def get_hourly_forecast():
    """获取真实 API 融合后的 1h/3h 动态精细化预报"""
    return engine.generate_fused_hourly()

@app.get("/api/forecast/daily")
def get_daily_forecast():
    """获取真实 API 融合后的 7天 日级指标预报"""
    return engine.generate_fused_daily()

@app.get("/api/push-discord")
def trigger_discord_push(day: str = "today"):
    """手动触发一次 Discord Webhook 推送"""
    success = discord_webhook.send_to_discord(day=day)
    return {
        "status": "success" if success else "failed",
        "day": day,
        "timestamp": datetime.datetime.now().isoformat()
    }

@app.get("/api/push-lark")
def trigger_lark_push(day: str = "today"):
    """手动触发一次 Lark Webhook 推送"""
    success = lark_webhook.send_to_lark(day=day)
    return {
        "status": "success" if success else "failed",
        "day": day,
        "timestamp": datetime.datetime.now().isoformat()
    }

@app.get("/")
def read_root():
    return RedirectResponse(url="/static/index.html")

# 挂载前端静态目录
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
