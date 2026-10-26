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

    _dumped = False

    async def refresh(self):
        await super().refresh()
        if Granary2Feeder._dumped:
            return
        Granary2Feeder._dumped = True
        for path in _DUMP_PATHS:
            try:
                data = await self.api.session.post_serial(path, self.serial)
                text = json.dumps(_redact(data), default=str)
            except Exception as err:  # unknown endpoints are expected to fail
                text = f"ERROR {type(err).__name__}: {err}"
            for i in range(0, min(len(text), 12000), 3000):
                _LOGGER.warning("PETLIBRO-G2-DUMP %s %s [%d] %s", self.serial[-4:], path, i // 3000, text[i:i + 3000])
