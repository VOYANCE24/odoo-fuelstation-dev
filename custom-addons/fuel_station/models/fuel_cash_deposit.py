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

    currency_id = fields.Many2one(
        'res.currency',
        compute='_compute_currency_id',
        string='Currency',
    )
    is_locked = fields.Boolean(
        compute="_compute_is_locked",
        string="Locked",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("fuel.cash.deposit") or "CD/"
                )
        return super().create(vals_list)

    def write(self, vals):
        locked = self.filtered(
            lambda r: r.session_id and r.session_id.state == "approved"
        )
        if locked:
            raise ValidationError(
                "Cannot edit a cash deposit that belongs to an approved session. "
                "Reset the session to Draft first."
            )
        return super().write(vals)

    def unlink(self):
        locked = self.filtered(
            lambda r: r.session_id and r.session_id.state == "approved"
        )
        if locked:
            raise ValidationError(
                "Cannot delete a cash deposit that belongs to an approved session. "
                "Reset the session to Draft first."
            )
        return super().unlink()

    @api.depends("session_id", "session_id.state")
    def _compute_is_locked(self):
        for rec in self:
            rec.is_locked = bool(rec.session_id and rec.session_id.state == "approved")

    @api.depends_context('company')
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = self.env.company.currency_id

    @api.constrains("amount")
    def _check_amount(self):
        for r in self:
            if r.amount <= 0:
                raise ValidationError("Deposit amount must be greater than 0.")