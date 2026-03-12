from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FuelNozzle(models.Model):
    _name = "fuel.nozzle"
    _description = "Fuel Pump Nozzle"
    _order = "pump_id, nozzle_number"

    _unique_pump_nozzle_number = models.Constraint(
        "UNIQUE(pump_id, nozzle_number)",
        "Each nozzle number must be unique per pump.",
    )

    pump_id = fields.Many2one(
        "fuel.pump",
        string="Pump",
        required=True,
        ondelete="cascade",
        index=True,
    )
    nozzle_number = fields.Integer(string="Nozzle #", required=True, default=1)
    name = fields.Char(
        compute="_compute_name",
        store=True,
        readonly=False,
        required=True,
    )
    product_id = fields.Many2one(
        "product.product",
        string="Fuel Product",
        required=True,
        domain=[("type", "in", ["consu", "product"])],
    )
    active = fields.Boolean(default=True)

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    @api.depends("pump_id", "nozzle_number")
    def _compute_name(self):
        for nozzle in self:
            if nozzle.pump_id and nozzle.nozzle_number:
                nozzle.name = f"{nozzle.pump_id.name} – Nozzle {nozzle.nozzle_number}"
            else:
                nozzle.name = nozzle.name or ""

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    @api.constrains("nozzle_number")
    def _check_nozzle_number(self):
        for nozzle in self:
            if nozzle.nozzle_number < 1 or nozzle.nozzle_number > 4:
                raise ValidationError("Nozzle number must be between 1 and 4.")
