import argparse
import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import aiohttp
from dotenv import load_dotenv


SUMMER_MODE = "Tryb letni"
PARALLEL_PUMPS_MODE = "Pompy rownolegle"
MENU_TYPES = ("MU", "MI")
CHOICE_TYPES = {11, 111, 112}


@dataclass(frozen=True)
class Settings:
    api_url: str
    emodul_url: str
    module_udid: Optional[str]
    email: str
    password: str
    threshold_c: float
    check_interval_seconds: int
    schedule_minutes: tuple[int, ...]
    hysteresis_c: float
    history_file: Path
    history_limit: int


class TechApiError(RuntimeError):
    pass


class TechApi:
    def __init__(self, session: aiohttp.ClientSession, base_url: str) -> None:
        self.session = session
        self.base_url = base_url.rstrip("/") + "/"
        self.headers = {"Accept": "application/json", "Accept-Encoding": "gzip"}
        self.user_id: Optional[str] = None
        self.token: Optional[str] = None
        self.translations: dict[str, str] = {}

    async def get(self, path: str) -> dict[str, Any]:
        async with self.session.get(self.base_url + path, headers=self.headers) as response:
            if response.status != 200:
                raise TechApiError(f"GET {path} zwrocil {response.status}: {await response.text()}")
            return await response.json()

    async def post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        async with self.session.post(
            self.base_url + path,
            data=json.dumps(data),
            headers=self.headers,
        ) as response:
            if response.status != 200:
                raise TechApiError(f"POST {path} zwrocil {response.status}: {await response.text()}")
            return await response.json()

    async def authenticate(self, username: str, password: str) -> None:
        result = await self.post("authentication", {"username": username, "password": password})
        if not result.get("authenticated"):
            raise TechApiError("Logowanie do eModul nie powiodlo sie")

        self.user_id = str(result["user_id"])
        self.token = result["token"]
        self.headers["Authorization"] = f"Bearer {self.token}"

    async def load_translations(self, language: str = "pl") -> None:
        result = await self.get(f"i18n/{language}")
        self.translations = result.get("data", {})

    async def list_modules(self) -> list[dict[str, Any]]:
        self._require_user_id()
        result = await self.get(f"users/{self.user_id}/modules")
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ("modules", "data"):
                value = result.get(key)
                if isinstance(value, list):
                    return value
        raise TechApiError(f"Nie rozpoznano odpowiedzi listy sterownikow: {result}")

    async def module_data(self, module_udid: str) -> dict[str, Any]:
        self._require_user_id()
        return await self.get(f"users/{self.user_id}/modules/{module_udid}")

    async def menu_items(self, module_udid: str) -> list[dict[str, Any]]:
        self._require_user_id()
        items: list[dict[str, Any]] = []
        for menu_type in MENU_TYPES:
            try:
                result = await self.get(f"users/{self.user_id}/modules/{module_udid}/menu/{menu_type}/")
            except TechApiError:
                continue

            for item in result.get("data", {}).get("elements", []):
                item["menuType"] = item.get("menuType", menu_type)
                items.append(item)
        return items

    async def set_menu_value(
        self,
        module_udid: str,
        menu_type: str,
        item_id: int,
        value: int,
    ) -> None:
        self._require_user_id()
        await self.post(
            f"users/{self.user_id}/modules/{module_udid}/menu/{menu_type}/ido/{item_id}",
            {"value": value},
        )

    def text(self, txt_id: Any) -> str:
        if txt_id in (None, 0, "0"):
            return ""
        return self.translations.get(str(txt_id), f"txtId {txt_id}")

    def _require_user_id(self) -> None:
        if not self.user_id:
            raise TechApiError("Klient API nie jest zalogowany")


def load_settings() -> Settings:
    load_dotenv()

    return Settings(
        api_url=os.getenv("EMODUL_API_URL", "https://emodul.eu/api/v1/"),
        emodul_url=os.getenv("EMODUL_URL", ""),
        module_udid=empty_to_none(os.getenv("EMODUL_MODULE_UDID")) or parse_udid_from_url(os.getenv("EMODUL_URL", "")),
        email=require_env("EMODUL_EMAIL"),
        password=require_env("EMODUL_PASSWORD"),
        threshold_c=float(os.getenv("TEMP_THRESHOLD_C", "16")),
        check_interval_seconds=int(os.getenv("CHECK_INTERVAL_SECONDS", "1800")),
        schedule_minutes=parse_schedule_minutes(os.getenv("SCHEDULE_MINUTES", "0,30")),
        hysteresis_c=float(os.getenv("HYSTERESIS_C", "0")),
        history_file=Path(os.getenv("HISTORY_FILE", "logs/history.json")),
        history_limit=int(os.getenv("HISTORY_LIMIT", "20")),
    )


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Brak wymaganej zmiennej srodowiskowej: {name}")
    return value


