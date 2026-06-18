/**
 * Zhuji Weather Fusion Dashboard (Meteoblue Layout)
 * Front-end rendering engine - Lifestyle indices & SVG Curve Wave
 */

const ICON_MAP = {
    "sunny": "clear-day.svg",
    "sunny-night": "clear-night.svg",
    "cloudy": "partly-cloudy-day.svg",
    "cloudy-night": "partly-cloudy-night.svg",
    "overcast": "overcast.svg",
    "light-rain": "rain.svg",
    "heavy-rain": "extreme-day-rain.svg",
    "heavy-rain-night": "extreme-night-rain.svg",
    "thunderstorm": "thunderstorms-day-rain.svg",
    "thunderstorm-night": "thunderstorms-night-rain.svg"
};

// 动态计算气温热力插值
function getTempColor(temp) {
    const minTemp = 15;
    const maxTemp = 38;
    const percent = Math.max(0, Math.min(1, (temp - minTemp) / (maxTemp - minTemp)));
    const hue = 210 - percent * 198;
    return `hsla(${hue}, 82%, 36%, 0.8)`;
}

// 渲染可信度点
function renderPredictabilityDots(level) {
    let html = '<div class="col-predictability">';
    for (let i = 1; i <= 5; i++) {
        const filledClass = i <= level ? 'filled' : '';
        html += `<span class="target-dot ${filledClass}"></span>`;
    }
    html += '</div>';
    return html;
}

class WeatherDashboard {
    constructor() {
        this.initClock();
        this.loadDashboardData();
    }

    initClock() {
        const timeBadge = document.getElementById("current-time-badge");
        const updateClock = () => {
            const now = new Date();
            timeBadge.innerHTML = `<i data-lucide="clock"></i> ${now.toLocaleTimeString("zh-CN", { hour12: false })}`;
            if (window.lucide) {
                window.lucide.createIcons();
            }
        };
        updateClock();
        setInterval(updateClock, 1000);
    }

    async loadDashboardData() {
        try {
            const [hourlyRes, dailyRes] = await Promise.all([
                fetch("/api/forecast/hourly").then(r => r.json()),
                fetch("/api/forecast/daily").then(r => r.json())
            ]);

            this.renderDailyColumns(dailyRes);
            this.renderHourlyTable(hourlyRes);
            
            const sourceText = document.getElementById("data-source-text");
            if (hourlyRes[0] && hourlyRes[0].source === "api_fused_ecmwf_meteoblue") {
                sourceText.innerText = "Meteoblue + ECMWF 物理融合";
            } else {
                sourceText.innerText = "Meteoblue 融合引擎 (Demo)";
            }

        } catch (error) {
            console.warn("未能连接至后端 API，启动本地 Meteoblue 仿真数据...", error);
            this.loadFallbackData();
        }
    }

    loadFallbackData() {
        const hourlyMock = this.getMockHourlyData();
        const dailyMock = this.getMockDailyData();

        this.renderDailyColumns(dailyMock);
        this.renderHourlyTable(hourlyMock);

        document.getElementById("data-source-text").innerText = "Meteoblue 本地离线引擎";
    }

