# TechSterownik auto lato

Program cyklicznie loguje sie do API eModul i kontroluje tryb pracy pieca:

- temperatura zewnetrzna `>= 16 C` -> `Tryb letni`
- temperatura zewnetrzna `< 16 C` -> `Pompy równoległe`

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
CHECK_INTERVAL_SECONDS=300
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

Logi:

```bash
journalctl -u techsterownik-auto-lato -f
```

## Uwagi

Pierwsze uruchomienie najlepiej zrobic przez `python main.py --discover`. Program wypisze kafelki i menu wyboru z API, bez zmieniania ustawien. Dzieki temu mozna potwierdzic, ze API widzi kafelek `Temperatura zewnetrzna` oraz menu z opcjami `Tryb letni` i `Pompy równoległe`.
