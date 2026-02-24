from odoo import fields, models, api
from odoo.exceptions import ValidationError


class FuelStationShiftClose(models.Model):
    _name = "fuel.station.shift.close"
    _description = "Station Shift Close"
    _order = "date desc, id desc"

    name = fields.Char(default="New", readonly=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    shift_id = fields.Many2one("fuel.shift", required=True)

    state = fields.Selection(
        [("draft", "Draft"), ("approved", "Approved")],
        default="draft",
        required=True,
    )

    attendant_session_ids = fields.Many2many(
        "fuel.attendant.session",
        "fuel_station_close_session_rel",
        "close_id",
        "session_id",
        string="Approved Attendant Sessions",
        domain=[("state", "=", "approved")],
    )

    fuel_balance_line_ids = fields.One2many(
        "fuel.station.fuel.balance.line", "close_id", string="Fuel Balance"
    )

    credit_payment_ids = fields.One2many(
        "fuel.credit.payment", "station_close_id", string="Credit Payments"
    )

    # ------------------------------------------------------------------ #
    # Cash balancing fields                                                #
    # ------------------------------------------------------------------ #

    pump_sales_total = fields.Float(
        compute="_compute_cash",
        store=True,
        string="Total Pump Sales",
    )
    pump_credit_total = fields.Float(
        compute="_compute_cash",
        store=True,
        string="Total Credit Sales",
    )

    # Removed: cash_deposited_by_attendants
    #   This field was computed but never referenced in any formula or view,
    #   making it dead weight that could mislead operators reading the form.
    #   The per-session breakdown is accessible via attendant_session_ids.

    cash_credit_payments = fields.Float(
        compute="_compute_cash",
        store=True,
        string="Cash Credit Payments Received",
        help="Sum of credit payments received in cash during this shift.",
    )
    cheque_credit_payments = fields.Float(
        compute="_compute_cash",
        store=True,
        string="Cheque Credit Payments Received",
        help="Sum of credit payments received by cheque during this shift.",
    )

    cash_expected = fields.Float(
        compute="_compute_cash",
        store=True,
        string="Expected Cash",
        help=(
            "= Pump Sales − Credit Sales + Cash Credit Payments received.\n"
            "This is the cash the cashier should physically hold."
        ),
    )

    cash_deposited_in_safe = fields.Float(string="Cash Deposited in Safe")

    safe_difference = fields.Float(
        compute="_compute_cash",
        store=True,
        string="Safe Difference",
        help="= Cash Deposited in Safe − Expected Cash. Negative = shortage.",
    )

    approver_id = fields.Many2one("res.users", readonly=True)
    approved_at = fields.Datetime(readonly=True)

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
                    self.env["ir.sequence"].next_by_code("fuel.station.shift.close")
                    or "SC/"
                )
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    @api.depends(
        "attendant_session_ids.total_sales",
        "attendant_session_ids.total_credit_sales",
        "credit_payment_ids.amount_paid",
        "credit_payment_ids.payment_method",
        "cash_deposited_in_safe",
    )
    def _compute_cash(self):
        """
        Cash balancing formula (business logic):

            pump_sales_total      = Σ session.total_sales
            pump_credit_total     = Σ session.total_credit_sales
            cash_credit_payments  = Σ credit_payments where method = cash
            cheque_credit_payments= Σ credit_payments where method = cheque

            cash_expected = pump_sales_total
                          − pump_credit_total          (credit sales reduce cash due)
                          + cash_credit_payments        (cash collected for old credit)

            safe_difference = cash_deposited_in_safe − cash_expected
                              (positive = overage, negative = shortage)

        Note: cheque_credit_payments improve the station's credit book but do NOT
        affect the physical cash expected in the safe.
        """
        for close in self:
            close.pump_sales_total = sum(
                close.attendant_session_ids.mapped("total_sales")
            )
            close.pump_credit_total = sum(
                close.attendant_session_ids.mapped("total_credit_sales")
            )

            cash_payments = close.credit_payment_ids.filtered(
                lambda p: p.payment_method == "cash"
            )
            cheque_payments = close.credit_payment_ids.filtered(
                lambda p: p.payment_method == "cheque"
            )

            close.cash_credit_payments = sum(cash_payments.mapped("amount_paid"))
            close.cheque_credit_payments = sum(cheque_payments.mapped("amount_paid"))

            close.cash_expected = (
                close.pump_sales_total
                - close.pump_credit_total
                + close.cash_credit_payments
            )
            close.safe_difference = (
                (close.cash_deposited_in_safe or 0.0) - close.cash_expected
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _shift_window_domain(self):
        """
        Return a domain fragment covering the datetime window for this close's
        shift on this close's date.
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

    def action_pull_sessions(self):
        """Pull all approved sessions for this date + shift into the close."""
        for close in self:
            sessions = self.env["fuel.attendant.session"].search([
                ("state", "=", "approved"),
                ("date", "=", close.date),
                ("shift_id", "=", close.shift_id.id),
            ])
            close.attendant_session_ids = [(6, 0, sessions.ids)]

    def action_prepare_balancing(self):
        """
        Create fuel balance lines for every product that appeared in any
        session pump line or is assigned to any active pump.
        Existing lines are not duplicated.
        """
        for close in self:
            # Collect products from pumps and session sales lines.
            products = self.env["fuel.pump"].search([]).mapped("product_id")
            products |= close.attendant_session_ids.mapped("line_ids.product_id")
            products = products.filtered(lambda p: p.id)

            existing_product_ids = close.fuel_balance_line_ids.mapped("product_id").ids
            for product in products:
                if product.id not in existing_product_ids:
                    self.env["fuel.station.fuel.balance.line"].create({
                        "close_id": close.id,
                        "product_id": product.id,
                    })

    def action_pull_credit_payments(self):
        """
        Attach unlinked credit payments posted during this shift to this close.
        Filtered by shift_id + datetime window to prevent cross-shift contamination.
        """
        for close in self:
            payments = self.env["fuel.credit.payment"].search(
                [
                    ("station_close_id", "=", False),
                    ("shift_id", "=", close.shift_id.id),
                ]
                + close._shift_window_domain()
            )
            payments.write({"station_close_id": close.id})

    def action_approve(self):
        for close in self:
            if close.state != "draft":
                continue
            if not close.attendant_session_ids:
                raise ValidationError(
                    "Pull or select approved attendant sessions before approval."
                )
            if not close.fuel_balance_line_ids:
                raise ValidationError(
                    "Prepare fuel balancing lines before approval."
                )
            close.write(
                {
                    "state": "approved",
                    "approver_id": self.env.user.id,
                    "approved_at": fields.Datetime.now(),
                }
            )