    // 1. 渲染 7日 天气纵向列 (含生活指数：防霉/晒衣，闷热预警)
    renderDailyColumns(dailyData) {
        const container = document.getElementById("daily-columns-wrapper");
        container.innerHTML = "";

        dailyData.forEach((day, index) => {
            const column = document.createElement("div");
            column.className = `daily-column ${index === 0 ? 'active-day' : ''}`;
            
            const dayIconFile = ICON_MAP[day.icon] || "cloudy.svg";
            
            // 构建列内容，拼装晒衣与体感预警指标
            column.innerHTML = `
                <span class="col-day-name">${day.day_name}</span>
                <span class="col-day-date">${day.date}</span>
                
                <div class="col-weather-box">
                    <img src="https://cdn.jsdelivr.net/npm/@meteocons/svg@latest/fill/${dayIconFile}" class="weather-icon-img" alt="${day.condition}" />
                </div>
                
                <div class="col-temp-group">
                    <span class="temp-pill-max">${day.temperature_max}°C</span>
                    <span class="temp-pill-min">${day.temperature_min}°C</span>
                </div>
                
                <!-- 晒衣防霉指数 -->
                <span class="col-lifestyle-badge laundry-lvl-${day.laundry_level}" title="${day.laundry_index}">
                    <i data-lucide="shirt" style="width:12px;height:12px;"></i>
                    ${day.laundry_index.split(' ')[0]}
                </span>
                
                <!-- 体感闷热警报 -->
                <span class="col-lifestyle-badge heat-lvl-${day.heat_level}" title="${day.heat_alert}">
                    <i data-lucide="thermometer-sun" style="width:12px;height:12px;"></i>
                    ${day.heat_alert.split(' ')[0]}
                </span>
                
                <span class="col-param wind" style="margin-top: 12px;">
                    <i data-lucide="navigation" style="transform: rotate(${day.wind_direction_deg}deg); display: inline-block;"></i>
                    ${day.wind_speed_text}
                </span>
                
                <span class="col-param precip">
                    <i data-lucide="droplet"></i>
                    ${day.precipitation_text}
                </span>
                
                <span class="col-param sun">
                    <i data-lucide="sun"></i>
                    ${day.sunshine_hours}
                </span>

                <!-- 扩展生活/健康小字栏 -->
                <span class="col-sub-param aqi" title="全天日均空气质量">
                    <i data-lucide="wind"></i>
                    AQI ${day.aqi_mean || 50}
                </span>
                
                <span class="col-sub-param soil" title="土壤含水率 (平均)">
                    <i data-lucide="sprout"></i>
                    土壤 ${day.soil_moisture_mean || 30}%
                </span>
                
                ${renderPredictabilityDots(day.predictability)}
            `;

            // 悬浮夜间天气小图标
            if (index < dailyData.length - 1) {
                const nightBadge = document.createElement("div");
                nightBadge.className = "night-badge-container";
                
                const nightIconFile = ICON_MAP[day.night_icon] || "clear-night.svg";
                nightBadge.innerHTML = `<img src="https://cdn.jsdelivr.net/npm/@meteocons/svg@latest/fill/${nightIconFile}" class="weather-icon-img-night" alt="night weather" />`;
                
                nightBadge.title = `${day.day_name} 夜间：${day.night_icon.includes('thunderstorm') ? '雷阵雨' : '晴朗'}`;
                
                column.appendChild(nightBadge);
            }

            container.appendChild(column);
        });

        if (window.lucide) {
            window.lucide.createIcons();
        }
    }

