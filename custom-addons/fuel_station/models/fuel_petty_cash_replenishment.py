from odoo import fields, models, api
from odoo.exceptions import ValidationError


class FuelPettyCashReplenishment(models.Model):
    _name = "fuel.petty.cash.replenishment"
    _description = "Petty Cash Deposit"
    _order = "date desc, id desc"

    name = fields.Char(default="New", readonly=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    amount = fields.Float(required=True, string="Amount", digits=(16, 2))
    source = fields.Char(string="Source")
    received_by = fields.Many2one(
        "res.users",
        default=lambda self: self.env.user,
        string="Received By",
    )
    note = fields.Char(string="Note")
    station_close_id = fields.Many2one(
        "fuel.station.shift.close",
        string="Shift Close",
        index=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_currency_id",
        string="Currency",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code(
                        "fuel.petty.cash.replenishment"
                    )
                    or "PCR/"
                )
        return super().create(vals_list)

    @api.depends_context("company")
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = self.env.company.currency_id

    @api.constrains("amount")
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError("Deposit amount must be greater than 0.")
