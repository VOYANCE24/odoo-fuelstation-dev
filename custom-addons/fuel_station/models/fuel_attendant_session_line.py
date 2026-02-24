from odoo import fields, models, api
from odoo.exceptions import ValidationError

class FuelAttendantSessionLine(models.Model):
    _name = "fuel.attendant.session.line"
    _description = "Attendant Session Sales Line"
    _order = "id"

    session_id = fields.Many2one("fuel.attendant.session", required=True, ondelete="cascade")
    date = fields.Date(related="session_id.date", store=True, readonly=True)
    shift_id = fields.Many2one(related="session_id.shift_id", store=True, readonly=True)

    pump_id = fields.Many2one("fuel.pump", required=True)
    product_id = fields.Many2one(related="pump_id.product_id", store=True, readonly=True)

    previous_meter = fields.Float(readonly=True)
    current_meter = fields.Float(required=True)

    litres_sold = fields.Float(compute="_compute_litres", store=True)
    price = fields.Float(required=True)
    total = fields.Float(compute="_compute_total", store=True)

    @api.onchange("pump_id")
    def _onchange_pump_id_set_previous(self):
        for l in self:
            if not l.pump_id:
                l.previous_meter = 0.0
                return

            # find last approved line for this pump
            last = self.env["fuel.attendant.session.line"].search([
                ("pump_id", "=", l.pump_id.id),
                ("session_id.state", "=", "approved"),
            ], order="session_id.date desc, id desc", limit=1)

            l.previous_meter = last.current_meter if last else 0.0

    @api.depends("previous_meter", "current_meter")
    def _compute_litres(self):
        for l in self:
            l.litres_sold = (l.current_meter or 0.0) - (l.previous_meter or 0.0)

    @api.depends("litres_sold", "price")
    def _compute_total(self):
        for l in self:
            l.total = (l.litres_sold or 0.0) * (l.price or 0.0)

    @api.constrains("current_meter", "previous_meter")
    def _check_meter(self):
        for l in self:
            if l.current_meter < l.previous_meter:
                raise ValidationError("Current meter must be >= previous meter.")
            if l.current_meter < 0 or l.previous_meter < 0:
                raise ValidationError("Meter readings must be >= 0.")