    // 2. 渲染参数矩阵 (逐点动态 SVG 曲线)
    renderHourlyTable(hourlyData) {
        this.clearTableRows();

        const rowHours = document.getElementById("row-hours");
        const rowIcons = document.getElementById("row-weather-icons");
        const rowAqi = document.getElementById("row-aqi");
        const rowUv = document.getElementById("row-uv");
        const rowWindDir = document.getElementById("row-wind-direction");
        const rowWindSpeed = document.getElementById("row-wind-speed");
        const rowConvective = document.getElementById("row-convective");
        const rowPrecip = document.getElementById("row-precipitation");
        const rowPrecipProb = document.getElementById("row-precipitation-probability");
        const rowPrecipBars = document.getElementById("row-precipitation-bars");
        const rowSoil = document.getElementById("row-soil");
        const rowVisibility = document.getElementById("row-visibility");
        const rowPredict = document.getElementById("row-predictability");

        // 动态设置温度曲线行 colspan
        document.getElementById("temp-curve-td").setAttribute("colspan", hourlyData.length);

        // 渲染基础行列
        hourlyData.forEach(hour => {
            // 时间轴
            const thHour = document.createElement("th");
            thHour.innerText = hour.time_local;
            rowHours.appendChild(thHour);

            // 天气图表
            const tdIcon = document.createElement("td");
            const hourIconFile = ICON_MAP[hour.icon] || "cloudy.svg";
            tdIcon.innerHTML = `
                <div class="hourly-sky-cell">
                    <img src="https://cdn.jsdelivr.net/npm/@meteocons/svg@latest/fill/${hourIconFile}" class="weather-icon-img-hourly" alt="${hour.condition}" />
                </div>
            `;
            rowIcons.appendChild(tdIcon);

            // AQI
            const tdAqi = document.createElement("td");
            let aqiLevelClass = 1;
            if (hour.aqi > 150) aqiLevelClass = 4;
            else if (hour.aqi > 100) aqiLevelClass = 3;
            else if (hour.aqi > 50) aqiLevelClass = 2;
            tdAqi.innerHTML = `
                <span class="aqi-badge aqi-val-${aqiLevelClass}" title="PM2.5: ${hour.pm25} | PM10: ${hour.pm10}">
                    ${hour.aqi}
                </span>
            `;
            rowAqi.appendChild(tdAqi);

            // UV Index
            const tdUv = document.createElement("td");
            tdUv.innerHTML = `
                <span class="uv-badge" title="紫外线指数">
                    <i data-lucide="sun-dim" style="width:11px;height:11px;"></i>
                    ${hour.uvindex}
                </span>
            `;
            rowUv.appendChild(tdUv);

            // 风向标 (箭头旋转)
            const tdWindDir = document.createElement("td");
            tdWindDir.innerHTML = `
                <div class="wind-dir-cell">
                    <i data-lucide="navigation" class="wind-vane-arrow" style="transform: rotate(${hour.wind_direction}deg);"></i>
                    <span class="wind-dir-text">${hour.wind_direction_text}</span>
                </div>
            `;
            rowWindDir.appendChild(tdWindDir);

            // 风速范围
            const tdWindSpeed = document.createElement("td");
            tdWindSpeed.innerText = hour.wind_speed;
            rowWindSpeed.appendChild(tdWindSpeed);

            // 对流天气风险
            const tdConvective = document.createElement("td");
            tdConvective.innerHTML = `
                <span class="convective-shield convective-lvl-${hour.cape_level}" title="CAPE: ${hour.cape} J/kg">
                    ${hour.cape_risk}
                </span>
            `;
            rowConvective.appendChild(tdConvective);

            // 降雨量 (mm 或 in)
            const tdPrecip = document.createElement("td");
            tdPrecip.innerText = hour.precipitation;
            if (hour.precipitation !== "-") {
                tdPrecip.className = "prob-cell";
            }
            rowPrecip.appendChild(tdPrecip);

            // 降雨概率
            const tdPrecipProb = document.createElement("td");
            tdPrecipProb.className = "prob-cell";
            tdPrecipProb.innerText = `${hour.precipitation_probability}%`;
            rowPrecipProb.appendChild(tdPrecipProb);

            // 降水柱高度显示
            const tdPrecipBar = document.createElement("td");
            if (hour.precipitation_probability > 0) {
                const barHeight = Math.max(3, Math.round(hour.precipitation_probability * 0.28));
                tdPrecipBar.innerHTML = `
                    <div class="rain-bar-container">
                        <div class="rain-bar" style="height: ${barHeight}px;"></div>
                    </div>
                `;
            } else {
                tdPrecipBar.innerHTML = `
                    <div class="rain-bar-container">
                        <span class="rain-bar-none"></span>
                    </div>
                `;
            }
            rowPrecipBars.appendChild(tdPrecipBar);

            // 土壤温湿度
            const tdSoil = document.createElement("td");
            tdSoil.innerHTML = `
                <span class="soil-details" title="土壤温度 / 土壤湿度 (0-10cm)">
                    ${hour.soil_temp}° / ${hour.soil_moisture}%
                </span>
            `;
            rowSoil.appendChild(tdSoil);

            // 能见度
            const tdVisibility = document.createElement("td");
            tdVisibility.innerText = hour.visibility;
            rowVisibility.appendChild(tdVisibility);

            // 置信度
            const tdPredict = document.createElement("td");
            tdPredict.innerHTML = `<div class="predict-row-cell">${renderPredictabilityDots(hour.predictability)}</div>`;
            rowPredict.appendChild(tdPredict);
        });

        // 3. 绘制平滑温度波浪折线图 (SVG 形式)
        this.drawTemperatureCurve(hourlyData);

        if (window.lucide) {
            window.lucide.createIcons();
        }
    }

