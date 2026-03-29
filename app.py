import math
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
import requests
import os
import datetime

# ==========================================
# MODULE 1: WEATHER API INTEGRATION
# ==========================================
def get_weather(api_key, lat, lon, target_timestamp=None):
    fallback = {"wind_speed": 5.0, "wind_deg": 90, "temp": 15.0, "pressure": 1013.25, "error": None}
    if not api_key:
        fallback["error"] = "API_KEY girilmedi. Varsayılan hava durumu kullanılıyor."
        return fallback
        
    try:
        now = datetime.datetime.now().timestamp()
        
        if target_timestamp is None or abs(target_timestamp - now) < 3600:
            url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric"
            res = requests.get(url, timeout=5).json()
            if res.get("cod") != 200:
                fallback["error"] = f"API Hatası: {res.get('message')}"
                return fallback
            
            return {
                "wind_speed": res["wind"].get("speed", 5.0),
                "wind_deg": res["wind"].get("deg", 90),
                "temp": res["main"]["temp"],
                "pressure": res["main"]["pressure"],
                "error": None
            }
        else:
            url = f"http://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={api_key}&units=metric"
            res = requests.get(url, timeout=5).json()
            if str(res.get("cod")) != "200":
                fallback["error"] = f"API Hatası (Forecast): {res.get('message')}"
                return fallback
                
            forecast_list = res.get("list", [])
            if not forecast_list: return fallback
                
            closest_forecast = min(forecast_list, key=lambda x: abs(x["dt"] - target_timestamp))
            error_msg = None
            if abs(closest_forecast["dt"] - target_timestamp) > (5 * 86400):
                error_msg = "Sadece maks 5 günlük tahmin desteklenir."
                
            return {
                "wind_speed": closest_forecast["wind"].get("speed", 5.0),
                "wind_deg": closest_forecast["wind"].get("deg", 90),
                "temp": closest_forecast["main"]["temp"],
                "pressure": closest_forecast["main"]["pressure"],
                "error": error_msg
            }
    except Exception as e:
        fallback["error"] = "Bağlantı Hatası: Varsayılan hava durumu kullanılıyor (Özel konumlar için oda şartları geçerlidir)."
        return fallback

def get_city_name(api_key, lat, lon):
    if not api_key:
        return "Bilinmiyor (API Key Giriniz)"
    try:
        url = f"http://api.openweathermap.org/geo/1.0/reverse?lat={lat}&lon={lon}&limit=1&appid={api_key}"
        res = requests.get(url, timeout=5).json()
        if isinstance(res, list) and len(res) > 0:
            return res[0].get("name", "Bilinmiyor")
    except Exception as e:
        pass
    return "Bilinmiyor"

