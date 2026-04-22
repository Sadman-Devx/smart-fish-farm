## Smart Fish Farm Management System (Advanced)

This is a Django-based Smart Fish Farm Management System that helps you:

- Track ponds and fish batches
- Log fish growth over time
- Log water/weather conditions per pond
- Automatically calculate daily feed based on biomass and temperature bands
- Generate feeding logs and basic reminders
- View an analytics-style dashboard with recent activity

### 1. Setup

```bash
cd "F:\sakib\smart-fish-farm"
py -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Copy environment template and edit values:

```bash
copy .env.example .env
```

### 2. PostgreSQL setup (recommended)

Create DB user and database in `psql`:

```sql
CREATE USER myuser WITH PASSWORD 'your_postgres_password';
CREATE DATABASE smart_fish_farm OWNER myuser;
GRANT ALL PRIVILEGES ON DATABASE smart_fish_farm TO myuser;
```

Then set these in `.env`:

```bash
DB_NAME=smart_fish_farm
DB_USER=myuser
DB_PASSWORD=your_postgres_password
DB_HOST=localhost
DB_PORT=5432
```

### 3. Database & Admin

```bash
python manage.py migrate
python manage.py createsuperuser
```

Run the development server:

```bash
# Terminal 1 - Redis
docker run -p 6379:6379 redis

# Terminal 2 - Celery
python -m celery -A smart_fish_farm worker -l info -P solo

# Terminal 3 - Django
python manage.py runserver
```

Open `http://127.0.0.1:8000/` for the dashboard and `http://127.0.0.1:8000/admin/` for the admin.

### 4. Core Concepts

- **Ponds**: basic pond metadata (area, depth).
- **Fish Batches**: species, stocking date, counts, starting weights.
- **Growth Records**: periodic samples of average weight and survival.
- **Weather Records**: per-pond measurements (temperature, DO, pH, rainfall).
- **Feeding Profiles**: map a temperature range to a feeding rate (% of biomass).
- **Feed Logs**: daily feed amounts (auto or manual).
- **Feeding Reminders**: scheduled notifications for future feeding times.

To enable automatic feed calculation, create `FeedingProfile` entries in the Django admin that define temperature bands and feeding % of biomass. When you open a batch page, the system uses:

1. Latest growth record to estimate biomass.
2. Latest pond water temperature.
3. Matching feeding profile for that temperature.

This produces a suggested feed amount in kg, which is pre-filled in the feeding form.

### 5. Extending

- Hook reminders into email/SMS by adding a periodic job that scans `FeedingReminder` objects and sends notifications.
- Add charts (e.g. with Chart.js) to plot growth and FCR over time.
- Integrate with an external weather or sensor API to auto-create `WeatherRecord` entries.

