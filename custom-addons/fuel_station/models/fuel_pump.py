from odoo import fields, models

class FuelPump(models.Model):
    _name = "fuel.pump"
    _description = "Fuel Pump"
    _order = "name"

    name = fields.Char(required=True)  # Pump 1, Pump 2
    code = fields.Char()
    product_id = fields.Many2one(
        "product.product",
        required=True,
        domain=[("type", "in", ["consu", "product"])],
        string="Fuel Product"
    )
    active = fields.Boolean(default=True)