# ==========================================
# MODULE 2: GNC & PHYSICS ENGINE (dt=0.05)
# ==========================================
class PhysicsEngine:
    def __init__(self, stages, area, payload, weather_data, t_apogee, t_perigee, launch_lat):
        self.time = 0.0
        self.x = 0.0
        self.y = 0.0
        
        self.R_EARTH = 6371000.0
        self.G_CONSTANT = 6.67430e-11
        self.M_EARTH = 5.972e24
        self.G0 = 9.80665
        self.R_SPECIFIC = 287.05 
        self.MOLAR_MASS = 0.02896 
        self.R_UNIVERSAL = 8.314 

        self.v_rot = 465.1 * math.cos(math.radians(launch_lat))
        self.vx = self.v_rot
        self.vy = 0.0
        
        self.stages = stages
        self.payload = payload
        self.current_stage_idx = 0
        
        self.mass = self.payload
        for s in self.stages:
            self.mass += s['dry_mass'] + s['fuel']
            
        self.initial_mass = self.mass         
        
        self.fuel = self.stages[0]['fuel']
        self.thrust = self.stages[0]['thrust']
        self.isp = self.stages[0]['isp']
        self.v_eq = self.isp * self.G0   
        self.drag_coeff_base = 0.4
        self.area = area
        
        self.weather_data = weather_data
        self.target_apogee = t_apogee
        self.target_perigee = t_perigee
        
        self.pitch = 90.0                
        self.max_q = 0.0
        self.max_q_time = 0.0
        self.max_q_v = 0.0
        self.fuel_empty_alt = None
        self.seco_time = None
        
        self.history = []
        self.seco_achieved = False
        self.orbital_energy = 0.0
        self.eccentricity = 0.0
        self.orbit_type = "Bekliyor"

    def simulate(self, dt=0.05, max_time=6000):
        T_sea = self.weather_data['temp'] + 273.15
        P_sea = self.weather_data['pressure'] * 100.0
        
        wind_rad = math.radians(self.weather_data['wind_deg'])
        wind_vx = -self.weather_data['wind_speed'] * math.sin(wind_rad)

        while True:
            # 1. ISA Atmosfer Yoğunluğu
            if self.y < 11000:
                T_local = T_sea - 0.0065 * self.y
            elif self.y < 20000:
                T_local = T_sea - 71.5
            else:
                T_local = T_sea - 71.5 + 0.001 * (self.y - 20000)
                
            T_local = max(T_local, 200.0)
            
            exponent = - (self.MOLAR_MASS * self.G0 * self.y) / (self.R_UNIVERSAL * T_sea)
            P_local = P_sea * math.exp(exponent)
            
            rho = P_local / (self.R_SPECIFIC * T_local) if self.y < 100000 else 0.0

            vacuum_isp = self.stages[self.current_stage_idx]['isp']
            sea_level_isp = vacuum_isp * 0.85
            current_isp = sea_level_isp + (vacuum_isp - sea_level_isp) * (1.0 - min(1.0, P_local / P_sea))
            self.v_eq = current_isp * self.G0

            # 2. Dinamik Sürüklenme
            v_rel_x = self.vx - self.v_rot
            v_rel_y = self.vy
            v_air = math.sqrt(v_rel_x**2 + v_rel_y**2) 
            a_sound = math.sqrt(1.4 * self.R_SPECIFIC * T_local)
            mach = v_air / a_sound if a_sound > 0 else 0.0
            
            if mach < 0.8:
                current_cd = self.drag_coeff_base
            elif 0.8 <= mach <= 1.2:
                current_cd = self.drag_coeff_base * 2.5
            else:
                current_cd = self.drag_coeff_base * (2.5 - 0.5 * math.log(1.0 + (mach - 1.2)))
                current_cd = max(self.drag_coeff_base * 0.5, current_cd)
            
            # Dinamik Basınç (q)
            q = 0.5 * rho * v_air**2
            if q > self.max_q:
                self.max_q = q
                self.max_q_time = self.time
                self.max_q_v = v_air
                self.max_q_x = self.x
                self.max_q_y = self.y
                
            F_d = q * current_cd * self.area
            
            # Wind drag calculations
            F_wx = 0.5 * rho * (wind_vx**2) * self.area * current_cd * math.copysign(1.0, wind_vx)
            if self.y > 40000: F_wx = 0.0

            if v_air != 0:
                F_dx = F_d * (v_rel_x / v_air)
                F_dy = F_d * (v_rel_y / v_air)
            else:
                F_dx = 0.0; F_dy = 0.0

            # 3. SECO GNC & Gravity
            dm = 0.0
            current_thrust = 0.0
            v_mag = math.sqrt(self.vx**2 + self.vy**2)
            r = self.R_EARTH + self.y
            mu = self.G_CONSTANT * self.M_EARTH
            
            self.orbital_energy = (v_mag**2)/2.0 - mu/r
            
            if self.fuel > 0:
                # SECO Target Calculation (Vis-Viva)
                v_req = math.sqrt(mu / (self.R_EARTH + self.target_perigee))
                # SECO checks
                if v_mag >= v_req and self.y >= self.target_perigee and not self.seco_achieved:
                    current_thrust = 0.0
                    self.seco_achieved = True
                    self.seco_time = self.time
                    self.eccentricity = abs((r * v_mag**2) / mu - 1.0)
                    if self.eccentricity < 0.05:
                        self.orbit_type = "Dairesel (Circular)"
                    elif self.eccentricity < 1.0:
                        self.orbit_type = "Eliptik (Elliptical)"
                    else:
                        self.orbit_type = "Hiperbolik (Escape)"
                
                if not self.seco_achieved:
                    current_thrust = self.thrust
                    m_dot = current_thrust / self.v_eq
                    dm = m_dot * dt
                    self.fuel -= dm
                    self.mass -= dm 
            else:
                # Yakıt bitti
                if getattr(self, 'fuel_empty_alt', None) is None:
                    self.fuel_empty_alt = self.y
                    self.fuel_empty_time = self.time
                    
                if self.current_stage_idx < len(self.stages) - 1:
                    self.mass -= self.stages[self.current_stage_idx]['dry_mass']
                    self.current_stage_idx += 1
                    nxt = self.stages[self.current_stage_idx]
                    self.fuel = nxt['fuel']
                    self.thrust = nxt['thrust']
                    self.isp = nxt['isp']
                    self.v_eq = self.isp * self.G0
                    current_thrust = 0.0
                elif not self.seco_achieved:
                    self.orbit_type = "Suborbital"

            # Pitch and Gravity Turn logic
            self.max_y_so_far = max(self.y, getattr(self, 'max_y_so_far', 0.0))
            if self.max_y_so_far <= 2000:
                self.pitch = 90.0
            elif 2000 < self.max_y_so_far <= 120000:
                h_val = self.max_y_so_far
                self.pitch = 90.0 * (1.0 - math.sqrt((h_val - 2000) / 118000.0))
            else:
                # Calculate necessary pitch to maintain altitude above 120km
                g_local_est = mu / (r**2)
                centrifugal_est = (self.vx**2) / r
                required_ay = max(0.0, g_local_est - centrifugal_est)
                
                if current_thrust > 0 and required_ay > 0:
                    sin_theta = (self.mass * required_ay) / current_thrust
                    sin_theta = min(0.95, max(0.0, sin_theta))
                    self.pitch = math.degrees(math.asin(sin_theta))
                else:
                    self.pitch = 0.0  
                
            pitch_rad = math.radians(self.pitch)
            weight = self.mass * self.G0
            g_force_analytic = (current_thrust - F_d) / weight if weight > 0 else 0.0
            
            # Dinamik g = G * M / r^2
            g_local = mu / (r**2)
            
            ax_thrust = (current_thrust * math.cos(pitch_rad) - F_dx + F_wx) / self.mass
            ay_thrust = (current_thrust * math.sin(pitch_rad) - F_dy) / self.mass
            
            centrifugal_accel = (self.vx**2) / r
            effective_g = max(0.0, g_local - centrifugal_accel)
            
            self.vx += ax_thrust * dt
            self.vy += (ay_thrust - effective_g) * dt  
            
            self.x += self.vx * dt
            self.y += self.vy * dt
            self.time += dt

            # Saniyede tam loglama
            current_dry_mass = self.mass - self.fuel
            delta_v_rem = current_isp * self.G0 * math.log(self.mass / current_dry_mass) if self.fuel > 0 and current_dry_mass > 0 else 0.0
            
            pe = self.mass * self.G0 * self.y * (self.R_EARTH / r)
            ke = 0.5 * self.mass * (v_mag**2)
            
            twr = current_thrust / (self.mass * self.G0) if self.mass > 0 else 0.0
            hull_temp = T_local * (1 + 0.2 * (mach**2))  # Stagnation temperature approximation

            self.history.append({
                "Time": self.time, "X": self.x, "Y": self.y,
                "V_x": self.vx, "V_y": self.vy, 
                "Velocity": v_mag, "Mass": self.mass, 
                "Pitch": self.pitch, "Stage": self.current_stage_idx + 1,
                "Mach": mach, "Drag_Coeff": current_cd, "Orbital_Energy": self.orbital_energy, 
                "G_Force": g_force_analytic, "Dyn_Pressure": q, "Orbit_Type": self.orbit_type,
                "Isp": current_isp, "Delta_V_Rem": delta_v_rem, "Kinetic_Energy": ke, "Potential_Energy": pe,
                "TWR": twr, "Hull_Temp": hull_temp
            })

            # Break conditions
            if self.time > 10.0 and self.y < 0.0: break
            if self.seco_achieved and self.time > getattr(self, 'seco_time', self.time) + 4.0: break
            if self.time > max_time: break
                
        return pd.DataFrame(self.history)

