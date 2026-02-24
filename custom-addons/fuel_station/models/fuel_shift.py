from odoo import fields, models, api
from datetime import datetime, time, timedelta
import logging
import pytz

_logger = logging.getLogger(__name__)

# Default timezone used when a user has not configured their own.
# Change this to match your station's physical location so that shift
# window calculations are correct even for users without a tz set.
_DEFAULT_TZ = "Africa/Kampala"


class FuelShift(models.Model):
    _name = "fuel.shift"
    _description = "Fuel Station Shift"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Selection(
        [("day", "Day"), ("night", "Night")], required=True
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    # Shift window stored as decimal hours (e.g. 7.5 = 07:30).
    start_time = fields.Float(help="e.g. 7.0 for 07:00")
    end_time = fields.Float(
        help="e.g. 19.0 for 19:00.  Values < start_time indicate an overnight shift."
    )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _float_to_time(f: float) -> time:
        """Convert a decimal-hour float to a Python time object."""
        hours = int(f or 0.0)
        minutes = int(round(((f or 0.0) - hours) * 60))
        if minutes == 60:
            hours += 1
            minutes = 0
        return time(hour=hours % 24, minute=minutes)

    def _get_user_tz(self) -> pytz.BaseTzInfo:
        """
        Return the user's configured timezone.

        Fix applied vs original:
            The original code silently fell back to UTC when env.user.tz was
            not set.  UTC is almost never correct for a physical fuel station and
            would place shift boundaries at wrong local times.

            We now fall back to _DEFAULT_TZ and log a warning so operators know
            the timezone has not been configured for a user.
        """
        tz_name = self.env.user.tz
        if not tz_name:
            _logger.warning(
                "User %s (%s) has no timezone configured. "
                "Falling back to %s for shift window calculation. "
                "Please set the user's timezone in Settings → Users.",
                self.env.user.name,
                self.env.user.id,
                _DEFAULT_TZ,
            )
            tz_name = _DEFAULT_TZ
        return pytz.timezone(tz_name)

    def get_window(self, date):
        """
        Return a (start_utc, end_utc) tuple of UTC-aware datetimes representing
        the boundaries of this shift on the given date (fields.Date value).

        Overnight shifts (end_time < start_time) are handled by advancing
        end_local by one day.
        """
        self.ensure_one()
        user_tz = self._get_user_tz()

        start_t = self._float_to_time(self.start_time or 0.0)
        end_t = self._float_to_time(self.end_time or 0.0)

        start_local = user_tz.localize(datetime.combine(date, start_t))
        end_local = user_tz.localize(datetime.combine(date, end_t))

        # Overnight shift: end of shift falls on the following calendar day.
        if end_local <= start_local:
            end_local = end_local + timedelta(days=1)

        return (
            start_local.astimezone(pytz.UTC),
            end_local.astimezone(pytz.UTC),
        )