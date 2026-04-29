# TechSterownik auto lato

Program cyklicznie loguje sie do API eModul i kontroluje tryb pracy pieca:

- temperatura zewnetrzna `>= 16 C` -> `Tryb letni`
- temperatura zewnetrzna `< 16 C` -> `Pompy rownolegle`

## Uruchomienie lokalnie

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

W pliku `.env` ustaw:

```env
EMODUL_URL=https://emodul.pl/web/TWOJ_ID_STEROWNIKA/home
EMODUL_MODULE_UDID=
EMODUL_EMAIL=twoj-email@example.com
EMODUL_PASSWORD=twoje-haslo
EMODUL_API_URL=https://emodul.eu/api/v1/
TEMP_THRESHOLD_C=16
CHECK_INTERVAL_SECONDS=1800
SCHEDULE_MINUTES=0,30
HISTORY_FILE=logs/history.json
HISTORY_LIMIT=20
HYSTERESIS_C=0
```

Start:

```powershell
python main.py
```

Tryb diagnostyczny, bez zmiany ustawien:

```powershell
python main.py --discover
```

Historia ostatnich decyzji i zmian jest zapisywana w `logs/history.json`.
Domyslnie program trzyma ostatnie 20 wpisow.

`SCHEDULE_MINUTES=0,30` oznacza sprawdzanie o pelnej godzinie i w polowie godziny,
np. `08:00`, `08:30`, `09:00`, `09:30`. Gdy `SCHEDULE_MINUTES` jest puste,
program uzywa zwyklego interwalu `CHECK_INTERVAL_SECONDS`.

## Uruchomienie na serwerze Linux jako usluga

```bash
sudo apt update
sudo apt install -y python3 python3-venv
cd /opt/TechSterownik_auto_lato
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cp .env.example .env
nano .env
```

Przykladowy plik `/etc/systemd/system/techsterownik-auto-lato.service`:

```ini
[Unit]
Description=Automatyczna zmiana trybu pracy pieca eModul
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/TechSterownik_auto_lato
EnvironmentFile=/opt/TechSterownik_auto_lato/.env
ExecStart=/opt/TechSterownik_auto_lato/.venv/bin/python /opt/TechSterownik_auto_lato/main.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Wlaczenie uslugi:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now techsterownik-auto-lato
sudo systemctl status techsterownik-auto-lato
```

Przydatne skrypty:

```bash
chmod +x scripts/*.sh
./scripts/start.sh
./scripts/stop.sh
./scripts/restart.sh
./scripts/status.sh
./scripts/logs.sh
./scripts/history.sh
./scripts/discover.sh
```

`logs.sh` pokazuje log systemd na zywo, a `history.sh` pokazuje ostatnie wpisy z `logs/history.json`.

## Uwagi

Pierwsze uruchomienie najlepiej zrobic przez `python main.py --discover`. Program wypisze kafelki i menu wyboru z API, bez zmieniania ustawien. Dzieki temu mozna potwierdzic, ze API widzi kafelek `Temperatura zewnetrzna` oraz menu z opcjami `Tryb letni` i `Pompy rownolegle`.