def empty_to_none(value: Optional[str]) -> Optional[str]:
    value = (value or "").strip()
    return value or None


def parse_udid_from_url(url: str) -> Optional[str]:
    match = re.search(r"/web/([^/]+)/", url)
    return match.group(1) if match else None


def parse_schedule_minutes(value: str) -> tuple[int, ...]:
    minutes: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        minute = int(part)
        if minute < 0 or minute > 59:
            raise ValueError("SCHEDULE_MINUTES moze zawierac tylko minuty 0-59")
        minutes.add(minute)
    return tuple(sorted(minutes))


def seconds_until_next_run(settings: Settings) -> float:
    if not settings.schedule_minutes:
        return float(settings.check_interval_seconds)

    now = datetime.now()
    candidates = []
    for minute in settings.schedule_minutes:
        candidate = now.replace(minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(hours=1)
        candidates.append(candidate)

    next_run = min(candidates)
    return max(1.0, (next_run - now).total_seconds())


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover", action="store_true", help="Pokaz kafelki i menu bez zmiany ustawien")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        api = TechApi(session, settings.api_url)
        await api.authenticate(settings.email, settings.password)
        await api.load_translations("pl")
        module_udid = await resolve_module_udid(api, settings)

        if args.discover:
            await print_discovery(api, module_udid)
            return

        while True:
            try:
                await run_check(api, module_udid, settings)
            except Exception as error:
                logging.exception("Blad podczas kontroli trybu pracy")
                append_history(
                    settings,
                    {
                        "status": "error",
                        "error": str(error),
                    },
                )

            sleep_seconds = seconds_until_next_run(settings)
            logging.info("Nastepne sprawdzenie za %.0f sekund", sleep_seconds)
            await asyncio.sleep(sleep_seconds)


async def resolve_module_udid(api: TechApi, settings: Settings) -> str:
    if settings.module_udid:
        return settings.module_udid

    modules = await api.list_modules()
    if not modules:
        raise TechApiError("Konto eModul nie ma zadnych sterownikow")

    udid = find_nested_key(modules[0], ("udid", "id", "moduleId"))
    if not udid:
        raise TechApiError(f"Nie znaleziono UDID sterownika w odpowiedzi API: {modules[0]}")
    return str(udid)


async def run_check(api: TechApi, module_udid: str, settings: Settings) -> None:
    module = await api.module_data(module_udid)
    menus = await api.menu_items(module_udid)

    outside_temp = find_outside_temperature(api, module)
    current_mode = find_current_mode(api, module)
    wanted_mode = decide_mode(outside_temp, current_mode, settings)

    logging.info(
        "Temperatura zewnetrzna: %.1f C, obecny tryb: %s, docelowy tryb: %s",
        outside_temp,
        current_mode or "nieznany",
        wanted_mode,
    )

    if current_mode == wanted_mode:
        logging.info("Tryb jest poprawny, nie zmieniam ustawien")
        append_history(
            settings,
            {
                "status": "no_change",
                "outside_temp_c": outside_temp,
                "current_mode": current_mode,
                "wanted_mode": wanted_mode,
            },
        )
        return

    menu_item, value = find_work_mode_menu_value(api, menus, wanted_mode)
    await api.set_menu_value(module_udid, menu_item["menuType"], int(menu_item["id"]), value)
    logging.info("Zmieniono tryb pracy na: %s", wanted_mode)
    append_history(
        settings,
        {
            "status": "changed",
            "outside_temp_c": outside_temp,
            "previous_mode": current_mode,
            "new_mode": wanted_mode,
            "menu_type": menu_item["menuType"],
            "menu_id": int(menu_item["id"]),
            "menu_value": value,
        },
    )


def find_outside_temperature(api: TechApi, module: dict[str, Any]) -> float:
    for tile in module.get("tiles", []):
        label = tile_label(api, tile).lower()
        if "temperatura zewn" not in normalize_polish(label):
            continue

        params = tile.get("params", {})
        value = first_number_from_candidates(params, ("value", "currentTemp", "temperature"))
        if value is not None:
            return normalize_temperature_value(value, params)

        numbers = re.findall(r"-?\d+(?:[,.]\d+)?", json.dumps(tile, ensure_ascii=False))
        if numbers:
            return normalize_temperature_value(float(numbers[-1].replace(",", ".")), params)

    raise TechApiError("Nie znaleziono kafelka 'Temperatura zewnetrzna'")


def find_current_mode(api: TechApi, module: dict[str, Any]) -> Optional[str]:
    for tile in module.get("tiles", []):
        label = tile_label(api, tile)
        if "tryb pracy" not in normalize_polish(label.lower()):
            continue
        params = tile.get("params", {})
        status = api.text(params.get("statusId")) or str(params.get("value", ""))
        for mode in (SUMMER_MODE, PARALLEL_PUMPS_MODE, "Ogrzewanie domu", "Priorytet bojlera"):
            if normalize_polish(mode.lower()) in normalize_polish(status.lower()):
                return mode
        return status or None
    return None


def decide_mode(outside_temp: float, current_mode: Optional[str], settings: Settings) -> str:
    if settings.hysteresis_c <= 0 or current_mode is None:
        return SUMMER_MODE if outside_temp >= settings.threshold_c else PARALLEL_PUMPS_MODE

    if outside_temp >= settings.threshold_c + settings.hysteresis_c:
        return SUMMER_MODE
    if outside_temp < settings.threshold_c - settings.hysteresis_c:
        return PARALLEL_PUMPS_MODE
    return current_mode


def find_work_mode_menu_value(
    api: TechApi,
    menus: list[dict[str, Any]],
    wanted_mode: str,
) -> tuple[dict[str, Any], int]:
    wanted_norm = normalize_polish(wanted_mode.lower())

    for item in menus:
        if item.get("type") not in CHOICE_TYPES or not item.get("access", False):
            continue

        options = item.get("params", {}).get("options", [])
        option_labels = {int(option["value"]): api.text(option.get("txtId")) for option in options if "value" in option}
        labels_norm = [normalize_polish(label.lower()) for label in option_labels.values()]
        menu_name = normalize_polish(api.text(item.get("txtId")).lower())

        is_work_mode_menu = "tryb pracy" in menu_name or "tryby pracy" in menu_name
        has_wanted_option = any(wanted_norm in label for label in labels_norm)
        has_parallel_option = any(normalize_polish(PARALLEL_PUMPS_MODE.lower()) in label for label in labels_norm)
        has_summer_option = any(normalize_polish(SUMMER_MODE.lower()) in label for label in labels_norm)

        if not has_wanted_option or not (is_work_mode_menu or (has_parallel_option and has_summer_option)):
            continue

        for value, label in option_labels.items():
            if wanted_norm in normalize_polish(label.lower()):
                return item, value

    raise TechApiError(f"Nie znaleziono w menu opcji trybu pracy: {wanted_mode}")


async def print_discovery(api: TechApi, module_udid: str) -> None:
    modules = await api.list_modules()
    module = await api.module_data(module_udid)
    menus = await api.menu_items(module_udid)

    print("Sterowniki:")
    for module_info in modules:
        print(f"- {module_info}")

    print("\nKafelki:")
    for tile in module.get("tiles", []):
        print(f"- id={tile.get('id')} label={tile_label(api, tile)!r} params={tile.get('params', {})}")

    print("\nMenu wyboru:")
    for item in menus:
        if item.get("type") not in CHOICE_TYPES:
            continue
        options = [
            f"{option.get('value')}={api.text(option.get('txtId'))}"
            for option in item.get("params", {}).get("options", [])
        ]
        print(
            f"- {item.get('menuType')} id={item.get('id')} access={item.get('access')} "
            f"name={api.text(item.get('txtId'))!r} current={item.get('params', {}).get('value')} "
            f"options={options}"
        )


def tile_label(api: TechApi, tile: dict[str, Any]) -> str:
    params = tile.get("params", {})
    pieces = [
        params.get("description", ""),
        api.text(params.get("headerId")),
        api.text(params.get("statusId")),
        api.text(params.get("txtId")),
    ]
    return " ".join(piece for piece in pieces if piece)


def first_number_from_candidates(data: dict[str, Any], keys: tuple[str, ...]) -> Optional[float]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            match = re.search(r"-?\d+(?:[,.]\d+)?", value)
            if match:
                return float(match.group(0).replace(",", "."))
    return None


def normalize_temperature_value(value: float, params: dict[str, Any]) -> float:
    if params.get("description") == "Temperature sensor":
        return value / 10
    return value


def append_history(settings: Settings, event: dict[str, Any]) -> None:
    history_path = settings.history_file
    history_path.parent.mkdir(parents=True, exist_ok=True)

    history: list[dict[str, Any]] = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logging.warning("Nie udalo sie odczytac historii: %s", history_path)

    history.append(
        {
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            **event,
        }
    )
    history = history[-settings.history_limit :]
    history_path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def normalize_polish(value: str) -> str:
    translation = str.maketrans(
        "\u0105\u0107\u0119\u0142\u0144\u00f3\u015b\u017a\u017c",
        "acelnoszz",
    )
    return value.translate(translation)


def find_nested_key(data: Any, keys: tuple[str, ...]) -> Optional[Any]:
    if isinstance(data, dict):
        for key in keys:
            if key in data:
                return data[key]
        for value in data.values():
            found = find_nested_key(value, keys)
            if found is not None:
                return found
    if isinstance(data, list):
        for value in data:
            found = find_nested_key(value, keys)
            if found is not None:
                return found
    return None


if __name__ == "__main__":
    asyncio.run(main())
