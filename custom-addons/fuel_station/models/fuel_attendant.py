from odoo import fields, models

class FuelAttendant(models.Model):
    _name = "fuel.attendant"
    _description = "Pump Attendant"
    _order = "name"

    name = fields.Char(required=True)
    employee_id = fields.Many2one("hr.employee")
    active = fields.Boolean(default=True)