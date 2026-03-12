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
    date = fields.Date(related="session_id.date", store=True, readonly=True, index=True)
    shift_id = fields.Many2one(related="session_id.shift_id", store=True, readonly=True)

    nozzle_id = fields.Many2one("fuel.nozzle", string="Nozzle", required=True)
    pump_id = fields.Many2one(
        "fuel.pump",
        related="nozzle_id.pump_id",
        store=True,
        readonly=True,
        string="Pump",
    )
    product_id = fields.Many2one(
        related="nozzle_id.product_id",
        store=True,
        readonly=True,
    )

    uom_id = fields.Many2one(
        "uom.uom",
        string="Unit",
        default=lambda self: self.env.ref("uom.product_uom_litre"),
        readonly=True,
    )

    previous_meter = fields.Float(readonly=True)
    current_meter = fields.Float(required=True)

    litres_sold = fields.Float(compute="_compute_litres", store=True)
    price = fields.Float(required=True)
    total = fields.Float(compute="_compute_total", store=True)

    analytic_distribution = fields.Json(
        string="Analytic Distribution",
        default=lambda self: {},
    )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_previous_meter_for_nozzle(self, nozzle_id: int) -> float:
        """
        Return the current_meter of the most-recently approved session line
        for the given nozzle.

        Uses the stored 'date' related field for safe ordering.
        """
        last = self.search(
            [
                ("nozzle_id", "=", nozzle_id),
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
        for vals in vals_list:
            if vals.get("nozzle_id") and not vals.get("previous_meter"):
                vals["previous_meter"] = self._get_previous_meter_for_nozzle(
                    vals["nozzle_id"]
                )
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Onchange (UI feedback only — authoritative logic lives in create())
    # ------------------------------------------------------------------

    @api.onchange("nozzle_id")
    def _onchange_nozzle_id_set_previous(self):
        for line in self:
            if not line.nozzle_id:
                line.previous_meter = 0.0
                continue
            line.previous_meter = self._get_previous_meter_for_nozzle(line.nozzle_id.id)
            product = line.nozzle_id.product_id
            if product:
                if hasattr(product.product_tmpl_id, 'analytic_distribution'):
                    line.analytic_distribution = product.product_tmpl_id.analytic_distribution or {}
                current_price = self.env["fuel.price"].get_current_price(product.id)
                if current_price:
                    line.price = current_price

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
                    f"previous meter ({line.previous_meter}) on {line.nozzle_id.name}."
                )
