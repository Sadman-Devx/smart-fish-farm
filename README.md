# 🐟 AquaSmart — Smart Fish Farm Management System

<p align="center">
  <img src="https://img.shields.io/badge/Django-5.2-092E20?style=for-the-badge&logo=django&logoColor=white"/>
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white"/>
  <img src="https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white"/>
  <img src="https://img.shields.io/badge/Celery-37814A?style=for-the-badge&logo=celery&logoColor=white"/>
  <img src="https://img.shields.io/badge/Google_Gemini-4285F4?style=for-the-badge&logo=google&logoColor=white"/>
  <img src="https://img.shields.io/badge/REST_API-005571?style=for-the-badge&logo=fastapi&logoColor=white"/>
</p>

<p align="center">
  A full-featured, intelligent fish farm management platform built with Django — featuring real-time weather integration, AI-powered disease diagnosis, IoT sensor support, automated feeding schedules, water quality alerts, ML-based growth prediction, and advanced analytics.
</p>

---

## 📋 Table of Contents

- [Features](#-features)
- [Tech Stack](#-tech-stack)
- [Project Structure](#-project-structure)
- [Getting Started](#-getting-started)
- [Environment Variables](#-environment-variables)
- [Running the Project](#-running-the-project)
- [API Reference](#-api-reference)
- [Core Concepts](#-core-concepts)
- [Automated Tasks](#-automated-tasks)
- [Security](#-security)
- [User Roles & Guest Access](#-user-roles--guest-access)

---

## ✨ Features

### 🤖 AI Fish Doctor
- **Google Gemini AI** powered fish disease diagnosis chatbot
- Upload fish images for visual disease detection
- Bilingual support (English & Bengali)
- Automatic disease severity detection (mild / moderate / critical)
- Disease history logging with recurring alert system
- Rate-limited per user to prevent API abuse

### 🌤️ Weather & Feeding Intelligence
- **Live weather integration** using OpenWeatherMap API
- GPS auto-detect or manual Bangladesh district/upazila selection
- **Smart feeding suggestion** based on temperature and humidity (Good / Reduce 30% / Minimal)
- **Automated daily feeding schedule** — morning (60%) and evening (40%) split per batch
- Weather-based feed rate calculation using temperature bands and biomass

### 🐟 Farm Management
- Multi-pond management with detailed pond profiles
- Fish batch tracking (species, stocking date, count, weight)
- Growth record logging with weekly weight tracking
- Mortality log with cause-of-death categorization
- Harvest records with revenue tracking
- Pond notes for field observations

### 💧 Water Quality Monitoring
- Manual water quality entry (temperature, dissolved oxygen, pH, rainfall)
- **IoT sensor support** via REST API — sensors can POST data directly
- **Automated water temperature logging** daily at 9:00 AM
- Real-time water quality alerts on dashboard
- Water quality heatmap visualization

### 🚨 Alert System
- Automatic alert generation when water quality is out of safe range:
  - Dissolved Oxygen < 4.0 mg/L → Critical
  - Water Temperature > 34°C → Critical
  - pH out of range (6.5–9.0) → Warning
- Email alerts sent immediately when critical conditions detected
- Disease alerts with recurring detection (same disease 3+ times)
- Dashboard alert banners with resolve functionality

### 📊 Analytics & Reports
- **Fish Growth Chart** — dual Y-axis (weight + count) with Chart.js
- **Profit/Loss Report** — monthly revenue vs expenses breakdown
- **Mortality Rate Tracker** — deaths by cause with trend charts
- **Daily Feed & Temperature** table (last 14 days)
- **ML-based growth prediction** using scikit-learn
- **FCR (Feed Conversion Ratio)** analytics
- **Benchmarking** — compare farm performance against industry standards
- Feed consumption, biomass, and weather trend charts

### 🔐 Security & Accounts
- Custom user model with role-based access (Owner, Manager, Worker, Viewer)
- Two-Factor Authentication (Email OTP)
- Google OAuth login (django-allauth)
- Brute-force protection — 5 attempts → 15-minute lockout
- Active session tracking and remote session revocation
- **Danger Zone** — Hard delete all farm data with double confirmation (type DELETE + password)
- Google OAuth users skip password requirement on data deletion

### 🌱 Onboarding Flow
- 4-step farm setup after registration:
  1. Farm basic info (name, size, ponds, water source)
  2. Location — GPS auto-detect or manual district/upazila selection
  3. Fish species and experience level
  4. Weather data fetched automatically from farm location

### 👁️ Guest Mode
- Guests can browse all read-only pages (Dashboard, Ponds, Reports)
- Write operations (add/edit/delete) require login
- AI Fish Doctor and Analytics Dashboard require login
- Sidebar clearly shows locked items with 🔒 icon

---

## 🛠️ Tech Stack

| Category | Technology |
|----------|-----------|
| Backend | Django 5.2 |
| Database | PostgreSQL |
| Cache / Session | Redis |
| Task Queue | Celery + Celery Beat |
| REST API | Django REST Framework |
| AI / LLM | Google Gemini (google-genai) |
| ML | scikit-learn, numpy, pandas |
| Weather | OpenWeatherMap API |
| SMS | Twilio |
| Auth | django-allauth (Google OAuth + Email OTP) |
| Charts | Chart.js |
| Frontend | Vanilla HTML/CSS/JS (dark theme) |
| Image Processing | Pillow |

---

## 📁 Project Structure

```
smart-fish-farm/
│
├── accounts/                    # User authentication & security
│   ├── models.py                # User, OTPToken, UserSession, LoginAttempt
│   ├── views.py                 # Login, Register, OTP, Profile, Sessions, Delete Data
│   ├── forms.py                 # LoginForm, RegisterForm, OTPForm, ProfileForm
│   ├── security.py              # Rate limiting, brute-force lockout, session tracking
│   ├── backends.py              # Email-based authentication backend
│   ├── middleware.py            # Session activity middleware
│   └── urls.py                  # accounts: login, register, profile, delete_all_data ...
│
├── farm/                        # Core farm management app
│   ├── models.py                # Pond, FishBatch, GrowthRecord, WeatherRecord,
│   │                            # DailyWeather, FeedingProfile, FeedLog,
│   │                            # FeedingReminder, SensorReading, HarvestRecord,
│   │                            # Expense, MortalityLog, FarmAlert, PondNote,
│   │                            # FarmProfile, PerformanceLog, BenchmarkRun,
│   │                            # DiseaseLog, DiseaseAlert
│   ├── views.py                 # Dashboard, Batch, Pond, Feed, Weather, Reports
│   │                            # (Pond list/detail: public read-only for guests)
│   ├── ai_agent_views.py        # Fish Doctor — Gemini AI disease diagnosis
│   ├── api_views.py             # REST API endpoints (IoT sensor support)
│   ├── api_urls.py              # DRF URL routing
│   ├── onboarding_views.py      # 4-step farm onboarding flow
│   ├── onboarding_forms.py      # Onboarding step forms
│   ├── tasks.py                 # Celery tasks (feed alert, auto temperature, alerts)
│   ├── notifications.py         # Email & SMS notification helpers
│   ├── serializers.py           # DRF serializers for API
│   ├── bd_geo.py                # Bangladesh district/upazila geodata
│   │
│   └── services/                # Business logic layer
│       ├── feed_calculator.py   # Smart feed kg calculation (biomass + temp)
│       ├── weather_ingest.py    # OpenWeatherMap API integration
│       ├── growth_prediction.py # Fish growth prediction algorithm
│       ├── ml_prediction.py     # scikit-learn ML prediction models
│       ├── analytics.py         # Analytics data processing
│       ├── benchmarking.py      # Farm performance benchmarking
│       ├── fcr_analytics.py     # Feed Conversion Ratio analytics
│       ├── predictive_alerts.py # Predictive alert generation
│       ├── water_heatmap.py     # Water quality heatmap data
│       └── generate_water_alerts.py # Automated alert generation
│
├── smart_fish_farm/             # Django project settings
│   ├── settings.py              # All settings (fully env-based configuration)
│   ├── urls.py                  # Root URLs + custom 404/500/403 handlers
│   ├── celery.py                # Celery app configuration
│   ├── asgi.py
│   └── wsgi.py
│
├── templates/                   # HTML templates (dark theme)
│   ├── base.html                # Base layout, sidebar, guest-aware navigation
│   ├── 404.html                 # Custom 404 — Page Not Found
│   ├── 500.html                 # Custom 500 — Server Error
│   ├── 403.html                 # Custom 403 — Access Denied
│   ├── accounts/                # Login, Register, Profile, OTP, Sessions
│   └── farm/                    # Dashboard, Pond, Batch, Reports, AI Doctor
│       └── onboarding/          # 4-step onboarding templates
│
├── static/                      # CSS, JS, images, PWA icons
├── manage.py
├── requirements.txt
└── .env.example
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL
- Redis

### Installation

**1. Clone the repository:**
```bash
git clone https://github.com/Sadman-Devx/smart-fish-farm.git
cd smart-fish-farm
```

**2. Create and activate virtual environment:**
```bash
python -m venv .venv

# Windows
.\.venv\Scripts\Activate.ps1

# Linux/Mac
source .venv/bin/activate
```

**3. Install dependencies:**
```bash
pip install -r requirements.txt
```

**4. Copy and configure environment file:**
```bash
cp .env.example .env
```

**5. Generate a secure secret key:**
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```
Copy the output and set it as `SECRET_KEY` in your `.env`.

**6. Run migrations:**
```bash
python manage.py migrate
```

**7. Create superuser:**
```bash
python manage.py createsuperuser
```

---

## ⚙️ Environment Variables

Edit `.env` with your credentials:

```env
# ── Django ────────────────────────────────────────────
SECRET_KEY=your-secure-random-key-here
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost

# ── Database (PostgreSQL) ─────────────────────────────
DB_NAME=smart_fish_farm
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_HOST=localhost
DB_PORT=5432

# ── Redis ─────────────────────────────────────────────
REDIS_CACHE_URL=redis://localhost:6379/1
CELERY_BROKER_URL=redis://localhost:6379/0

# ── Weather API (OpenWeatherMap) ──────────────────────
OPENWEATHER_API_KEY=your_openweathermap_api_key
OPENWEATHER_LOCATION=Dhaka,BD

# ── AI (Google Gemini) ────────────────────────────────
GOOGLE_API_KEY=your_google_gemini_api_key

# ── Email (Gmail SMTP) ────────────────────────────────
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your_email@gmail.com
EMAIL_HOST_PASSWORD=your_gmail_app_password
FARM_NOTIFICATION_EMAIL=your_email@gmail.com

# ── Twilio SMS (optional) ─────────────────────────────
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_token
TWILIO_FROM_NUMBER=+1234567890
TWILIO_TO_NUMBER=+8801XXXXXXXXX

# ── Google OAuth (optional) ───────────────────────────
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
```

---

## ▶️ Running the Project

Start all required services in **4 separate terminals**:

```bash
# Terminal 1 — Redis
redis-server

# Terminal 2 — Celery Worker
python -m celery -A smart_fish_farm worker -l info -P solo

# Terminal 3 — Celery Beat (Scheduled Tasks)
python -m celery -A smart_fish_farm beat -l info

# Terminal 4 — Django Development Server
python manage.py runserver
```

Open in browser:
- **Dashboard:** http://127.0.0.1:8000/
- **Admin Panel:** http://127.0.0.1:8000/admin/

---

## 🔌 API Reference

Base URL: `http://127.0.0.1:8000/api/`

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/ponds/` | GET, POST | Optional / Required | List / create ponds |
| `/api/batches/` | GET, POST | Optional / Required | List / create fish batches |
| `/api/batches/<pk>/` | GET | Optional | Batch detail |
| `/api/batches/<pk>/prediction/` | GET | Optional | ML growth prediction |
| `/api/growth-records/` | GET, POST | Optional / Required | Growth records |
| `/api/weather-records/` | GET, POST | Optional / Required | Water quality (IoT) |
| `/api/feed-logs/` | GET, POST | Optional / Required | Feed logs |

### IoT Sensor Example

POST water quality data from a sensor:

```bash
curl -X POST http://127.0.0.1:8000/api/weather-records/ \
  -H "Content-Type: application/json" \
  -d '{
    "pond": 1,
    "water_temp_c": 28.5,
    "dissolved_oxygen_mg_l": 6.2,
    "ph": 7.1,
    "rainfall_mm": 0
  }'
```

Alerts are automatically triggered if values are out of safe range.

---

## 🧠 Core Concepts

### Smart Feed Calculation

```
Biomass (kg) = Surviving Fish × Avg Weight (g) ÷ 1000
Base Feed    = Biomass × Feed Rate % (from FeedingProfile)
Final Feed   = Base Feed × Temperature Factor
```

| Temperature | Factor |
|-------------|--------|
| < 18°C | 0.10 (minimal) |
| 18–21°C | 0.40 |
| 22–25°C | 0.70 |
| 26–30°C | 1.00 (optimal) |
| > 30°C | 0.90 |

### Water Quality Safe Ranges

| Parameter | Safe Range | Alert Threshold |
|-----------|-----------|-----------------|
| Dissolved Oxygen | > 5.0 mg/L | < 4.0 = Critical |
| Water Temperature | 22–31°C | > 34°C = Critical |
| pH | 6.5–9.0 | Outside = Warning |

---

## ⏰ Automated Tasks

Powered by **Celery Beat** — runs automatically:

| Schedule | Task |
|----------|------|
| 6:00 AM daily | 📧 Daily feed alert email with schedule |
| 9:00 AM daily | 🌡️ Auto water temperature logging for all ponds |
| Every hour | 🔔 Predictive alert generation |

---

## 🔐 Security

| Feature | Details |
|---------|---------|
| Brute-force protection | 5 failed attempts → 15-minute lockout (per IP + email) |
| Two-Factor Auth | Email OTP, 10-minute expiry |
| Google OAuth | django-allauth with PKCE enabled |
| Session tracking | Active session list with remote revocation |
| CSRF protection | Enabled on all POST endpoints |
| Danger Zone | Hard delete all data — requires typing `DELETE` + password |
| Google OAuth delete | Password-less delete — active session confirms identity |
| Custom error pages | 403 / 404 / 500 pages (active when DEBUG=False) |

---

## 👥 User Roles & Guest Access

### User Roles

| Role | Access |
|------|--------|
| Owner | Full access |
| Manager | Farm management |
| Worker | Log feed, growth, mortality |
| Viewer | Read-only dashboard |

### Guest Access

| Section | Guest | Logged-in |
|---------|-------|-----------|
| Dashboard | ✅ View | ✅ Full |
| Ponds (list + detail) | ✅ Read-only | ✅ Full |
| Harvests / Expenses / P&L | ✅ Read-only | ✅ Full |
| Alerts / Reports / Reminders | ✅ Read-only | ✅ Full |
| Add / Edit / Delete anything | 🔒 Login required | ✅ |
| Analytics Dashboard | 🔒 Login required | ✅ |
| Fish Doctor (AI) | 🔒 Login required | ✅ |

---

## 📄 License

This project is developed for academic research purposes at **Daffodil International University**.

---

<p align="center">
  Built by <a href="https://github.com/Sadman-Devx">Sadman Sakib</a>
</p>