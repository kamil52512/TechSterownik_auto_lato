import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError, async_playwright


SUMMER_MODE = "Tryb letni"
PARALLEL_PUMPS_MODE = "Pompy równoległe"


@dataclass(frozen=True)
class Settings:
    url: str
    email: str
    password: str
    threshold_c: float
    check_interval_seconds: int
    headless: bool
    hysteresis_c: float


def load_settings() -> Settings:
    load_dotenv()

    url = require_env("EMODUL_URL")
    email = require_env("EMODUL_EMAIL")
    password = require_env("EMODUL_PASSWORD")

    return Settings(
        url=url,
        email=email,
        password=password,
        threshold_c=float(os.getenv("TEMP_THRESHOLD_C", "16")),
        check_interval_seconds=int(os.getenv("CHECK_INTERVAL_SECONDS", "300")),
        headless=os.getenv("HEADLESS", "true").lower() in {"1", "true", "yes", "tak"},
        hysteresis_c=float(os.getenv("HYSTERESIS_C", "0")),
    )


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Brak wymaganej zmiennej srodowiskowej: {name}")
    return value


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    settings = load_settings()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=settings.headless)
        context = await browser.new_context(locale="pl-PL")
        page = await context.new_page()

        while True:
            try:
                await run_check(page, settings)
            except Exception:
                logging.exception("Blad podczas kontroli trybu pracy")

            await asyncio.sleep(settings.check_interval_seconds)


async def run_check(page: Page, settings: Settings) -> None:
    await ensure_home_page(page, settings)

    outside_temp = await read_outside_temperature(page)
    current_mode = await read_current_mode(page)
    wanted_mode = decide_mode(outside_temp, current_mode, settings)

    logging.info(
        "Temperatura zewnetrzna: %.1f C, obecny tryb: %s, docelowy tryb: %s",
        outside_temp,
        current_mode or "nieznany",
        wanted_mode,
    )

    if current_mode == wanted_mode:
        logging.info("Tryb jest poprawny, nie zmieniam ustawien")
        return

    await change_work_mode(page, wanted_mode)
    logging.info("Zmieniono tryb pracy na: %s", wanted_mode)


async def ensure_home_page(page: Page, settings: Settings) -> None:
    if not page.url.startswith("http"):
        await page.goto(settings.url, wait_until="domcontentloaded")
    elif settings.url not in page.url:
        await page.goto(settings.url, wait_until="domcontentloaded")

    await maybe_login(page, settings)
    await page.locator("body").wait_for(timeout=15000)

    if "login" in page.url.lower():
        raise RuntimeError("Logowanie do eModul nie powiodlo sie")


async def maybe_login(page: Page, settings: Settings) -> None:
    email_field = page.locator(
        "input[type='email'], input[name*='email' i], input[name*='login' i], input[type='text']"
    ).first

    try:
        await email_field.wait_for(timeout=5000)
    except PlaywrightTimeoutError:
        return

    password_field = page.locator("input[type='password']").first
    await email_field.fill(settings.email)
    await password_field.fill(settings.password)

    submit = page.locator(
        "button[type='submit'], input[type='submit'], button:has-text('Zaloguj'), button:has-text('Log in')"
    ).first
    await submit.click()
    await page.wait_for_timeout(2000)
    await page.goto(settings.url, wait_until="domcontentloaded")


async def read_outside_temperature(page: Page) -> float:
    value = await find_value_near_label(page, "Temperatura zewnętrzna")
    if value is None:
        value = await find_value_near_label(page, "Temperatura zewnetrzna")
    if value is None:
        raise RuntimeError("Nie znaleziono temperatury zewnetrznej na stronie")
    return value


async def read_current_mode(page: Page) -> Optional[str]:
    text = await find_text_near_label(page, "Tryb pracy")
    if not text:
        return None

    for mode in (SUMMER_MODE, PARALLEL_PUMPS_MODE, "Ogrzewanie domu", "Priorytet bojlera"):
        if mode.lower() in text.lower():
            return mode
    return text.strip()


def decide_mode(outside_temp: float, current_mode: Optional[str], settings: Settings) -> str:
    if settings.hysteresis_c <= 0 or current_mode is None:
        return SUMMER_MODE if outside_temp >= settings.threshold_c else PARALLEL_PUMPS_MODE

    summer_on = settings.threshold_c + settings.hysteresis_c
    winter_on = settings.threshold_c - settings.hysteresis_c

    if outside_temp >= summer_on:
        return SUMMER_MODE
    if outside_temp < winter_on:
        return PARALLEL_PUMPS_MODE
    return current_mode


async def change_work_mode(page: Page, wanted_mode: str) -> None:
    await page.get_by_text("Tryb pracy", exact=True).click(timeout=15000)
    await page.get_by_text(wanted_mode, exact=True).click(timeout=15000)

    confirm_button = page.locator(
        "button:has-text('OK'), button:has-text('Zapisz'), button:has-text('Potwierdź'), "
        ".green, .btn-success, [class*='confirm'], [class*='save']"
    ).last
    await confirm_button.click(timeout=15000)
    await page.wait_for_timeout(2000)


async def find_value_near_label(page: Page, label: str) -> Optional[float]:
    text = await find_text_near_label(page, label)
    if not text:
        return None

    numbers = re.findall(r"-?\d+(?:[,.]\d+)?", text)
    if not numbers:
        return None
    return float(numbers[-1].replace(",", "."))


async def find_text_near_label(page: Page, label: str) -> Optional[str]:
    return await page.evaluate(
        """
        (label) => {
            const normalize = (value) => value.replace(/\\s+/g, ' ').trim();
            const elements = [...document.querySelectorAll('body *')];
            const labelElement = elements.find((element) =>
                normalize(element.innerText || '').toLowerCase().includes(label.toLowerCase())
            );

            if (!labelElement) {
                return null;
            }

            let node = labelElement;
            for (let depth = 0; depth < 5 && node; depth += 1) {
                const text = normalize(node.innerText || '');
                const lowerText = text.toLowerCase();
                const lowerLabel = label.toLowerCase();
                if (
                    text &&
                    text.length < 250 &&
                    lowerText.includes(lowerLabel) &&
                    lowerText !== lowerLabel
                ) {
                    return text;
                }
                node = node.parentElement;
            }

            return normalize(labelElement.innerText || '');
        }
        """,
        label,
    )


if __name__ == "__main__":
    asyncio.run(main())