    // 绘制 SVG 波浪折线
    drawTemperatureCurve(hourlyData) {
        const svg = document.getElementById("temp-curve-svg");
        svg.innerHTML = ""; // 清理画布

        const colWidth = 80; // 与 CSS 列宽完全一致
        const count = hourlyData.length;
        const width = colWidth * count;
        const height = 110;
        
        svg.setAttribute("width", width);
        svg.setAttribute("height", height);
        svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

        const temps = hourlyData.map(h => h.temperature);
        const apparents = hourlyData.map(h => h.apparent_temperature);
        const allVal = [...temps, ...apparents];
        
        const maxVal = Math.max(...allVal);
        const minVal = Math.min(...allVal);
        const range = maxVal - minVal || 1;

        const pointsActual = [];
        const pointsApparent = [];

        // 映射物理点坐标
        for (let i = 0; i < count; i++) {
            const x = colWidth * i + colWidth / 2;
            
            // 线性映射至 Y [24px, 86px] 空间
            const yActual = 86 - ((hourlyData[i].temperature - minVal) / range) * 62;
            pointsActual.push({ x, y: yActual, val: hourlyData[i].temperature });

            const yApparent = 86 - ((hourlyData[i].apparent_temperature - minVal) / range) * 62;
            pointsApparent.push({ x, y: yApparent, val: hourlyData[i].apparent_temperature });
        }

        // 计算三次贝塞尔曲线控制路径 (Bezier Curve Spline)
        const getBezierPath = (pts) => {
            if (pts.length === 0) return "";
            let d = `M ${pts[0].x} ${pts[0].y}`;
            for (let i = 0; i < pts.length - 1; i++) {
                const p0 = pts[i];
                const p1 = pts[i + 1];
                const cpX1 = p0.x + 28;
                const cpY1 = p0.y;
                const cpX2 = p1.x - 28;
                const cpY2 = p1.y;
                d += ` C ${cpX1} ${cpY1}, ${cpX2} ${cpY2}, ${p1.x} ${p1.y}`;
            }
            return d;
        };

        // 1. 实际温度：渐变阴影填充 (Area Chart)
        if (pointsActual.length > 0) {
            const pathD = getBezierPath(pointsActual);
            const fillD = `${pathD} L ${pointsActual[pointsActual.length - 1].x} ${height} L ${pointsActual[0].x} ${height} Z`;
            
            // 构建 SVG defs 渐变
            let defs = svg.querySelector("defs");
            if (!defs) {
                defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
                defs.innerHTML = `
                    <linearGradient id="temp-curve-grad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="var(--mb-light-blue)" stop-opacity="0.3"/>
                        <stop offset="100%" stop-color="var(--mb-light-blue)" stop-opacity="0.0"/>
                    </linearGradient>
                `;
                svg.appendChild(defs);
            }

            const fillPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
            fillPath.setAttribute("d", fillD);
            fillPath.setAttribute("fill", "url(#temp-curve-grad)");
            svg.appendChild(fillPath);

            // 实际温度线 (实线)
            const linePath = document.createElementNS("http://www.w3.org/2000/svg", "path");
            linePath.setAttribute("d", pathD);
            linePath.setAttribute("fill", "none");
            linePath.setAttribute("stroke", "var(--mb-light-blue)");
            linePath.setAttribute("stroke-width", "3");
            svg.appendChild(linePath);
        }

        // 2. 体感温度线 (绿色虚线)
        if (pointsApparent.length > 0) {
            const pathD = getBezierPath(pointsApparent);
            const linePath = document.createElementNS("http://www.w3.org/2000/svg", "path");
            linePath.setAttribute("d", pathD);
            linePath.setAttribute("fill", "none");
            linePath.setAttribute("stroke", "var(--accent-green)");
            linePath.setAttribute("stroke-width", "2");
            linePath.setAttribute("stroke-dasharray", "4,4");
            svg.appendChild(linePath);
        }

        // 3. 实际温度：绘制顶点底衬
        pointsActual.forEach(p => {
            const outerCircle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
            outerCircle.setAttribute("cx", p.x);
            outerCircle.setAttribute("cy", p.y);
            outerCircle.setAttribute("r", "5");
            outerCircle.setAttribute("fill", "#0c0f1c");
            outerCircle.setAttribute("stroke", "var(--mb-light-blue)");
            outerCircle.setAttribute("stroke-width", "2.5");
            svg.appendChild(outerCircle);
        });

        // 4. 体感温度：绘制小顶点
        pointsApparent.forEach(p => {
            const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
            circle.setAttribute("cx", p.x);
            circle.setAttribute("cy", p.y);
            circle.setAttribute("r", "3");
            circle.setAttribute("fill", "var(--accent-green)");
            svg.appendChild(circle);
        });

        // 5. 动态计算文字位置，防重叠渲染
        for (let i = 0; i < count; i++) {
            const pActual = pointsActual[i];
            const pApparent = pointsApparent[i];

            let yActualLabel, yApparentLabel;

            if (pActual.val > pApparent.val) {
                // 实际气温高：实际气温置于线上方，体感温度置于线下方
                yActualLabel = pActual.y - 10;
                yApparentLabel = pApparent.y + 14;
            } else if (pApparent.val > pActual.val) {
                // 体感温度高：体感温度置于线上方，实际温度置于线下方
                yActualLabel = pActual.y + 14;
                yApparentLabel = pApparent.y - 10;
            } else {
                // 相等：默认实际气温在上，体感在下 (24px 间距，不重合)
                yActualLabel = pActual.y - 10;
                yApparentLabel = pApparent.y + 14;
            }

            // 绘制实际温度文字
            const tActual = document.createElementNS("http://www.w3.org/2000/svg", "text");
            tActual.setAttribute("x", pActual.x);
            tActual.setAttribute("y", yActualLabel);
            tActual.setAttribute("text-anchor", "middle");
            tActual.setAttribute("fill", "var(--text-primary)");
            tActual.setAttribute("style", "font-family: var(--font-number); font-weight: 700; font-size: 0.82rem; text-shadow: 0 1px 3px rgba(0,0,0,0.85);");
            tActual.textContent = `${pActual.val}°`;
            svg.appendChild(tActual);

            // 绘制体感温度文字
            const tApparent = document.createElementNS("http://www.w3.org/2000/svg", "text");
            tApparent.setAttribute("x", pApparent.x);
            tApparent.setAttribute("y", yApparentLabel);
            tApparent.setAttribute("text-anchor", "middle");
            tApparent.setAttribute("fill", "var(--text-secondary)");
            tApparent.setAttribute("style", "font-family: var(--font-number); font-weight: 500; font-size: 0.72rem; text-shadow: 0 1px 2px rgba(0,0,0,0.85);");
            tApparent.textContent = `${pApparent.val}°`;
            svg.appendChild(tApparent);
        }
    }

