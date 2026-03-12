from odoo import fields, models

class FuelPump(models.Model):
    _name = "fuel.pump"
    _description = "Fuel Pump"
    _order = "name"

    name = fields.Char(required=True)  # Pump 1, Pump 2
    code = fields.Char()
    active = fields.Boolean(default=True)
    nozzle_ids = fields.One2many("fuel.nozzle", "pump_id", string="Nozzles")