# ==========================================
# MODULE 3: STREAMLIT UI/UX DASHBOARD
# ==========================================
st.set_page_config(page_title="S.P.E.A.R.", layout="wide")

if 'tour_active' not in st.session_state:
    st.session_state.tour_active = True
    st.session_state.run_sim = True

st.markdown("""
<style>
    .stApp { background-color: #0b1120; color: #e6edf3; }
    /* Genel Buton Temeli */
    .stButton>button { width: 100%; height: 60px; font-size: 26px; font-weight: 900; border-radius: 8px; transition: 0.3s; }
    
    /* DEMO Buton Özelleştirmesi (Secondary) */
    button[data-testid="baseButton-secondary"] {
        background-color: #343434 !important;
        color: white !important;
        border: 1px solid #343434 !important;
    }
    button[data-testid="baseButton-secondary"]:hover {
        background-color: #1A1A1A !important;
        border-color: #1A1A1A !important;
        color: white !important;
    }

    /* FIRLATMAYI BAŞLAT Buton Özelleştirmesi (Primary) */
    button[data-testid="baseButton-primary"] {
        background-color: #ff3366 !important;
        color: white !important;
        border: 1px solid #ff3366 !important;
    }
    button[data-testid="baseButton-primary"]:hover {
        background-color: #cc0044 !important;
        border-color: #cc0044 !important;
        color: white !important;
    }
    .metric-value { font-size: 24px; font-weight: bold; color: #00ffcc; }
    .title-banner { font-size: 38px; font-weight: 800; color: #ffffff; text-align: center; margin-bottom: 20px;}
    .weather-box { background-color: #162032; padding: 15px; border-radius: 8px; border-left: 4px solid #00ffcc; margin-top: 15px;}
</style>
""", unsafe_allow_html=True)

import os
if os.path.exists("logo1.png"):
    c_img1, c_img2, c_img3 = st.columns([2, 1, 2])
    with c_img2:
        st.image("logo1.png", use_container_width=True)

st.markdown('<div class="title-banner">S.P.E.A.R.</div>', unsafe_allow_html=True)


if os.path.exists("logo.png"):
    st.sidebar.image("logo.png", use_container_width=True)
st.sidebar.markdown("## Uzay Limanı & Hava Durumu")

API_KEY_FILE = ".weather_api_key"
default_api_key = ""
if os.path.exists(API_KEY_FILE):
    with open(API_KEY_FILE, "r") as f:
        default_api_key = f.read().strip()

api_key = st.sidebar.text_input("OpenWeatherMap API Key", value=default_api_key, type="password")
if api_key and api_key != default_api_key:
    with open(API_KEY_FILE, "w") as f:
        f.write(api_key)

spaceports = {
    "Nevşehir Spaceport (TR)": {"lat": 38.62, "lon": 34.71},
    "Cape Canaveral (USA)": {"lat": 28.39, "lon": -80.60},
    "Starbase (USA)": {"lat": 25.99, "lon": -97.15},
    "Baikonur (KAZ)": {"lat": 45.96, "lon": 63.30}
}

station_options = list(spaceports.keys()) + ["Özel Konum"]
selected_station = st.sidebar.selectbox("Fırlatma İstasyonu", station_options)

if selected_station == "Özel Konum":
    lat = st.sidebar.number_input("Enlem (Latitude)", value=41.0082, format="%.4f")
    lon = st.sidebar.number_input("Boylam (Longitude)", value=28.9784, format="%.4f")
    city_name = get_city_name(api_key, lat, lon)
    st.sidebar.markdown(f"**Tespit Edilen Şehir:** {city_name}")
else:
    lat = spaceports[selected_station]["lat"]
    lon = spaceports[selected_station]["lon"]

st.sidebar.markdown("### Fırlatma Tarih & Saati")
target_date = st.sidebar.date_input("Tarih", datetime.date.today())

st.sidebar.markdown("⏱️ **Saat Seçimi**")
c_hr, c_min = st.sidebar.columns(2)
target_hr = c_hr.slider("Saat", 0, 23, datetime.datetime.now().hour, format="%02d")
target_mn = c_min.slider("Dakika", 0, 59, datetime.datetime.now().minute, format="%02d")
target_time = datetime.time(target_hr, target_mn)

