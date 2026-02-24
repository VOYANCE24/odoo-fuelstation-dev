from odoo import fields, models, api
from odoo.exceptions import ValidationError

class FuelStationShiftClose(models.Model):
    _name = "fuel.station.shift.close"
    _description = "Station Shift Close"
    _order = "date desc, id desc"

    name = fields.Char(default="New", readonly=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    shift_id = fields.Many2one("fuel.shift", required=True)

    state = fields.Selection([("draft", "Draft"), ("approved", "Approved")], default="draft", required=True)

    attendant_session_ids = fields.Many2many(
        "fuel.attendant.session",
        "fuel_station_close_session_rel",
        "close_id",
        "session_id",
        string="Approved Attendant Sessions",
        domain=[("state", "=", "approved")],
    )

    fuel_balance_line_ids = fields.One2many("fuel.station.fuel.balance.line", "close_id")

    # credit payments during shift
    credit_payment_ids = fields.One2many("fuel.credit.payment", "station_close_id")

    pump_sales_total = fields.Float(compute="_compute_cash", store=True)
    pump_credit_total = fields.Float(compute="_compute_cash", store=True)
    cash_deposited_by_attendants = fields.Float(compute="_compute_cash", store=True)

    cash_credit_payments = fields.Float(compute="_compute_cash", store=True)
    cheque_credit_payments = fields.Float(compute="_compute_cash", store=True)

    cash_expected = fields.Float(compute="_compute_cash", store=True)

    cash_deposited_in_safe = fields.Float()
    safe_difference = fields.Float(compute="_compute_cash", store=True)

    approver_id = fields.Many2one("res.users")
    approved_at = fields.Datetime()

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"].next_by_code("fuel.station.shift.close") or "SC/"
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq
        return super().create(vals_list)

    @api.depends(
        "attendant_session_ids.total_sales",
        "attendant_session_ids.total_credit_sales",
        "attendant_session_ids.total_cash_deposited",
        "credit_payment_ids.amount_paid",
        "credit_payment_ids.payment_method",
        "cash_deposited_in_safe",
    )
    def _compute_cash(self):
        for c in self:
            c.pump_sales_total = sum(c.attendant_session_ids.mapped("total_sales"))
            c.pump_credit_total = sum(c.attendant_session_ids.mapped("total_credit_sales"))
            c.cash_deposited_by_attendants = sum(c.attendant_session_ids.mapped("total_cash_deposited"))

            c.cash_credit_payments = sum(c.credit_payment_ids.filtered(lambda x: x.payment_method == "cash").mapped("amount_paid"))
            c.cheque_credit_payments = sum(c.credit_payment_ids.filtered(lambda x: x.payment_method == "cheque").mapped("amount_paid"))

            c.cash_expected = (c.pump_sales_total - c.pump_credit_total) + c.cash_credit_payments
            c.safe_difference = (c.cash_deposited_in_safe or 0.0) - (c.cash_expected or 0.0)

    def _shift_window_domain(self):
        self.ensure_one()
        start_utc, end_utc = self.shift_id.get_window(self.date)
        return [("date", ">=", fields.Datetime.to_string(start_utc)),
                ("date", "<", fields.Datetime.to_string(end_utc))]

    def action_pull_sessions(self):
        """Pull all approved sessions for the same date+shift"""
        for c in self:
            sessions = self.env["fuel.attendant.session"].search([
                ("state", "=", "approved"),
                ("date", "=", c.date),
                ("shift_id", "=", c.shift_id.id),
            ])
            c.attendant_session_ids = [(6, 0, sessions.ids)]

    def action_prepare_balancing(self):
        """Create/update fuel balance lines based on products in pumps and sessions."""
        for c in self:
            products = c.env["fuel.pump"].search([]).mapped("product_id")
            products |= c.attendant_session_ids.mapped("line_ids.product_id")
            products = products.filtered(lambda p: p)

            existing = {l.product_id.id: l for l in c.fuel_balance_line_ids}
            for p in products:
                if p.id not in existing:
                    self.env["fuel.station.fuel.balance.line"].create({
                        "close_id": c.id,
                        "product_id": p.id,
                    })

    def action_pull_credit_payments(self):
        """Attach credit payments posted during this shift to this station close."""
        for c in self:
            pay = self.env["fuel.credit.payment"].search([
                ("station_close_id", "=", False),
                ("shift_id", "=", c.shift_id.id),
            ] + c._shift_window_domain())
            pay.write({"station_close_id": c.id})

    def action_approve(self):
        for c in self:
            if c.state != "draft":
                continue
            if not c.attendant_session_ids:
                raise ValidationError("Pull/Select approved attendant sessions before approval.")
            if not c.fuel_balance_line_ids:
                raise ValidationError("Prepare fuel balancing lines before approval.")
            c.state = "approved"
            c.approver_id = self.env.user.id
            c.approved_at = fields.Datetime.now()