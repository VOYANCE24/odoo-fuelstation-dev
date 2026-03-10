from odoo import fields, models, api
from odoo.exceptions import ValidationError


class FuelAttendantSession(models.Model):
    _name = "fuel.attendant.session"
    _description = "Attendant Shift Session (Closing)"
    _order = "date desc, id desc"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    _unique_attendant_shift_date = models.Constraint(
        "UNIQUE(attendant_id, shift_id, date)",
        "An attendant can only have one session per shift per day.",
    )

    name = fields.Char(default="New", readonly=True)
    date = fields.Date(required=True, default=fields.Date.context_today, index=True)
    shift_id = fields.Many2one("fuel.shift", required=True)
    attendant_id = fields.Many2one("fuel.attendant", required=True)

    state = fields.Selection(
        [("draft", "Draft"), ("approved", "Approved")],
        default="draft",
        required=True,
        index=True,
    )

    line_ids = fields.One2many(
        "fuel.attendant.session.line", "session_id", string="Sales"
    )
    credit_sale_ids = fields.One2many(
        "fuel.credit.sale", "session_id", string="Credit Sales"
    )
    cash_deposit_ids = fields.One2many(
        "fuel.cash.deposit", "session_id", string="Cash Deposits"
    )

    total_sales = fields.Float(compute="_compute_totals", store=True)
    total_credit_sales = fields.Float(compute="_compute_totals", store=True)
    expected_cash = fields.Float(compute="_compute_totals", store=True)
    total_cash_deposited = fields.Float(compute="_compute_totals", store=True)
    cash_difference = fields.Float(compute="_compute_totals", store=True)

    approver_id = fields.Many2one("res.users")
    approved_at = fields.Datetime()

    currency_id = fields.Many2one(
        'res.currency',
        compute='_compute_currency_id',
        string='Currency',
    )
    credit_sale_count = fields.Integer(compute='_compute_counts')
    cash_deposit_count = fields.Integer(compute='_compute_counts')

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """
        Fix: sequence called inside loop — each record gets its own unique number.
        """
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("fuel.attendant.session")
                    or "AS/"
                )
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    @api.depends(
        "line_ids.total",
        "credit_sale_ids.amount",
        "cash_deposit_ids.amount",
    )
    def _compute_totals(self):
        for session in self:
            session.total_sales = sum(session.line_ids.mapped("total"))
            session.total_credit_sales = sum(session.credit_sale_ids.mapped("amount"))
            session.expected_cash = session.total_sales - session.total_credit_sales
            session.total_cash_deposited = sum(session.cash_deposit_ids.mapped("amount"))
            session.cash_difference = (
                session.total_cash_deposited - session.expected_cash
            )

    @api.depends_context('company')
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = self.env.company.currency_id

    @api.depends('credit_sale_ids', 'cash_deposit_ids')
    def _compute_counts(self):
        for rec in self:
            rec.credit_sale_count = len(rec.credit_sale_ids)
            rec.cash_deposit_count = len(rec.cash_deposit_ids)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _shift_window_domain(self):
        """
        Return a domain fragment covering the datetime window for this session's
        shift on this session's date.

        Requires the user's timezone to be configured.  Falls back to UTC but
        logs a warning because an unconfigured timezone will silently misplace
        records at the shift boundaries.
        """
        self.ensure_one()
        start_utc, end_utc = self.shift_id.get_window(self.date)
        return [
            ("date", ">=", fields.Datetime.to_string(start_utc)),
            ("date", "<", fields.Datetime.to_string(end_utc)),
        ]

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_populate_shift_transactions(self):
        """
        Pull unlinked credit sales and cash deposits for this attendant / shift
        and attach them to this session.
        """
        for session in self:
            if session.state != "draft":
                continue

            base_domain = [
                ("session_id", "=", False),
                ("shift_id", "=", session.shift_id.id),
                ("attendant_id", "=", session.attendant_id.id),
            ] + session._shift_window_domain()

            credits = self.env["fuel.credit.sale"].search(base_domain)
            credits.write({"session_id": session.id})

            deposits = self.env["fuel.cash.deposit"].search(base_domain)
            deposits.write({"session_id": session.id})

    def action_approve(self):
        for session in self:
            if session.state != "draft":
                continue
            if not session.line_ids:
                raise ValidationError(
                    "Add at least one sales line before approving the session."
                )
            session.write(
                {
                    "state": "approved",
                    "approver_id": self.env.user.id,
                    "approved_at": fields.Datetime.now(),
                }
            )

    def action_open_credit_sales(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Credit Sales',
            'res_model': 'fuel.credit.sale',
            'view_mode': 'list,form',
            'domain': [('session_id', '=', self.id)],
            'context': {'default_session_id': self.id},
        }

    def action_open_cash_deposits(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cash Deposits',
            'res_model': 'fuel.cash.deposit',
            'view_mode': 'list,form',
            'domain': [('session_id', '=', self.id)],
            'context': {'default_session_id': self.id},
        }