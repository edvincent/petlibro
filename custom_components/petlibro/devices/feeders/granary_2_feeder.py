import json
from logging import getLogger

from .granary_smart_feeder import GranarySmartFeeder

_LOGGER = getLogger(__name__)


class Granary2Feeder(GranarySmartFeeder):
    """Plain Granary 2 (PLAF105).

    Same as the Granary Smart Feeder, but always asks for the feeding plan list:
    the base class only asks when the top-level device record carries
    ``enableFeedingPlan``, which this model's record may not. The first few
    refreshes also log the raw plan responses so the format can be checked.
    """

    _diag_left = 3

    async def refresh(self):
        await super().refresh()
        try:
            plans = await self.api.device_feeding_plan_list(self.serial)
            today = await self.api.device_feeding_plan_today_new(self.serial)
            if plans:
                self.update_data({"feedingPlan": plans})
            if today:
                self.update_data({"getfeedingplantoday": today})
            if Granary2Feeder._diag_left > 0:
                Granary2Feeder._diag_left -= 1
                real = self._data.get("realInfo", {}) or {}
                _LOGGER.warning("PETLIBRO-G2-DIAG %s plan list: %s", self.serial, json.dumps(plans, default=str)[:3500])
                _LOGGER.warning("PETLIBRO-G2-DIAG %s today: %s", self.serial, json.dumps(today, default=str)[:3500])
                _LOGGER.warning(
                    "PETLIBRO-G2-DIAG %s plan-related fields: %s | top-level enableFeedingPlan=%r",
                    self.serial,
                    {k: v for k, v in real.items() if "plan" in k.lower() or "feed" in k.lower() or "mode" in k.lower()},
                    self._data.get("enableFeedingPlan"),
                )
        except Exception as err:  # keep the device usable even if the plan calls fail
            _LOGGER.warning("PETLIBRO-G2-DIAG plan fetch failed for %s: %s", self.serial, err)
