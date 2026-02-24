from odoo import fields, models, api
from odoo.exceptions import ValidationError

class FuelCashDeposit(models.Model):
    _name = "fuel.cash.deposit"
    _description = "Cash Deposit (Attendant to Cashier)"
    _order = "date desc, id desc"

    name = fields.Char(default="New", readonly=True)
    date = fields.Datetime(required=True, default=fields.Datetime.now)

    shift_id = fields.Many2one("fuel.shift", required=True)
    attendant_id = fields.Many2one("fuel.attendant", required=True)

    amount = fields.Float(required=True)
    received_by_id = fields.Many2one("res.users", default=lambda self: self.env.user)
    note = fields.Char()

    session_id = fields.Many2one("fuel.attendant.session", index=True)
    station_close_id = fields.Many2one("fuel.station.shift.close", index=True)

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"].next_by_code("fuel.cash.deposit") or "CD/"
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq
        return super().create(vals_list)

    @api.constrains("amount")
    def _check_amount(self):
        for r in self:
            if r.amount <= 0:
                raise ValidationError("Deposit amount must be greater than 0.")