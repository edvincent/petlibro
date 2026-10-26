"""Plain Granary 2 (PLAF105).

Same device family as the Granary Smart Feeder, plus the fields this model adds:
feeding mode (PLAN or FREE "Smart Feed"), bowl telemetry, Smart Feed settings, meal
call, per-pet meal records, and state fields (power, running, cleaning, desiccant).

The PETLIBRO feeding plan endpoints (``/device/feedingPlan/list`` and ``/today``) answer
with empty data for this model even in PLAN mode, so the schedule is inferred from the
scheduled feedings the feeder has actually performed (see ``inferred_schedule``).
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from logging import getLogger

from homeassistant.util import dt as dt_util

from .granary_smart_feeder import GranarySmartFeeder

_LOGGER = getLogger(__name__)


def _params(record: dict) -> dict:
    raw = record.get("params")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}


class Granary2Feeder(GranarySmartFeeder):
    """Plain Granary 2 (productName "Granary 2")."""

    async def refresh(self):
        await super().refresh()
        try:
            data_real = await self.api.device_data_real_info(self.serial)
        except Exception as err:  # keep the base data if the extra calls fail
            _LOGGER.warning("Granary 2 %s: /data/data/realInfo failed: %s", self.serial, err)
            data_real = {}
        try:
            now = dt_util.utcnow()
            meals = await self.api.session.post("/device/workRecord/list", json={
                "deviceSn": self.serial,
                "id": self.serial,
                "startTime": int((now - timedelta(days=30)).timestamp() * 1000),
                "endTime": int(now.timestamp() * 1000),
                "size": 25,
                "type": ["MEAL_RECORD"],
            })
        except Exception as err:
            _LOGGER.warning("Granary 2 %s: meal records failed: %s", self.serial, err)
            meals = []
        self.update_data({
            "dataRealInfo": data_real if isinstance(data_real, dict) else {},
            "mealRecords": meals if isinstance(meals, list) else [],
        })

    # ---- helpers -------------------------------------------------------------------
    def _tz(self):
        """Device time zone, falling back to the Home Assistant one before data arrives."""
        name = self._real.get("timezone") or self._data.get("timezone")
        if name:
            try:
                zone = dt_util.get_time_zone(name)
                if zone:
                    return zone
            except Exception:  # noqa: BLE001 - bad zone names fall back to the default
                pass
        return dt_util.DEFAULT_TIME_ZONE

    @property
    def _real(self) -> dict:
        merged = dict(self._data.get("realInfo", {}) or {})
        merged.update(self._data.get("dataRealInfo", {}) or {})
        return merged

    def _flat_records(self, key: str) -> list[dict]:
        out: list[dict] = []
        for day in self._data.get(key, []) or []:
            if isinstance(day, dict):
                out.extend(r for r in day.get("workRecords", []) if isinstance(r, dict))
        return out

    @staticmethod
    def _ts(record: dict) -> datetime | None:
        ms = record.get("recordTime")
        return dt_util.utc_from_timestamp(ms / 1000) if ms else None

    # ---- bowl and mode -------------------------------------------------------------
    @property
    def feeding_mode(self) -> str | None:
        return self._real.get("feedingMode")

    @property
    def food_in_bowl(self) -> float | None:
        return self._real.get("remainingGrain")

    @property
    def feedable_portions(self) -> int | None:
        return self._real.get("maxFeedable")

    @property
    def portion_weight(self) -> float | None:
        return self._real.get("portionToGramRatio")

    @property
    def auto_feed_max_weight(self) -> float | None:
        return self._real.get("autoFeedMaxWeight")

    # ---- Smart Feed (free feeding) settings ---------------------------------------
    @property
    def smart_feed_daily_max(self) -> int | None:
        return self._real.get("freeDailyMaxNum")

    @property
    def smart_feed_portions_per_feed(self) -> int | None:
        return self._real.get("freePerGrainNum")

    @property
    def smart_feed_leftover_weight(self) -> float | None:
        return self._real.get("freeLeftoverWeight")

    @property
    def smart_feed_wait_seconds(self) -> int | None:
        return self._real.get("freeWaitSeconds")

    # ---- meal call -----------------------------------------------------------------
    @property
    def meal_call_times(self) -> int | None:
        return self._real.get("mealCallTimes")

    @property
    def meal_call_enabled(self) -> bool | None:
        value = self._real.get("mealCallSwitch")
        return bool(value) if value is not None else None

    # ---- state fields --------------------------------------------------------------
    @property
    def power_state(self) -> str | None:
        return self._real.get("powerState")

    @property
    def running_state(self) -> str | None:
        return self._real.get("runningState")

    @property
    def cleaning_state(self) -> str | None:
        return self._real.get("cleanState")

    @property
    def desiccant_state(self) -> str | None:
        return self._real.get("desiccantState")

    @property
    def remaining_cleaning_days(self) -> int | None:
        return self._real.get("remainingCleaningDays")

    @property
    def device_stopped_working(self) -> bool | None:
        value = self._real.get("deviceStoppedWorking")
        return bool(value) if value is not None else None

    @property
    def barn_door_error(self) -> bool | None:
        value = self._real.get("barnDoorError")
        return bool(value) if value is not None else None

    # ---- last meal (pet eating record) ---------------------------------------------
    def _last_meal(self) -> dict | None:
        for record in self._flat_records("mealRecords"):
            if record.get("type") == "MEAL_RECORD":
                return record
        return None

    @property
    def last_meal_pet(self) -> str | None:
        record = self._last_meal()
        return (record.get("petName") or _params(record).get("petName")) if record else None

    @property
    def last_meal_intake(self) -> float | None:
        record = self._last_meal()
        return _params(record).get("intake") if record else None

    @property
    def last_meal_duration(self) -> str | None:
        record = self._last_meal()
        return _params(record).get("duration") if record else None

    @property
    def last_meal_time(self) -> datetime | None:
        record = self._last_meal()
        return self._ts(record) if record else None

    # ---- last feeding and how it was triggered --------------------------------------
    def _last_grain_output(self) -> dict | None:
        for record in self._flat_records("workRecord"):
            if record.get("type") == "GRAIN_OUTPUT_SUCCESS":
                return record
        return None

    @property
    def last_feed_mode(self) -> str | None:
        record = self._last_grain_output()
        mode = _params(record).get("mode") if record else None
        return str(mode).strip("{}").removesuffix("_MODE") if mode else None

    @property
    def last_feed_portions(self) -> int | None:
        record = self._last_grain_output()
        grain = _params(record).get("grain") if record else None
        try:
            return int(grain)
        except (TypeError, ValueError):
            return None

    # ---- inferred schedule ---------------------------------------------------------
    def _plan_feeds(self) -> list[tuple[datetime, int]]:
        tz = self._tz()
        feeds = []
        for record in self._flat_records("workRecord"):
            if record.get("type") != "GRAIN_OUTPUT_SUCCESS":
                continue
            params = _params(record)
            if "PLAN" not in str(params.get("mode", "")):
                continue
            when = self._ts(record)
            if when is None:
                continue
            try:
                portions = int(params.get("grain"))
            except (TypeError, ValueError):
                portions = 0
            feeds.append((when.astimezone(tz), portions))
        return feeds

    @property
    def inferred_schedule(self) -> list[dict]:
        """Times of day (device timezone) with a scheduled feeding on at least two different days."""
        days: dict[str, set] = defaultdict(set)
        portions: dict[str, Counter] = defaultdict(Counter)
        for when, grain in self._plan_feeds():
            key = when.strftime("%H:%M")
            days[key].add(when.date())
            portions[key][grain] += 1
        schedule = [
            {"time": key, "portions": portions[key].most_common(1)[0][0]}
            for key in sorted(days) if len(days[key]) >= 2
        ]
        return schedule

    @property
    def inferred_schedule_text(self) -> str | None:
        schedule = self.inferred_schedule
        return ", ".join(f'{s["time"]} ({s["portions"]})' for s in schedule) if schedule else None

    @property
    def next_feed_time(self) -> datetime | None:
        """The plan-based value when the API provides it, else the next inferred time."""
        planned = super().next_feed_time
        if planned:
            return planned
        schedule = self.inferred_schedule
        if not schedule:
            return None
        tz = self._tz()
        now = dt_util.now(tz)
        candidates = []
        for item in schedule:
            hour, minute = (int(x) for x in item["time"].split(":"))
            when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if when <= now:
                when += timedelta(days=1)
            candidates.append(when)
        return min(candidates).astimezone(dt_util.UTC)

    @property
    def remaining_feeds_today(self) -> int | None:
        schedule = self.inferred_schedule
        if not schedule:
            return None
        tz = self._tz()
        now = dt_util.now(tz).strftime("%H:%M")
        return sum(1 for s in schedule if s["time"] > now)
