# 🐟 AquaSmart — Smart Fish Farm Management System

<p align="center">
  <img src="https://img.shields.io/badge/Django-5.2-092E20?style=for-the-badge&logo=django&logoColor=white"/>
  <img src="https://img.shields.io/badge/Python-3.14-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white"/>
  <img src="https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white"/>
  <img src="https://img.shields.io/badge/Celery-37814A?style=for-the-badge&logo=celery&logoColor=white"/>
  <img src="https://img.shields.io/badge/REST_API-005571?style=for-the-badge&logo=fastapi&logoColor=white"/>
</p>

<p align="center">
  A full-featured, intelligent fish farm management platform built with Django — featuring real-time weather integration, automated feeding schedules, IoT sensor support, water quality alerts, and advanced analytics.
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
- [Screenshots](#-screenshots)

---

## ✨ Features

### 🌤️ Weather & Feeding Intelligence
- **Live weather integration** using OpenWeatherMap API — supports GPS coordinates and district/upazila name (Bangladesh)
- **Smart feeding suggestion** based on temperature and humidity conditions (Good / Reduce 30% / Minimal)
- **Automated daily feeding schedule** — morning (60%) and evening (40%) split per batch
- **Weather-based feed rate calculation** using temperature bands and biomass

### 🐟 Farm Management
- Multi-pond management with detailed pond profiles
- Fish batch tracking (species, stocking date, count, weight)
- Growth record logging with weekly weight tracking
- Mortality log with cause-of-death categorization
- Harvest records with revenue tracking

### 💧 Water Quality Monitoring
- Manual water quality entry (temperature, dissolved oxygen, pH, rainfall)
- **IoT sensor support** via REST API — sensors can POST data directly
- **Automated water temperature logging** daily at 9:00 AM (estimated from air temperature)
- Real-time water quality alerts on dashboard

### 🚨 Alert System
- Automatic alert generation when water quality is out of safe range:
  - Dissolved Oxygen < 4.0 mg/L → Critical
  - Water Temperature > 34°C → Critical
  - pH out of range (6.5–9.0) → Warning
- Email alerts sent immediately when critical conditions detected
- Dashboard alert banners with resolve functionality

### 📊 Analytics & Reports
- **Fish Growth Chart** — dual Y-axis (weight + count) with Chart.js
- **Profit/Loss Report** — monthly revenue vs expenses breakdown
- **Mortality Rate Tracker** — deaths by cause with trend charts
- **Daily Feed & Temperature** table (last 14 days)
- Feed consumption, biomass, and weather trend charts

### 🔐 Security & Accounts
- Custom user model with role-based access (Owner, Manager, Worker, Viewer)
- Two-Factor Authentication (Email OTP)
- Google OAuth login (django-allauth)
- Brute-force protection with rate limiting and account lockout
- Active session tracking and remote session revocation

### 🌱 Onboarding Flow
- 4-step farm setup after registration:
  1. Farm basic info (name, size, ponds, water source)
  2. Location (GPS auto-detect or district/upazila)
  3. Fish species and experience
  4. Weather data fetched automatically from farm location
- Farm profile visible on user profile page

---

## 🛠️ Tech Stack

| Category | Technology |
|----------|-----------|
| Backend | Django 5.2 |
| Database | PostgreSQL |
| Cache / Broker | Redis |
| Task Queue | Celery + Celery Beat |
| REST API | Django REST Framework |
| Weather | OpenWeatherMap API |
| SMS | Twilio |
| Auth | django-allauth (Google OAuth + Email OTP) |
| Charts | Chart.js |
| Frontend | Vanilla HTML/CSS/JS (dark theme) |

---

## 📁 Project Structure

```
smart-fish-farm/
│
├── accounts/                   # User authentication & security
│   ├── models.py               # Custom User, OTPToken, UserSession, LoginAttempt
│   ├── views.py                # Login, Register, OTP verify, Profile, Sessions
│   ├── forms.py                # LoginForm, RegisterForm, OTPForm, ProfileForm
│   ├── security.py             # Rate limiting, brute-force, session tracking
│   ├── backends.py             # Email-based authentication backend
│   └── middleware.py           # Session activity middleware
│
├── farm/                       # Core farm management app
│   ├── models.py               # Pond, FishBatch, GrowthRecord, WeatherRecord,
│   │                           # DailyWeather, FeedingProfile, FeedLog,
│   │                           # FeedingReminder, HarvestRecord, Expense,
│   │                           # MortalityLog, FarmAlert, PondNote, FarmProfile
│   ├── views.py                # Dashboard, Batch, Pond, Feed, Weather, Reports
│   ├── api_views.py            # REST API endpoints (IoT sensor support)
│   ├── onboarding_views.py     # 4-step farm onboarding flow
│   ├── onboarding_forms.py     # Onboarding step forms
│   ├── tasks.py                # Celery tasks (feed alert, auto temperature)
│   ├── notifications.py        # Email & SMS notification helpers
│   ├── serializers.py          # DRF serializers for API
│   ├── bd_geo.py               # Bangladesh district/upazila data
│   │
│   └── services/               # Business logic layer
│       ├── feed_calculator.py  # Smart feed kg calculation (biomass + temp)
│       ├── weather_ingest.py   # OpenWeatherMap API integration
│       ├── growth_prediction.py# Fish growth prediction algorithm
│       └── analytics.py        # Analytics data processing
│
├── smart_fish_farm/            # Django project settings
│   ├── settings.py
│   ├── urls.py
│   ├── celery.py               # Celery app configuration
│   ├── asgi.py
│   └── wsgi.py
│
├── templates/                  # HTML templates
│   ├── base.html               # Base layout with dark theme
│   ├── accounts/               # Login, Register, Profile, OTP templates
│   └── farm/                   # Dashboard, Batch, Pond, Reports templates
│
├── static/                     # CSS, JS, images
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
- Docker (optional, for Redis)

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

**4. Copy environment file:**
```bash
cp .env.example .env
```

---

## ⚙️ Environment Variables

Edit `.env` with your credentials:

```env
# Django
SECRET_KEY=your-secret-key-here
DEBUG=True

# Database (PostgreSQL)
DB_NAME=smart_fish_farm
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_HOST=localhost
DB_PORT=5432

# Weather API (OpenWeatherMap)
WEATHER_API_KEY=your_openweathermap_api_key
WEATHER_LOCATION=Dhaka,BD

# Email (Gmail SMTP)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your_email@gmail.com
EMAIL_HOST_PASSWORD=your_gmail_app_password

# Farm Notification
FARM_NOTIFICATION_EMAIL=your_email@gmail.com

# Twilio SMS (optional)
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_token
TWILIO_FROM_NUMBER=+1234567890
FARM_PHONE_NUMBER=+8801XXXXXXXXX

# Google OAuth (optional)
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
```

---

## ▶️ Running the Project

Start all required services in **4 separate terminals**:

```bash
# Terminal 1 — Redis (via Docker)
docker run -p 6379:6379 redis

# Terminal 2 — Celery Worker
python -m celery -A smart_fish_farm worker -l info -P solo

# Terminal 3 — Celery Beat (Scheduled Tasks)
python -m celery -A smart_fish_farm beat -l info

# Terminal 4 — Django Development Server
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open in browser:
- **Dashboard:** http://127.0.0.1:8000/
- **Admin Panel:** http://127.0.0.1:8000/admin/

---

## 🔌 API Reference

Base URL: `http://127.0.0.1:8000/api/`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ponds/` | GET, POST | List / create ponds |
| `/api/batches/` | GET, POST | List / create fish batches |
| `/api/batches/<pk>/` | GET | Batch detail |
| `/api/batches/<pk>/prediction/` | GET | AI growth prediction |
| `/api/growth-records/` | GET, POST | Growth records |
| `/api/weather-records/` | GET, POST | Water quality records (IoT) |
| `/api/feed-logs/` | GET, POST | Feed logs |

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

Feed amount is calculated using:

```
Biomass (kg) = Surviving Fish Count × Avg Weight (g) ÷ 1000
Base Feed    = Biomass × Feed Rate % (from FeedingProfile)
Final Feed   = Base Feed × Temperature Factor
```

Temperature factors:
| Temperature | Factor |
|-------------|--------|
| < 18°C | 0.10 (minimal) |
| 18–21°C | 0.40 |
| 22–25°C | 0.70 |
| 26–30°C | 1.00 (optimal) |
| > 30°C | 0.90 |

### Water Quality Safe Ranges

| Parameter | Safe Range | Alert Level |
|-----------|-----------|-------------|
| Dissolved Oxygen | > 5.0 mg/L | < 4.0 = Critical |
| Water Temperature | 22–31°C | > 34°C = Critical |
| pH | 6.5–9.0 | Outside = Warning |

---

## ⏰ Automated Tasks

Powered by **Celery Beat** — runs automatically every day:

| Time | Task |
|------|------|
| 6:00 AM | 📧 Daily feed alert email with schedule |
| 9:00 AM | 🌡️ Auto water temperature logging for all ponds |

---

## 👥 User Roles

| Role | Access |
|------|--------|
| Owner | Full access |
| Manager | Farm management |
| Worker | Log feed, growth, mortality |
| Viewer | Read-only dashboard |

---

## 📄 License

This project is developed for academic research purposes at **Daffodil International University**.

---

<p align="center">
  Built with ❤️ by <a href="https://github.com/Sadman-Devx">Sadman Sakib</a>
</p>