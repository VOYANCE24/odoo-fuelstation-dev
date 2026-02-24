from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class FuelStationShiftClose(models.Model):
    _name = "fuel.station.shift.close"
    _description = "Station Shift Close"
    _order = "date desc, id desc"

    name = fields.Char(
        string="Reference",
        required=True,
        default=lambda self: self.env["ir.sequence"].next_by_code("fuel.station.shift.close") or _("New"),
        readonly=True,
        copy=False,
    )
    date = fields.Datetime(string="Date", required=True, default=fields.Datetime.now)

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        readonly=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        related="company_id.currency_id",
        store=True,
        readonly=True,
    )

    shift_id = fields.Many2one("fuel.shift", string="Shift", required=True)
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Approved")],
        default="draft",
        required=True,
    )

    # Attendant sessions included in this shift close
    session_ids = fields.Many2many(
        "fuel.attendant.session",
        "fuel_station_close_session_rel",
        "close_id",
        "session_id",
        string="Attendant Sessions",
        copy=False,
    )

    # Credit payments received this shift
    credit_payment_ids = fields.One2many(
        "fuel.credit.payment",
        "station_close_id",
        string="Credit Payments",
        copy=False,
    )

    # Tank dip cross-check lines
    tank_check_line_ids = fields.One2many(
        "fuel.station.shift.close.tankcheck",
        "shift_close_id",
        string="Tank Dip Cross-check",
        copy=True,
    )

    notes = fields.Text()

    # Totals from tank check lines
    total_litres_sold = fields.Float(
        string="Total Litres Sold",
        compute="_compute_totals",
        store=True,
        readonly=True,
    )
    total_sales_amount = fields.Monetary(
        string="Total Sales Amount",
        compute="_compute_totals",
        store=True,
        readonly=True,
        currency_field="currency_id",
    )

    # Cash summary from sessions
    pump_sales_total = fields.Monetary(
        string="Pump Sales Total",
        compute="_compute_cash_totals",
        store=False,
        currency_field="currency_id",
    )
    pump_credit_total = fields.Monetary(
        string="Pump Credit Total",
        compute="_compute_cash_totals",
        store=False,
        currency_field="currency_id",
    )
    cash_expected = fields.Monetary(
        string="Expected Cash (from Pumps)",
        compute="_compute_cash_totals",
        store=False,
        currency_field="currency_id",
    )
    cash_deposited_by_attendants = fields.Monetary(
        string="Cash Deposited by Attendants",
        compute="_compute_cash_totals",
        store=False,
        currency_field="currency_id",
    )
    cash_credit_payments = fields.Monetary(
        string="Credit Payments (Cash)",
        compute="_compute_cash_totals",
        store=False,
        currency_field="currency_id",
    )
    cheque_credit_payments = fields.Monetary(
        string="Credit Payments (Cheque)",
        compute="_compute_cash_totals",
        store=False,
        currency_field="currency_id",
    )
    cash_deposited_in_safe = fields.Monetary(
        string="Cash Deposited in Safe",
        currency_field="currency_id",
    )
    cash_difference = fields.Monetary(
        string="Cash Difference",
        compute="_compute_cash_totals",
        store=False,
        currency_field="currency_id",
        help="Cash Deposited in Safe minus Expected Cash from pumps.",
    )

    @api.depends("tank_check_line_ids.litres_sold", "tank_check_line_ids.sales_amount")
    def _compute_totals(self):
        for rec in self:
            rec.total_litres_sold = sum(rec.tank_check_line_ids.mapped("litres_sold")) or 0.0
            rec.total_sales_amount = sum(rec.tank_check_line_ids.mapped("sales_amount")) or 0.0

    @api.depends(
        "session_ids.line_ids.total",
        "session_ids.credit_sale_ids.amount",
        "session_ids.cash_deposit_ids.amount",
        "credit_payment_ids.amount_paid",
        "credit_payment_ids.payment_method",
        "cash_deposited_in_safe",
    )
    def _compute_cash_totals(self):
        for rec in self:
            sales_total = 0.0
            credit_total = 0.0
            deposited = 0.0

            for s in rec.session_ids:
                sales_total += sum(s.line_ids.mapped("total")) if s.line_ids else 0.0
                credit_total += sum(s.credit_sale_ids.mapped("amount")) if s.credit_sale_ids else 0.0
                deposited += sum(s.cash_deposit_ids.mapped("amount")) if s.cash_deposit_ids else 0.0

            cash_cp = sum(p.amount_paid for p in rec.credit_payment_ids if p.payment_method == "cash")
            cheque_cp = sum(p.amount_paid for p in rec.credit_payment_ids if p.payment_method == "cheque")

            rec.pump_sales_total = sales_total
            rec.pump_credit_total = credit_total
            rec.cash_expected = sales_total - credit_total
            rec.cash_deposited_by_attendants = deposited
            rec.cash_credit_payments = cash_cp
            rec.cheque_credit_payments = cheque_cp
            rec.cash_difference = (rec.cash_deposited_in_safe or 0.0) - rec.cash_expected

    def action_approve(self):
        for rec in self:
            if not rec.tank_check_line_ids:
                raise ValidationError(_("Add at least one tank cross-check line."))
            if not rec.session_ids:
                raise ValidationError(_("Select at least one attendant session to close this shift."))
            rec.state = "done"