    clearTableRows() {
        const rowIds = [
            "row-hours", "row-weather-icons", "row-aqi", "row-uv", 
            "row-wind-direction", "row-wind-speed", "row-convective",
            "row-precipitation", "row-precipitation-probability", "row-precipitation-bars", 
            "row-soil", "row-visibility", "row-predictability"
        ];
        rowIds.forEach(id => {
            const row = document.getElementById(id);
            if (row) {
                while (row.children.length > 1) {
                    row.removeChild(row.lastChild);
                }
            }
        });
    }

    // 备用混合 1h/3h 仿真数据生成
    getMockHourlyData() {
        return [
            // 今天 (1h 步长，从上午 09:00 至 23:00)
            {"time_local": "09:00", "temperature": 24, "apparent_temperature": 27, "wind_direction": 45, "wind_direction_text": "NE", "wind_speed": "2-6", "precipitation": "-", "precipitation_probability": 10, "visibility": "12.4", "icon": "cloudy", "predictability": 4},
            {"time_local": "10:00", "temperature": 25, "apparent_temperature": 28, "wind_direction": 45, "wind_direction_text": "NE", "wind_speed": "3-7", "precipitation": "-", "precipitation_probability": 10, "visibility": "12.4", "icon": "cloudy", "predictability": 4},
            {"time_local": "11:00", "temperature": 26, "apparent_temperature": 29, "wind_direction": 30, "wind_direction_text": "NNE", "wind_speed": "4-8", "precipitation": "-", "precipitation_probability": 15, "visibility": "12.4", "icon": "cloudy", "predictability": 4},
            {"time_local": "12:00", "temperature": 27, "apparent_temperature": 29, "wind_direction": 22.5, "wind_direction_text": "NNE", "wind_speed": "6-10", "precipitation": "-", "precipitation_probability": 20, "visibility": "12.4", "icon": "overcast", "predictability": 4},
            {"time_local": "13:00", "temperature": 28, "apparent_temperature": 30, "wind_direction": 22.5, "wind_direction_text": "NNE", "wind_speed": "6-11", "precipitation": "-", "precipitation_probability": 25, "visibility": "12.4", "icon": "overcast", "predictability": 4},
            {"time_local": "14:00", "temperature": 29, "apparent_temperature": 31, "wind_direction": 45, "wind_direction_text": "NE", "wind_speed": "6-11", "precipitation": "-", "precipitation_probability": 30, "visibility": "12.4", "icon": "cloudy", "predictability": 4},
            {"time_local": "15:00", "temperature": 26, "apparent_temperature": 26, "wind_direction": 135, "wind_direction_text": "SE", "wind_speed": "12-18", "precipitation": "12.5", "precipitation_probability": 95, "visibility": "6.2", "icon": "heavy-rain", "predictability": 4},
            {"time_local": "16:00", "temperature": 25, "apparent_temperature": 25, "wind_direction": 135, "wind_direction_text": "SE", "wind_speed": "10-15", "precipitation": "6.2", "precipitation_probability": 90, "visibility": "8.1", "icon": "heavy-rain", "predictability": 4},
            {"time_local": "17:00", "temperature": 25, "apparent_temperature": 26, "wind_direction": 135, "wind_direction_text": "SE", "wind_speed": "8-12", "precipitation": "2.1", "precipitation_probability": 80, "visibility": "10.0", "icon": "light-rain", "predictability": 4},
            {"time_local": "18:00", "temperature": 25, "apparent_temperature": 27, "wind_direction": 90, "wind_direction_text": "E", "wind_speed": "6-10", "precipitation": "-", "precipitation_probability": 40, "visibility": "12.4", "icon": "overcast", "predictability": 4},
            {"time_local": "19:00", "temperature": 24, "apparent_temperature": 27, "wind_direction": 45, "wind_direction_text": "NE", "wind_speed": "4-8", "precipitation": "-", "precipitation_probability": 20, "visibility": "12.4", "icon": "overcast", "predictability": 4},
            {"time_local": "20:00", "temperature": 24, "apparent_temperature": 28, "wind_direction": 22.5, "wind_direction_text": "NNE", "wind_speed": "3-8", "precipitation": "-", "precipitation_probability": 10, "visibility": "12.4", "icon": "sunny-night", "predictability": 4},
            {"time_local": "21:00", "temperature": 24, "apparent_temperature": 28, "wind_direction": 22.5, "wind_direction_text": "NNE", "wind_speed": "3-8", "precipitation": "-", "precipitation_probability": 10, "visibility": "12.4", "icon": "sunny-night", "predictability": 4},
            {"time_local": "22:00", "temperature": 23, "apparent_temperature": 27, "wind_direction": 337.5, "wind_direction_text": "NNW", "wind_speed": "3-5", "precipitation": "-", "precipitation_probability": 0, "visibility": "12.4", "icon": "sunny-night", "predictability": 4},
            {"time_local": "23:00", "temperature": 23, "apparent_temperature": 26, "wind_direction": 337.5, "wind_direction_text": "NNW", "wind_speed": "3-5", "precipitation": "-", "precipitation_probability": 0, "visibility": "12.4", "icon": "sunny-night", "predictability": 4},
            
            // 明天 (3h 步长，从 00:00 至 21:00)
            {"time_local": "明日 00:00", "temperature": 23, "apparent_temperature": 26, "wind_direction": 337.5, "wind_direction_text": "NNW", "wind_speed": "3-5", "precipitation": "-", "precipitation_probability": 0, "visibility": "12.4", "icon": "sunny-night", "predictability": 4},
            {"time_local": "明日 03:00", "temperature": 22, "apparent_temperature": 25, "wind_direction": 337.5, "wind_direction_text": "NNW", "wind_speed": "2-4", "precipitation": "-", "precipitation_probability": 0, "visibility": "12.4", "icon": "sunny-night", "predictability": 4},
            {"time_local": "明日 06:00", "temperature": 22, "apparent_temperature": 25, "wind_direction": 315, "wind_direction_text": "NW", "wind_speed": "2-4", "precipitation": "-", "precipitation_probability": 0, "visibility": "12.4", "icon": "cloudy", "predictability": 4},
            {"time_local": "明日 09:00", "temperature": 25, "apparent_temperature": 28, "wind_direction": 225, "wind_direction_text": "SW", "wind_speed": "3-6", "precipitation": "-", "precipitation_probability": 10, "visibility": "12.4", "icon": "cloudy", "predictability": 4},
            {"time_local": "明日 12:00", "temperature": 28, "apparent_temperature": 32, "wind_direction": 225, "wind_direction_text": "SW", "wind_speed": "4-8", "precipitation": "-", "precipitation_probability": 10, "visibility": "12.4", "icon": "sunny", "predictability": 4},
            {"time_local": "明日 15:00", "temperature": 30, "apparent_temperature": 35, "wind_direction": 225, "wind_direction_text": "SW", "wind_speed": "5-9", "precipitation": "-", "precipitation_probability": 20, "visibility": "12.4", "icon": "cloudy", "predictability": 4},
            {"time_local": "明日 18:00", "temperature": 28, "apparent_temperature": 33, "wind_direction": 180, "wind_direction_text": "S", "wind_speed": "4-8", "precipitation": "-", "precipitation_probability": 10, "visibility": "12.4", "icon": "cloudy", "predictability": 4},
            {"time_local": "明日 21:00", "temperature": 25, "apparent_temperature": 29, "wind_direction": 180, "wind_direction_text": "S", "wind_speed": "3-6", "precipitation": "-", "precipitation_probability": 0, "visibility": "12.4", "icon": "sunny-night", "predictability": 4}
        ];
    }