target_dt = datetime.datetime.combine(target_date, target_time)
target_timestamp = target_dt.timestamp()

weather_data = get_weather(api_key, lat, lon, target_timestamp)
wind = weather_data['wind_speed']
wind_deg = weather_data['wind_deg']
temp = weather_data['temp']
pressure = weather_data['pressure']

if weather_data['error']: st.sidebar.warning(weather_data['error'])

st.sidebar.markdown(f"**📍 Atmosfer:** {temp}°C, {pressure}hPa | Rüzgar: {wind}m/s | Zaman: {target_dt.strftime('%Y-%m-%d %H:%M')}")

st.sidebar.markdown("---")
st.sidebar.markdown("## 🎯 Yörünge Hedefleri (SECO)")

orbit_targets = {
    "LEO (Alçak Dünya Yörüngesi - 250x200 km)": (250000.0, 200000.0),
    "ISS (Uluslararası Uzay İstasyonu - 420x400 km)": (420000.0, 400000.0),
    "SSO (Güneş Eşzamanlı - 600x600 km)": (600000.0, 600000.0),
    "MEO (Orta Dünya Yörüngesi - 2000x2000 km)": (2000000.0, 2000000.0),
    "GTO (Yer Sabit Transfer - 35786x250 km)": (35786000.0, 250000.0)
}
selected_orbit = st.sidebar.selectbox("Hedef Yörünge", list(orbit_targets.keys()))
t_apogee = orbit_targets[selected_orbit][0]
t_perigee = orbit_targets[selected_orbit][1]

st.sidebar.markdown("---")
st.sidebar.markdown("## 🚀 Roket Konfigürasyonu")
rocket = st.sidebar.selectbox("Model", ["SpaceX Falcon 9", "SpaceX Starship"])
payload = st.sidebar.number_input("Payload (kg)", min_value=0, max_value=200000, value=12000, step=100)

if rocket == "SpaceX Falcon 9":
    area = 10.5
    stages = [
        {"dry_mass": 25000, "fuel": 411000, "thrust": 7600000, "isp": 311},  
        {"dry_mass": 4000,  "fuel": 111500, "thrust": 934000,  "isp": 348}   
    ]
elif rocket == "SpaceX Starship":
    area = 63.6
    stages = [
        {"dry_mass": 120000, "fuel": 3400000, "thrust": 72000000, "isp": 330}, 
        {"dry_mass": 100000, "fuel": 1200000, "thrust": 15000000, "isp": 380}  
    ]

should_run = st.sidebar.button("FIRLATMAYI BAŞLAT", type="primary")
if st.session_state.get('run_sim', False):
    should_run = True
    st.session_state.run_sim = False

