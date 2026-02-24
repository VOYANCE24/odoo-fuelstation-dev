from odoo import fields, models, api
from odoo.exceptions import ValidationError


class FuelAttendantSessionLine(models.Model):
    _name = "fuel.attendant.session.line"
    _description = "Attendant Session Sales Line"
    _order = "id"

    session_id = fields.Many2one(
        "fuel.attendant.session", required=True, ondelete="cascade"
    )

    # Stored related fields so we can ORDER BY them in search() calls.
    date = fields.Date(related="session_id.date", store=True, readonly=True)
    shift_id = fields.Many2one(related="session_id.shift_id", store=True, readonly=True)

    pump_id = fields.Many2one("fuel.pump", required=True)
    product_id = fields.Many2one(related="pump_id.product_id", store=True, readonly=True)

    previous_meter = fields.Float(readonly=True)
    current_meter = fields.Float(required=True)

    litres_sold = fields.Float(compute="_compute_litres", store=True)
    price = fields.Float(required=True)
    total = fields.Float(compute="_compute_total", store=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_previous_meter_for_pump(self, pump_id: int) -> float:
        """
        Return the current_meter of the most-recently approved session line
        for the given pump.

        Fix applied vs original:
            The original code ordered by "session_id.date desc, id desc" — ordering
            by a Many2one-related path in search() is unreliable in Odoo's ORM (it
            may or may not emit the required SQL JOIN depending on the version).

            "date" is a *stored* related field on this model, so we can order by it
            directly and safely.
        """
        last = self.search(
            [
                ("pump_id", "=", pump_id),
                ("session_id.state", "=", "approved"),
            ],
            order="date desc, id desc",
            limit=1,
        )
        return last.current_meter if last else 0.0

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """
        Fix applied vs original:
            The original code relied solely on @api.onchange to populate
            previous_meter.  onchange only fires in the browser UI — records
            created via the ORM (imports, API calls, tests) would always get
            previous_meter = 0.0, producing incorrect litres_sold.

            We now look up the previous meter in create() so that ALL code
            paths get the correct value.  The onchange below is retained for
            immediate UI feedback.
        """
        for vals in vals_list:
            if vals.get("pump_id") and not vals.get("previous_meter"):
                vals["previous_meter"] = self._get_previous_meter_for_pump(
                    vals["pump_id"]
                )
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Onchange (UI feedback only — authoritative logic lives in create())
    # ------------------------------------------------------------------

    @api.onchange("pump_id")
    def _onchange_pump_id_set_previous(self):
        for line in self:
            if not line.pump_id:
                line.previous_meter = 0.0
                continue
            line.previous_meter = self._get_previous_meter_for_pump(line.pump_id.id)

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    @api.depends("previous_meter", "current_meter")
    def _compute_litres(self):
        for line in self:
            line.litres_sold = (line.current_meter or 0.0) - (line.previous_meter or 0.0)

    @api.depends("litres_sold", "price")
    def _compute_total(self):
        for line in self:
            line.total = (line.litres_sold or 0.0) * (line.price or 0.0)

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    @api.constrains("current_meter", "previous_meter")
    def _check_meter(self):
        for line in self:
            if line.current_meter < 0 or line.previous_meter < 0:
                raise ValidationError("Meter readings must be >= 0.")
            if line.current_meter < line.previous_meter:
                raise ValidationError(
                    f"Current meter ({line.current_meter}) must be >= "
                    f"previous meter ({line.previous_meter}) on pump {line.pump_id.name}."
                )