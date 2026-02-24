from odoo import fields, models, api
from odoo.exceptions import ValidationError

class FuelCreditSale(models.Model):
    _name = "fuel.credit.sale"
    _description = "Fuel Credit Sale"
    _order = "date desc, id desc"

    name = fields.Char(default="New", readonly=True)
    date = fields.Datetime(required=True, default=fields.Datetime.now)

    shift_id = fields.Many2one("fuel.shift", required=True)
    attendant_id = fields.Many2one("fuel.attendant", required=True)
    pump_id = fields.Many2one("fuel.pump", required=True)
    product_id = fields.Many2one(related="pump_id.product_id", store=True, readonly=True)

    invoice_ref = fields.Char(required=True)
    customer_id = fields.Many2one("res.partner", domain=[("customer_rank", ">", 0)])
    customer_name = fields.Char()
    vehicle_type = fields.Char()
    vehicle_plate = fields.Char()

    litres = fields.Float(required=True)
    price = fields.Float(required=True)
    amount = fields.Float(compute="_compute_amount", store=True)

    session_id = fields.Many2one("fuel.attendant.session", index=True)
    station_close_id = fields.Many2one("fuel.station.shift.close", index=True)

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"].next_by_code("fuel.credit.sale") or "CS/"
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq
        return super().create(vals_list)

    @api.depends("litres", "price")
    def _compute_amount(self):
        for r in self:
            r.amount = (r.litres or 0.0) * (r.price or 0.0)

    @api.constrains("litres", "price")
    def _check_positive(self):
        for r in self:
            if r.litres <= 0:
                raise ValidationError("Litres must be greater than 0.")
            if r.price < 0:
                raise ValidationError("Price must be >= 0.")