if should_run:
    
    with st.spinner("Simülasyon çalıştırılıyor..."):
        sim_engine = PhysicsEngine(stages, area, payload, weather_data, t_apogee, t_perigee, lat)
        df_flight = sim_engine.simulate(dt=0.05, max_time=6000)
    
    final_vel = df_flight['Velocity'].iloc[-1]
    final_y = df_flight['Y'].iloc[-1]
    max_g = df_flight['G_Force'].max()
    
    mu_earth = 6.67430e-11 * 5.972e24
    v_target_approx = math.sqrt(mu_earth / (6371000.0 + t_perigee))
    
    if getattr(sim_engine, 'seco_achieved', False):
        st.success(f"🌠 SECO: ORBIT ACHIEVED (Hız={final_vel:.1f} m/s, İrtifa={final_y/1000:.1f} km)")
    else:
        st.error(f"💥 SECO BAŞARISIZ. Target Perigee ({t_perigee}) aşılamadı veya yakıt bitti.")
    
    # Data Table Analytics
    st.markdown("### GNC Uçuş Özeti")
    st_data = {
        "Max-Q Zamanı (s)": [f"{getattr(sim_engine, 'max_q_time', 0):.1f}"],
        "Yakıt Bitiş Süresi (s)": [f"{getattr(sim_engine, 'fuel_empty_time', 0):.1f}" if getattr(sim_engine, 'fuel_empty_time', None) else "Bitmedi"],
        "SECO Zamanı (s)": [f"{sim_engine.seco_time:.1f}" if getattr(sim_engine, 'seco_time', None) else "SECO Yok"],
        "Yörünge Tipi": [sim_engine.orbit_type]
    }
    st.table(pd.DataFrame(st_data))
    
    st.markdown("---")
    
    # G-Force Gauge
    g1, g2 = st.columns(2)
    with g1:
        fig_gf = go.Figure(go.Indicator(
            mode = "gauge+number",
            value = max_g, 
            title = {'text': "Max G-Kuvveti"},
            gauge = {
                'axis': {'range': [0, 10]},
                'bar': {'color': "#ff3366"},
                'steps': [
                    {'range': [0, 4], 'color': "darkgreen"},
                    {'range': [4, 7], 'color': "goldenrod"},
                    {'range': [7, 10], 'color': "red"}
                ]
            }
        ))
        fig_gf.update_layout(height=250, margin=dict(t=50, b=10, l=10, r=10), template="plotly_dark", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig_gf, use_container_width=True)
        
    with g2:
        # Anlık Hız Gauge (for balance)
        fig_v = go.Figure(go.Indicator(
            mode = "gauge+number",
            value = final_vel,
            title = {'text': "Nihai Hız Kadranı (m/s)"},
            gauge = {
                'axis': {'range': [0, max(10000, v_target_approx+1000)]},
                'bar': {'color': "#00ffcc"},
                'threshold': {
                    'line': {'color': "white", 'width': 4},
                    'thickness': 0.75,
                    'value': v_target_approx
                }
            }
        ))
        fig_v.update_layout(height=250, margin=dict(t=50, b=10, l=10, r=10), template="plotly_dark", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig_v, use_container_width=True)
        
    st.markdown("### Çok Adımlı Uçuş Profili")
    r_stage1, r_stage2 = st.columns(2)
    stage_changes = df_flight[df_flight['Stage'].diff() > 0]
    
    with r_stage1:
        fig_alt_t = go.Figure()
        fig_alt_t.add_trace(go.Scatter(x=df_flight['Time'], y=df_flight['Y']/1000, mode='lines', name='İrtifa', line=dict(color='#00ffcc', width=3)))
        
        # Stage Ayrılma anını işaretle (Staged Separation)
        for _, row_s in stage_changes.iterrows():
            fig_alt_t.add_vline(x=row_s['Time'], line_dash="dash", line_color="orange", annotation_text="Stage Separation")
            fig_alt_t.add_trace(go.Scatter(x=[row_s['Time']], y=[row_s['Y']/1000], mode='markers', name='MECO Noktası', marker=dict(color='orange', size=12, symbol='x')))
            
        fig_alt_t.update_layout(title="İrtifa Projeksiyonu (Ayrılma Tespiti)", xaxis_title="Zaman (s)", yaxis_title="İrtifa (km)", template="plotly_dark", height=400)
        st.plotly_chart(fig_alt_t, use_container_width=True)
        
    with r_stage2:
        # İvme (Acceleration) Analizi vs Zaman (dV/dt)
        fig_acc = go.Figure()
        acceleration = np.gradient(df_flight['Velocity'], df_flight['Time'])
        
        fig_acc.add_trace(go.Scatter(x=df_flight['Time'], y=acceleration, mode='lines', fill='tozeroy', name='Kinetik İvme (a)', line=dict(color='#ffaa00', width=3)))
        
        for _, row_s in stage_changes.iterrows():
            fig_acc.add_vline(x=row_s['Time'], line_dash="dash", line_color="orange", annotation_text="MECO (Kütle Azalımı)", annotation_position="top left")
            
        fig_acc.update_layout(title="Türevsel Kinematik (dV/dt) İvme Analizi", xaxis_title="Zaman (s)", yaxis_title="İvme (m/s²)", template="plotly_dark", height=400)
        st.plotly_chart(fig_acc, use_container_width=True)
        
    st.markdown("### 📈 Yörünge & Atmosfer Analizi")
    rc1, rc2 = st.columns(2)
    with rc1:
        fig_orb = go.Figure()
        theta_earth = np.linspace(0, 2*np.pi, 200)
        ex = 6371000.0 * np.cos(theta_earth)
        ey = 6371000.0 * np.sin(theta_earth)
        # We plot the full Earth circle centered at (0,0) instead of bottom normalized
        fig_orb.add_trace(go.Scatter(x=ex/1000, y=ey/1000, mode='lines', fill='toself', name='Dünya Yüzeyi (r=6371km)', line=dict(color='#003366', width=2)))
        
        rocket_radius = 6371000.0 + df_flight['Y']
        rocket_theta = (np.pi/2) - (df_flight['X'] / 6371000.0) 
        rx = rocket_radius * np.cos(rocket_theta)
        ry = rocket_radius * np.sin(rocket_theta)
        
        fig_orb.add_trace(go.Scatter(x=rx/1000, y=ry/1000, mode='lines', name='Rota', line=dict(color='#00ffcc', width=3)))
        
        fig_orb.update_layout(title="Dünya Merkezli Yörünge Haritası", xaxis_title="X (km)", yaxis_title="Y (km)", template="plotly_dark", height=450)
        fig_orb.update_yaxes(scaleanchor="x", scaleratio=1)
        st.plotly_chart(fig_orb, use_container_width=True)

    with rc2:
        fig_vel = go.Figure()
        fig_vel.add_trace(go.Scatter(x=df_flight['Time'], y=df_flight['Velocity'], mode='lines', name='Hız', line=dict(color='#00ffff', width=3)))
        if v_target_approx > 0:
            fig_vel.add_hline(y=v_target_approx, line_dash="dash", line_color="red", annotation_text="Vis-Viva Hedef Hızı")
        fig_vel.update_layout(title="Hız vs Zaman", xaxis_title="Zaman (s)", yaxis_title="Hız (m/s)", template="plotly_dark", height=450)
        st.plotly_chart(fig_vel, use_container_width=True)

    r2c1, r2c2 = st.columns(2)
    with r2c1:
        fig_g = go.Figure()
        fig_g.add_trace(go.Scatter(x=df_flight['Time'], y=df_flight['G_Force'], mode='lines', name='G-Force', line=dict(color='#ff3366', width=3)))
        if getattr(sim_engine, 'max_q', 0) > 0:
            stg_maxq = df_flight.loc[df_flight['Dyn_Pressure'].idxmax()]
            fig_g.add_annotation(x=stg_maxq['Time'], y=stg_maxq['G_Force'], text="Max-Q Noktası", showarrow=True, arrowhead=1, ax=0, ay=-40, font=dict(color='yellow'))
            fig_g.add_trace(go.Scatter(x=[stg_maxq['Time']], y=[stg_maxq['G_Force']], mode='markers', name='Max-Q', marker=dict(color='yellow', size=14, symbol='star')))
        fig_g.update_layout(title="G-Force Analitiği", xaxis_title="Zaman (s)", yaxis_title="G-Kuvveti (G)", template="plotly_dark", height=400)
        st.plotly_chart(fig_g, use_container_width=True)

    with r2c2:
        fig_q = go.Figure()
        fig_q.add_trace(go.Scatter(x=df_flight['Time'], y=df_flight['Dyn_Pressure']/1000, mode='lines', fill='tozeroy', name='Dinamik Basınç (q)', line=dict(color='#11dd88', width=3)))
        fig_q.update_layout(title="Dinamik Basınç Serüveni (q)", xaxis_title="Zaman (s)", yaxis_title="Basınç (kPa)", template="plotly_dark", height=400)
        st.plotly_chart(fig_q, use_container_width=True)

    st.markdown("### 📊 Enerji, Kütle ve İtki Analizleri")
    
    e1, e2 = st.columns(2)
    with e1:
        # Kütle (Mass) vs. Zaman
        fig_mass = go.Figure()
        fig_mass.add_trace(go.Scatter(x=df_flight['Time'], y=df_flight['Mass']/1000, mode='lines', name='Toplam Kütle (ton)', line=dict(color='#ff9900', width=3)))
        for _, row_s in stage_changes.iterrows():
            fig_mass.add_vline(x=row_s['Time'], line_dash="dash", line_color="red", annotation_text="Kademe Ayrılması")
        fig_mass.update_layout(title="Kütle Tüketimi ve Kademe Ayrılmaları", xaxis_title="Zaman (s)", yaxis_title="Kütle (ton)", template="plotly_dark", height=400)
        st.plotly_chart(fig_mass, use_container_width=True)

    with e2:
        # Kinetik Enerji vs. Potansiyel Enerji
        fig_energy = go.Figure()
        fig_energy.add_trace(go.Scatter(x=df_flight['Time'], y=df_flight['Kinetic_Energy']/1e9, mode='lines', name='Kinetik Enerji (GJ)', fill='tonexty', line=dict(color='#00ffcc', width=2)))
        fig_energy.add_trace(go.Scatter(x=df_flight['Time'], y=df_flight['Potential_Energy']/1e9, mode='lines', name='Potansiyel Enerji (GJ)', fill='tozeroy', line=dict(color='#ff3366', width=2)))
        fig_energy.update_layout(title="Kinetik ve Potansiyel Enerji Dengesi", xaxis_title="Zaman (s)", yaxis_title="Enerji (GigaJoule)", template="plotly_dark", height=400)
        st.plotly_chart(fig_energy, use_container_width=True)

    e3, e4 = st.columns(2)
    with e3:
        # Özgül İtki (Isp) vs. İrtifa
        fig_isp = go.Figure()
        fig_isp.add_trace(go.Scatter(x=df_flight['Y']/1000, y=df_flight['Isp'], mode='lines', name='Isp Değişimi', line=dict(color='#b366ff', width=3)))
        fig_isp.update_layout(title="Özgül İtki (Isp) vs İrtifa", xaxis_title="İrtifa (km)", yaxis_title="Isp (saniye)", template="plotly_dark", height=400)
        st.plotly_chart(fig_isp, use_container_width=True)

    with e4:
        # Kalan Delta-V vs. Zaman
        fig_dv = go.Figure()
        fig_dv.add_trace(go.Scatter(x=df_flight['Time'], y=df_flight['Delta_V_Rem']/1000, mode='lines', fill='tozeroy', name='Kalan Delta-V', line=dict(color='#3399ff', width=3)))
        for _, row_s in stage_changes.iterrows():
            fig_dv.add_vline(x=row_s['Time'], line_dash="dash", line_color="orange", annotation_text="Ayrılma")
        fig_dv.update_layout(title="Kalan Delta-V (Manevra Kapasitesi)", xaxis_title="Zaman (s)", yaxis_title="Delta-V (km/s)", template="plotly_dark", height=400)
        st.plotly_chart(fig_dv, use_container_width=True)

    st.markdown("###  Gelişmiş Görev Telemetrisi & Karar Sistemleri")
    
    # 1. Yörünge Yüksekliği Sapması
    target_orbit_alt = t_perigee if final_y <= t_apogee else t_apogee
    y_deviation = final_y - target_orbit_alt
    st.metric(label="Yörünge Yüksekliği Sapması (İrtifa - Hedef)", value=f"{final_y/1000:.2f} km", delta=f"{y_deviation/1000:.2f} km (Hata Payı)", delta_color="inverse")
    
    # 2. Otonom Sistem Karar Logu
    st.markdown("#### Otonom Sistem Karar Logu")
    events = [{"Time (s)": 0.0, "Event": "Ateşleme (Lift-off)", "Detail": "Motorlar tam güçte başlatıldı"}]
    
    # Pitch kick (Gravity turn start)
    pitch_kick = df_flight[df_flight['Pitch'] < 90.0]
    if not pitch_kick.empty:
        pk_time = pitch_kick.iloc[0]['Time']
        events.append({"Time (s)": pk_time, "Event": "Gravity Turn (Pitch Kick) Başladı", "Detail": "Roket dikeyden eğilmeye başladı."})
        
    # Mach 1
    mach1 = df_flight[df_flight['Mach'] >= 1.0]
    if not mach1.empty:
        m1_time = mach1.iloc[0]['Time']
        events.append({"Time (s)": m1_time, "Event": "Ses Duvarı Geçişi (Mach 1)", "Detail": "Transonik bölgeye giriş."})
        
    # Max-Q
    if getattr(sim_engine, 'max_q_time', 0) > 0:
        events.append({"Time (s)": sim_engine.max_q_time, "Event": "Max-Q", "Detail": f"Maksimum dinamik basınç {sim_engine.max_q/1000:.1f} kPa."})
        
    # Stage Separations
    for _, row_s in stage_changes.iterrows():
        events.append({"Time (s)": row_s['Time'], "Event": f"Kademe Ayrılması (Stage {int(row_s['Stage'])-1} -> {int(row_s['Stage'])})", "Detail": "Alt kademe ayrıldı, yeni ateşleme."})
        
    # SECO
    if getattr(sim_engine, 'seco_time', None):
        events.append({"Time (s)": sim_engine.seco_time, "Event": "SECO (Second Engine Cutoff)", "Detail": f"Hedef hıza ulaşıldı, motorlar susturuldu. Yörünge: {sim_engine.orbit_type}"})
        
    events_df = pd.DataFrame(events).sort_values(by="Time (s)")
    st.table(events_df.style.format({"Time (s)": "{:.2f}"}))
    
    # New Graphs Layout
    m1, m2 = st.columns(2)
    with m1:
        # 3. Mach Sayısı vs. Zaman
        fig_mach = go.Figure()
        fig_mach.add_trace(go.Scatter(x=df_flight['Time'], y=df_flight['Mach'], mode='lines', name='Mach Sayısı', line=dict(color='#ffff00', width=3)))
        fig_mach.add_hline(y=1.0, line_dash="dash", line_color="red", annotation_text="Mach 1 (Ses Hızı)")
        fig_mach.update_layout(title="Mach Sayısı vs. Zaman", xaxis_title="Zaman (s)", yaxis_title="Mach", template="plotly_dark", height=400)
        st.plotly_chart(fig_mach, use_container_width=True)
        
    with m2:
        # 4. Sürüklenme Katsayısı (Cd) Değişimi
        fig_cd = go.Figure()
        fig_cd.add_trace(go.Scatter(x=df_flight['Mach'], y=df_flight['Drag_Coeff'], mode='lines', name='Cd', line=dict(color='#ff5500', width=3)))
        if not mach1.empty:
            fig_cd.add_vrect(x0=0.8, x1=1.2, fillcolor="red", opacity=0.2, line_width=0, annotation_text="Transonik Şok")
        fig_cd.update_layout(title="Trasonik Aerodinamik: Sürüklenme Katsayısı (Cd) Değişimi", xaxis_title="Mach Sayısı", yaxis_title="Cd (Drag Coeff)", template="plotly_dark", height=400)
        st.plotly_chart(fig_cd, use_container_width=True)

    m3, m4 = st.columns(2)
    with m3:
        # 5. Sıcaklık Grafiği (Stagnation / Hull Temp)
        fig_temp = go.Figure()
        fig_temp.add_trace(go.Scatter(x=df_flight['Time'], y=df_flight['Hull_Temp'] - 273.15, mode='lines', fill='tozeroy', name='Gövde Sıcaklığı', line=dict(color='#ff3300', width=3)))
        fig_temp.update_layout(title="Sürtünme Kaynaklı Tahmini Gövde Isısı", xaxis_title="Zaman (s)", yaxis_title="Sıcaklık (°C)", template="plotly_dark", height=400)
        st.plotly_chart(fig_temp, use_container_width=True)
        
    with m4:
        # 6. TWR Değişimi
        fig_twr = go.Figure()
        fig_twr.add_trace(go.Scatter(x=df_flight['Time'], y=df_flight['TWR'], mode='lines', name='TWR', line=dict(color='#00ff88', width=3)))
        for _, row_s in stage_changes.iterrows():
            fig_twr.add_vline(x=row_s['Time'], line_dash="dash", line_color="red", annotation_text="Kademe Ayrılması")
        fig_twr.update_layout(title="TWR (İtki-Ağırlık Oranı) Karakteristiği", xaxis_title="Zaman (s)", yaxis_title="TWR", template="plotly_dark", height=400)
        st.plotly_chart(fig_twr, use_container_width=True)

    st.markdown("###  Telemetri Çıktısı (3 Saniyede 1 Kayıt)")
    df_display = df_flight.iloc[::60]
    num_cols = df_display.select_dtypes(include=['float64', 'int64']).columns
    st.dataframe(df_display.style.format("{:.2f}", subset=num_cols, na_rep=''), use_container_width=True, height=600)
    
    df_display.to_csv("flight_telemetry.csv", index=False)
    st.info(" Ham telemetri verisi (3 sn aralıklı) **flight_telemetry.csv** dosyasına kaydedildi.")

    # ------ YENİ AI MODÜLÜ (GÖREV DEĞERLENDİRME) ------
    import ai_analyzer
    st.markdown("---")
    st.markdown("###  S.P.E.A.R. AI Görev Analiz Raporu")
    
    try:
        api_key_ai = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        api_key_ai = ""
        
    with st.spinner("S.P.E.A.R. AI Görev Verilerini Yorumluyor"):
        ai_report = ai_analyzer.perform_ai_analysis("flight_telemetry.csv", api_key_ai)
        st.success("✅ Operasyon Değerlendirmesi Tamamlandı")
        st.markdown(f"> {ai_report}")

