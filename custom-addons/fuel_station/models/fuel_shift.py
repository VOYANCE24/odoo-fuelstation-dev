from odoo import fields, models, api
from datetime import datetime, time, timedelta
import pytz

class FuelShift(models.Model):
    _name = "fuel.shift"
    _description = "Fuel Station Shift"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Selection([("day", "Day"), ("night", "Night")], required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    # shift window definition (recommended)
    start_time = fields.Float(help="e.g. 7.0 for 07:00")
    end_time = fields.Float(help="e.g. 19.0 for 19:00; can be < start for overnight")

    def _float_to_time(self, f):
        hours = int(f or 0.0)
        minutes = int(round(((f or 0.0) - hours) * 60))
        if minutes == 60:
            hours += 1
            minutes = 0
        return time(hour=hours % 24, minute=minutes)

    def get_window(self, date):
        """Return UTC datetimes (start_utc, end_utc) for this shift on given date (fields.Date)."""
        self.ensure_one()
        user_tz = pytz.timezone(self.env.user.tz or "UTC")

        start_t = self._float_to_time(self.start_time or 0.0)
        end_t = self._float_to_time(self.end_time or 0.0)

        start_local = user_tz.localize(datetime.combine(date, start_t))
        end_local = user_tz.localize(datetime.combine(date, end_t))

        # overnight shift handling (end < start)
        if end_local <= start_local:
            end_local = end_local + timedelta(days=1)

        return (start_local.astimezone(pytz.UTC), end_local.astimezone(pytz.UTC))