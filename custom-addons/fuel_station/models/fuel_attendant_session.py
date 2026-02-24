from odoo import fields, models, api
from odoo.exceptions import ValidationError

class FuelAttendantSession(models.Model):
    _name = "fuel.attendant.session"
    _description = "Attendant Shift Session (Closing)"
    _order = "date desc, id desc"

    name = fields.Char(default="New", readonly=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    shift_id = fields.Many2one("fuel.shift", required=True)
    attendant_id = fields.Many2one("fuel.attendant", required=True)

    state = fields.Selection([("draft", "Draft"), ("approved", "Approved")], default="draft", required=True)

    line_ids = fields.One2many("fuel.attendant.session.line", "session_id", string="Sales")

    credit_sale_ids = fields.One2many("fuel.credit.sale", "session_id", string="Credit Sales")
    cash_deposit_ids = fields.One2many("fuel.cash.deposit", "session_id", string="Cash Deposits")

    total_sales = fields.Float(compute="_compute_totals", store=True)
    total_credit_sales = fields.Float(compute="_compute_totals", store=True)
    expected_cash = fields.Float(compute="_compute_totals", store=True)
    total_cash_deposited = fields.Float(compute="_compute_totals", store=True)
    cash_difference = fields.Float(compute="_compute_totals", store=True)

    approver_id = fields.Many2one("res.users")
    approved_at = fields.Datetime()

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"].next_by_code("fuel.attendant.session") or "AS/"
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq
        return super().create(vals_list)

    @api.depends("line_ids.total", "credit_sale_ids.amount", "cash_deposit_ids.amount")
    def _compute_totals(self):
        for s in self:
            s.total_sales = sum(s.line_ids.mapped("total"))
            s.total_credit_sales = sum(s.credit_sale_ids.mapped("amount"))
            s.expected_cash = s.total_sales - s.total_credit_sales
            s.total_cash_deposited = sum(s.cash_deposit_ids.mapped("amount"))
            s.cash_difference = s.total_cash_deposited - s.expected_cash

    def _shift_window_domain(self):
        """Returns a domain for datetime window for credit/deposit pulls."""
        self.ensure_one()
        start_utc, end_utc = self.shift_id.get_window(self.date)
        return [("date", ">=", fields.Datetime.to_string(start_utc)),
                ("date", "<", fields.Datetime.to_string(end_utc))]

    def action_populate_shift_transactions(self):
        for s in self:
            if s.state != "draft":
                continue

            credit_domain = [
                ("session_id", "=", False),
                ("shift_id", "=", s.shift_id.id),
                ("attendant_id", "=", s.attendant_id.id),
            ] + s._shift_window_domain()

            deposit_domain = [
                ("session_id", "=", False),
                ("shift_id", "=", s.shift_id.id),
                ("attendant_id", "=", s.attendant_id.id),
            ] + s._shift_window_domain()

            credits = self.env["fuel.credit.sale"].search(credit_domain)
            credits.write({"session_id": s.id})

            deposits = self.env["fuel.cash.deposit"].search(deposit_domain)
            deposits.write({"session_id": s.id})

    def action_approve(self):
        for s in self:
            if s.state != "draft":
                continue
            if not s.line_ids:
                raise ValidationError("Add at least one sales line before approval.")
            s.state = "approved"
            s.approver_id = self.env.user.id
            s.approved_at = fields.Datetime.now()