# ==========================================
# MODULE 4: DRIVER.JS ONBOARDING TOUR
# ==========================================
if st.session_state.tour_active:
    driver_js = """
    <script>
        const doc = window.parent.document;
        
        if (!doc.getElementById('driver-css')) {
            const link = doc.createElement('link');
            link.id = 'driver-css';
            link.rel = 'stylesheet';
            link.href = 'https://cdn.jsdelivr.net/npm/driver.js@1.0.1/dist/driver.css';
            doc.head.appendChild(link);
        }
        
        if (!doc.getElementById('driver-custom-css')) {
            const style = doc.createElement('style');
            style.id = 'driver-custom-css';
            style.innerHTML = `
                .dark-driver-popover {
                    background-color: #0f172a !important;
                    color: white !important;
                    border: 1px solid #334155 !important;
                }
                .dark-driver-popover .driver-popover-title {
                    color: white !important;
                    font-size: 1.2rem !important;
                }
                .dark-driver-popover .driver-popover-description {
                    color: #cbd5e1 !important;
                }
                .dark-driver-popover .driver-popover-next-btn, 
                .dark-driver-popover .driver-popover-prev-btn {
                    background-color: orange !important;
                    color: white !important;
                    text-shadow: none !important;
                    border: none !important;
                }
                .dark-driver-popover .driver-popover-close-btn {
                    color: white !important;
                }
                .dark-driver-popover .driver-popover-progress-text {
                    color: #cbd5e1 !important;
                }
            `;
            doc.head.appendChild(style);
        }

        function runDriver() {
            if (!window.parent.driver) return setTimeout(runDriver, 100);
            const driver = window.parent.driver.js.driver;
            
            let steps_config = [];
            
            // 0. Genel Karşılama / Görev Brifingi (Ekranda ortalanmış şekilde açılır)
            steps_config.push({
                popover: {
                    title: 'DEMO',
                    description: 'S.P.E.A.R. Tanıtım Turuna Hoş Geldiniz! Bu turda size başarılı bir fırlatma operasyonu için gerekli olan tüm parametreleri ve metrikleri tanıtacağım. Her şey hazırsa başlayalım.',
                    align: 'center'
                }
            });

            const pushStep = (el, title, desc, side) => {
                if (el) {
                    steps_config.push({
                        element: el,
                        popover: { title: title, description: desc, side: side, align: 'start' }
                    });
                }
            };

            // 1'den 7'ye kadar olan Sidebar Inputları
            pushStep(doc.querySelectorAll('div[data-testid="stTextInput"]')[0], '1. API Bağlantısı', 'Gerçek zamanlı hava durumu verisi için OpenWeatherMap API anahtarınızı buraya girin.', 'right');
            pushStep(doc.querySelectorAll('div[data-testid="stSelectbox"]')[0], '2. Fırlatma İstasyonu', 'Dünya üzerindeki stratejik fırlatma noktalarından birini seçin.', 'right');
            pushStep(doc.querySelectorAll('div[data-testid="stDateInput"]')[0], '3. Fırlatma Tarihi', 'Görevin gerçekleştirileceği tarihi planlayın.', 'right');
            pushStep(doc.querySelectorAll('div[data-testid="stSlider"]')[0], '4. Zaman Çizelgesi', 'Fırlatma saati ve dakikasını hassas olarak ayarlayın.', 'right');
            pushStep(doc.querySelectorAll('div[data-testid="stSelectbox"]')[1], '5. Yörünge Hedefi', 'Roketin ulaşması hedeflenen yörüngeyi buradan belirleyin.', 'right');
            pushStep(doc.querySelectorAll('div[data-testid="stSelectbox"]')[2], '6. Araç Konfigürasyonu', 'Görevinize uygun fırlatma aracını seçin.', 'right');
            pushStep(doc.querySelectorAll('div[data-testid="stNumberInput"]')[0], '7. Faydalı Yük (Payload)', 'Yörüngeye taşınacak yükün kütlesi.', 'right');
            
            // 8. Fırlatmayı Başlat Butonu 
            pushStep(doc.querySelector('div[data-testid="stSidebar"] button'), '8. Operasyonu Başlat', 'Tüm ayarlarınızı manuel olarak test etmek istediğinizde operasyonu bu butondan tetikleyebilirsiniz. (Tur başladığında simülasyon sizin için çoktan otomatik çalıştırıldı!)', 'right');

            // 9. Çıktılar (Ana Ekran)
            pushStep(doc.querySelector('section[data-testid="stMain"]'), '8. Tüm Uçuş Çıktıları', 'Başarılı! Biz konuşurken arka planda simülasyon tamamlandı. Fırlatma profilini, anlık telemetri ve otonom sistem loglarını detaylıca buradan inceleyebilirsiniz.', 'left');

            const driverObj = driver({
              showProgress: true,
              animate: true,
              overlayOpacity: 0.8,
              popoverClass: 'dark-driver-popover',
              steps: steps_config,
              onDestroyStarted: () => {
                if (!driverObj.hasNextStep() || confirm("Turu sonlandırmak istediğinize emin misiniz?")) {
                  driverObj.destroy();
                }
              }
            });

            driverObj.drive();
        }

        if (!doc.getElementById('driver-js')) {
            const script = doc.createElement('script');
            script.id = 'driver-js';
            script.src = 'https://cdn.jsdelivr.net/npm/driver.js@1.0.1/dist/driver.js.iife.js';
            script.onload = () => setTimeout(runDriver, 500);
            doc.head.appendChild(script);
        } else {
            setTimeout(runDriver, 500);
        }
    </script>
    """
    st.components.v1.html(driver_js, width=0, height=0)
    st.session_state.tour_active = False