    getMockDailyData() {
        return [
            {"day_name": "SUN Today", "date": "6-14", "temperature_max": 29, "temperature_min": 21, "wind_speed_text": "7 mph", "wind_direction_deg": 225, "precipitation_text": "-", "sunshine_hours": "2 h", "icon": "cloudy", "night_icon": "sunny-night", "predictability": 4, "laundry_index": "极速晾晒 (干燥防霉)", "laundry_level": 1, "heat_alert": "温和舒适", "heat_level": 2},
            {"day_name": "MON Tomorrow", "date": "6-15", "temperature_max": 28, "temperature_min": 22, "wind_speed_text": "10 mph", "wind_direction_deg": 240, "precipitation_text": "-", "sunshine_hours": "5 h", "icon": "cloudy", "night_icon": "sunny-night", "predictability": 4, "laundry_index": "极速晾晒 (干燥防霉)", "laundry_level": 1, "heat_alert": "温和舒适", "heat_level": 2},
            {"day_name": "TUE", "date": "6-16", "temperature_max": 30, "temperature_min": 23, "wind_speed_text": "7 mph", "wind_direction_deg": 225, "precipitation_text": "0-0.1\"", "sunshine_hours": "3 h", "icon": "thunderstorm", "night_icon": "cloudy-night", "predictability": 4, "laundry_index": "不宜晾晒 (潮湿易霉)", "laundry_level": 3, "heat_alert": "闷热警告", "heat_level": 3},
            {"day_name": "WED", "date": "6-17", "temperature_max": 31, "temperature_min": 24, "wind_speed_text": "3 mph", "wind_direction_deg": 180, "precipitation_text": "0-0.2\"", "sunshine_hours": "6 h", "icon": "thunderstorm", "night_icon": "thunderstorm-night", "predictability": 4, "laundry_index": "不宜晾晒 (潮湿易霉)", "laundry_level": 3, "heat_alert": "闷热警告", "heat_level": 3},
            {"day_name": "THU", "date": "6-18", "temperature_max": 30, "temperature_min": 25, "wind_speed_text": "4 mph", "wind_direction_deg": 225, "precipitation_text": ">0.8\"", "sunshine_hours": "2 h", "icon": "heavy-rain", "night_icon": "heavy-rain-night", "predictability": 4, "laundry_index": "禁止晾晒 (阴雨大霉)", "laundry_level": 4, "heat_alert": "闷热警告", "heat_level": 3},
            {"day_name": "FRI", "date": "6-19", "temperature_max": 28, "temperature_min": 25, "wind_speed_text": "4 mph", "wind_direction_deg": 225, "precipitation_text": ">0.8\"", "sunshine_hours": "0 h", "icon": "heavy-rain", "night_icon": "heavy-rain-night", "predictability": 4, "laundry_index": "禁止晾晒 (阴雨大霉)", "laundry_level": 4, "heat_alert": "清凉舒适", "heat_level": 1},
            {"day_name": "SAT", "date": "6-20", "temperature_max": 29, "temperature_min": 25, "wind_speed_text": "4 mph", "wind_direction_deg": 180, "precipitation_text": ">0.8\"", "sunshine_hours": "0 h", "icon": "heavy-rain", "night_icon": "heavy-rain-night", "predictability": 3, "laundry_index": "禁止晾晒 (阴雨大霉)", "laundry_level": 4, "heat_alert": "温和舒适", "heat_level": 2}
        ];
    }
}

document.addEventListener("DOMContentLoaded", () => {
    window.app = new WeatherDashboard();
});
