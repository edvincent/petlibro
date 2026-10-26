import json
import re
from logging import getLogger

from .granary_smart_feeder import GranarySmartFeeder

_LOGGER = getLogger(__name__)

_REDACT = re.compile(r"ssid|mac|ip$|ipaddr|token|auth|wifi|email|password|secret|lat|lng|address|phone|bssid", re.I)

# Read-only endpoints dumped once so every field the Granary 2 returns can be mapped.
_DUMP_PATHS = [
    "/device/device/baseInfo",
    "/device/device/realInfo",
    "/data/data/realInfo",
    "/device/setting/getAttributeSetting",
    "/device/data/grainStatus",
    "/device/feedingPlan/list",
    "/device/feedingPlan/todayNew",
    "/device/feedingPlan/listV2",
    "/device/feedingPlan/todayList",
    "/device/device/getFreeFeedingSetting",
    "/device/workRecord/list",
    "/device/ota/getUpgrade",
    "/device/device/getDefaultMatrix",
    "/device/setting/getSleepModeSetting",
    "/device/device/getFeedingMode",
]


def _redact(value):
    if isinstance(value, dict):
        return {k: ("<redacted>" if _REDACT.search(str(k)) else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


class Granary2Feeder(GranarySmartFeeder):
    """Plain Granary 2 (PLAF105).

    Same as the Granary Smart Feeder. The first refresh also dumps (redacted) the raw
    responses of the read-only endpoints so every field can be mapped.
    """

    async def refresh(self):
        await super().refresh()
        if getattr(self, "_dumped", False):
            return
        self._dumped = True
        extra = []
        try:
            import aiohttp
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                async with s.get("https://raw.githubusercontent.com/edvincent/petlibro/granary2-support/diag_paths.json") as r:
                    extra = (await r.json(content_type=None)).get("paths", []) if r.status == 200 else []
        except Exception as err:
            _LOGGER.warning("PETLIBRO-G2-DUMP could not fetch candidate endpoints: %s", err)
        for item in extra:
            path, body = item["path"], dict(item.get("body") or {})
            try:
                body["id"] = self.serial
                body["deviceSn"] = self.serial
                data = await self.api.session.post(path, json=body)
                text = json.dumps(_redact(data), default=str)
            except Exception as err:
                text = f"ERROR {type(err).__name__}: {str(err)[:80]}"
            if text.startswith("ERROR") and ("404" in text or "not supported" in text):
                continue
            _LOGGER.warning("PETLIBRO-G2-PROBE %s %s %s -> %s", self.serial[-4:], path, json.dumps(item.get("body") or {}), text[:1500])
        return
        for path in _DUMP_PATHS:
            try:
                data = await self.api.session.post_serial(path, self.serial)
                text = json.dumps(_redact(data), default=str)
            except Exception as err:  # unknown endpoints are expected to fail
                text = f"ERROR {type(err).__name__}: {err}"
            for i in range(0, min(len(text), 12000), 3000):
                _LOGGER.warning("PETLIBRO-G2-DUMP %s %s [%d] %s", self.serial[-4:], path, i // 3000, text[i:i + 3000])