class FuelStationShiftCloseTankCheck(models.Model):
    _name = "fuel.station.shift.close.tankcheck"
    _description = "Station Shift Close — Tank Dip Cross-check"
    _order = "sequence, id"

    shift_close_id = fields.Many2one(
        "fuel.station.shift.close", required=True, ondelete="cascade"
    )
    sequence = fields.Integer(default=10)

    company_id = fields.Many2one(
        related="shift_close_id.company_id", store=True, readonly=True
    )
    currency_id = fields.Many2one(
        related="shift_close_id.currency_id", store=True, readonly=True
    )

    product_id = fields.Many2one("product.product", string="Fuel Type", required=True)

    opening_depth_mm = fields.Float(string="Opening Depth (mm)")
    closing_depth_mm = fields.Float(string="Closing Depth (mm)")
    opening_volume_liters = fields.Float(string="Opening Volume (L)")
    closing_volume_liters = fields.Float(string="Closing Volume (L)")

    deliveries_liters = fields.Float(
        string="Deliveries (L)", compute="_compute_deliveries", store=True
    )
    litres_sold = fields.Float(string="Litres Sold (L)")
    price = fields.Float(string="Price")

    sales_amount = fields.Monetary(
        string="Sales Amount",
        compute="_compute_sales_amount",
        store=True,
        currency_field="currency_id",
    )
    expected_closing_volume = fields.Float(
        string="Expected Closing (L)", compute="_compute_check", store=True
    )
    variance_liters = fields.Float(
        string="Variance (L)", compute="_compute_check", store=True
    )
    loss_amount = fields.Monetary(
        string="Loss Amount",
        compute="_compute_check",
        store=True,
        currency_field="currency_id",
    )

    @api.depends("litres_sold", "price")
    def _compute_sales_amount(self):
        for rec in self:
            rec.sales_amount = (rec.litres_sold or 0.0) * (rec.price or 0.0)

    @api.depends("shift_close_id.date", "product_id")
    def _compute_deliveries(self):
        FuelDelivery = self.env["fuel.delivery"]
        for rec in self:
            rec.deliveries_liters = 0.0
            if not rec.shift_close_id.date or not rec.product_id:
                continue

            shift_dt = rec.shift_close_id.date
            day_start = fields.Datetime.to_string(fields.Datetime.start_of(shift_dt, "day"))
            day_end = fields.Datetime.to_string(fields.Datetime.end_of(shift_dt, "day"))

            deliveries = FuelDelivery.search([
                ("state", "=", "applied"),
                ("create_date", ">=", day_start),
                ("create_date", "<=", day_end),
            ])

            total = 0.0
            for d in deliveries:
                for line in d.compartment_line_ids:
                    if line.product_id and line.product_id.id == rec.product_id.id:
                        total += line.measured_volume_liters or 0.0
            rec.deliveries_liters = total

    @api.depends(
        "opening_volume_liters",
        "closing_volume_liters",
        "deliveries_liters",
        "litres_sold",
        "price",
    )
    def _compute_check(self):
        for rec in self:
            opening = rec.opening_volume_liters or 0.0
            closing = rec.closing_volume_liters or 0.0
            deliveries = rec.deliveries_liters or 0.0
            sold = rec.litres_sold or 0.0

            rec.expected_closing_volume = opening + deliveries - sold
            rec.variance_liters = closing - rec.expected_closing_volume
            rec.loss_amount = abs(rec.variance_liters) * (rec.price or 0.0)