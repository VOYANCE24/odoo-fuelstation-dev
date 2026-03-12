from odoo import api, fields, models
from datetime import date as date_type, timedelta


class FuelDashboard(models.TransientModel):
    """
    Fuel Station Dashboard — transient singleton opened via action_open().

    Lifecycle
    ---------
    The menu item calls the server action which calls action_open().
    action_open() calls self.create({}), which triggers create() →
    _populate_tank_levels() + _populate_attendant_ranks().
    The resulting record id is returned as an act_window so the user
    lands directly on a fully-populated, read-only dashboard form.

    A "Refresh" button recreates all computed sub-lines for the current
    period selection.
    """
    _name = "fuel.dashboard"
    _description = "Fuel Station Dashboard"

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "Fuel Station Dashboard"

    # ------------------------------------------------------------------
    # Period selector
    # ------------------------------------------------------------------

    date_from = fields.Date(
        string="From",
        required=True,
        default=lambda self: date_type.today().replace(day=1),
    )
    date_to = fields.Date(
        string="To",
        required=True,
        default=fields.Date.today,
    )

    last_refreshed = fields.Datetime(string="Last Refreshed", readonly=True)

    # ------------------------------------------------------------------
    # KPI — store=False so they always reflect live data when rendered
    # ------------------------------------------------------------------

    total_litres_sold = fields.Float(
        string="Litres Sold",
        compute="_compute_kpis",
        digits=(16, 2),
    )
    total_revenue = fields.Float(
        string="Sales Revenue",
        compute="_compute_kpis",
        digits=(16, 2),
    )
    total_credit_sales = fields.Float(
        string="Credit Sales",
        compute="_compute_kpis",
        digits=(16, 2),
    )
    total_loss_litres = fields.Float(
        string="Loss (L)",
        compute="_compute_kpis",
        digits=(16, 2),
    )
    total_loss_value = fields.Float(
        string="Loss Value",
        compute="_compute_kpis",
        digits=(16, 2),
    )
    total_receivables = fields.Float(
        string="Outstanding Receivables",
        compute="_compute_receivables",
        digits=(16, 2),
    )
    total_cash_collected = fields.Float(
        string="Cash Collected",
        compute="_compute_cash_collected",
        digits=(16, 2),
        help="Sum of cash deposited in safe across approved shift closes in the period.",
    )
    petty_cash_balance = fields.Float(
        string="Petty Cash Balance",
        compute="_compute_petty_cash_kpis",
        digits=(16, 2),
        help="Running petty cash balance: total replenishments minus all posted expenses.",
    )
    total_period_expenses = fields.Float(
        string="Period Cash Expenses",
        compute="_compute_petty_cash_kpis",
        digits=(16, 2),
        help="Total posted cash expenses in the selected period.",
    )
    total_safe_difference = fields.Float(
        string="Cash Variance",
        compute="_compute_cash_variance",
        digits=(16, 2),
        help="Sum of safe_difference across approved shift closes in the period. "
             "Negative = shortage, Positive = overage.",
    )
    total_cash_credit_received = fields.Float(
        string="Cash Credit Payments",
        compute="_compute_credit_collections",
        digits=(16, 2),
        help="Sum of credit payments received in cash during the selected period.",
    )
    total_cheque_credit_received = fields.Float(
        string="Cheque Credit Payments",
        compute="_compute_credit_collections",
        digits=(16, 2),
        help="Sum of credit payments received by cheque during the selected period.",
    )

    currency_id = fields.Many2one(
        'res.currency',
        compute='_compute_currency_id',
        string='Currency',
    )

    # ------------------------------------------------------------------
    # Alert counts (plain stored fields set in _populate_tank_levels)
    # ------------------------------------------------------------------

    pending_session_count = fields.Integer(string="Draft Sessions")
    unpaid_credit_count = fields.Integer(string="Unpaid Credit Sales")
    pending_delivery_count = fields.Integer(string="Draft Deliveries")

    # ------------------------------------------------------------------
    # Sub-line One2manys (populated in create / refresh)
    # ------------------------------------------------------------------

    tank_level_ids = fields.One2many(
        "fuel.dashboard.tank.level",
        "dashboard_id",
        string="Tank Levels",
    )
    attendant_rank_ids = fields.One2many(
        "fuel.dashboard.attendant.rank",
        "dashboard_id",
        string="Top Attendants",
    )

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._populate_tank_levels()
            rec._populate_attendant_ranks()
        return records

    def write(self, vals):
        """
        Auto-refresh sub-lines whenever the date range changes so operators do
        not have to click the Refresh button after adjusting the period.
        """
        result = super().write(vals)
        if "date_from" in vals or "date_to" in vals:
            for rec in self:
                rec._populate_tank_levels()
                rec._populate_attendant_ranks()
        return result

    # ------------------------------------------------------------------
    # Compute — KPIs
    # ------------------------------------------------------------------

    @api.depends("date_from", "date_to")
    def _compute_kpis(self):
        SessionLine = self.env["fuel.attendant.session.line"]
        BalanceLine = self.env["fuel.station.fuel.balance.line"]

        for rec in self:
            df, dt = rec.date_from, rec.date_to

            # ── Litres sold & revenue — single SQL SUM via read_group ─────
            sl_domain = [("session_id.state", "=", "approved")]
            if df:
                sl_domain.append(("date", ">=", df))
            if dt:
                sl_domain.append(("date", "<=", dt))
            sl_result = SessionLine.read_group(
                domain=sl_domain,
                fields=["litres_sold:sum", "total:sum"],
                groupby=[],
            )
            rec.total_litres_sold = sl_result[0]["litres_sold"] if sl_result else 0.0
            rec.total_revenue = sl_result[0]["total"] if sl_result else 0.0

            # ── Credit sales — single SQL SUM ─────────────────────────────
            cs_domain = [("session_id.state", "=", "approved")]
            if df:
                cs_domain.append(("date", ">=", fields.Datetime.to_datetime(df)))
            if dt:
                cs_domain.append(("date", "<=", fields.Datetime.to_datetime(dt).replace(
                    hour=23, minute=59, second=59
                )))
            cs_result = self.env["fuel.credit.sale"].read_group(
                domain=cs_domain,
                fields=["amount:sum"],
                groupby=[],
            )
            rec.total_credit_sales = cs_result[0]["amount"] if cs_result else 0.0

            # ── Variance / loss — single SQL SUM (only positive differences) ─
            bl_domain = [
                ("close_id.state", "=", "approved"),
                ("litre_difference", ">", 0),
            ]
            if df:
                bl_domain.append(("date", ">=", df))
            if dt:
                bl_domain.append(("date", "<=", dt))
            bl_result = BalanceLine.read_group(
                domain=bl_domain,
                fields=["litre_difference:sum", "loss_value:sum"],
                groupby=[],
            )
            rec.total_loss_litres = bl_result[0]["litre_difference"] if bl_result else 0.0
            rec.total_loss_value = bl_result[0]["loss_value"] if bl_result else 0.0

    @api.depends("date_from", "date_to")
    def _compute_receivables(self):
        for rec in self:
            df, dt = rec.date_from, rec.date_to

            def dt_start(d):
                return fields.Datetime.to_datetime(d) if d else None

            def dt_end(d):
                return fields.Datetime.to_datetime(d).replace(
                    hour=23, minute=59, second=59
                ) if d else None

            cs_domain = []
            if df:
                cs_domain.append(("date", ">=", dt_start(df)))
            if dt:
                cs_domain.append(("date", "<=", dt_end(dt)))
            cs_result = self.env["fuel.credit.sale"].read_group(
                domain=cs_domain,
                fields=["amount:sum"],
                groupby=[],
            )
            total_credit = cs_result[0]["amount"] if cs_result else 0.0

            cp_domain = []
            if df:
                cp_domain.append(("date", ">=", dt_start(df)))
            if dt:
                cp_domain.append(("date", "<=", dt_end(dt)))
            cp_result = self.env["fuel.credit.payment"].read_group(
                domain=cp_domain,
                fields=["amount_paid:sum"],
                groupby=[],
            )
            total_paid = cp_result[0]["amount_paid"] if cp_result else 0.0

            rec.total_receivables = max(total_credit - total_paid, 0.0)

    @api.depends("date_from", "date_to")
    def _compute_cash_collected(self):
        """Cash collected = sum of cash_deposited_in_safe across approved shift closes."""
        for rec in self:
            domain = [("state", "=", "approved")]
            if rec.date_from:
                domain.append(("date", ">=", rec.date_from))
            if rec.date_to:
                domain.append(("date", "<=", rec.date_to))
            result = self.env["fuel.station.shift.close"].read_group(
                domain=domain,
                fields=["cash_deposited_in_safe:sum"],
                groupby=[],
            )
            rec.total_cash_collected = result[0]["cash_deposited_in_safe"] if result else 0.0

    @api.depends("date_from", "date_to")
    def _compute_petty_cash_kpis(self):
        for rec in self:
            # Running petty cash balance — all-time, petty_cash source only
            replenishments = self.env["fuel.petty.cash.replenishment"].search([])
            posted_expenses = self.env["fuel.petty.cash.expense"].search([
                ("state", "=", "posted"),
                ("payment_source", "=", "petty_cash"),
            ])
            rec.petty_cash_balance = (
                sum(replenishments.mapped("amount"))
                - sum(posted_expenses.mapped("amount"))
            )

            # Period expenses — date-filtered, petty_cash source only
            exp_domain = [("state", "=", "posted"), ("payment_source", "=", "petty_cash")]
            if rec.date_from:
                exp_domain.append(("date", ">=", rec.date_from))
            if rec.date_to:
                exp_domain.append(("date", "<=", rec.date_to))
            exp_result = self.env["fuel.petty.cash.expense"].read_group(
                domain=exp_domain,
                fields=["amount:sum"],
                groupby=[],
            )
            rec.total_period_expenses = exp_result[0]["amount"] if exp_result else 0.0

    @api.depends("date_from", "date_to")
    def _compute_cash_variance(self):
        for rec in self:
            domain = [("state", "=", "approved")]
            if rec.date_from:
                domain.append(("date", ">=", rec.date_from))
            if rec.date_to:
                domain.append(("date", "<=", rec.date_to))
            result = self.env["fuel.station.shift.close"].read_group(
                domain=domain,
                fields=["safe_difference:sum"],
                groupby=[],
            )
            rec.total_safe_difference = result[0]["safe_difference"] if result else 0.0

    @api.depends("date_from", "date_to")
    def _compute_credit_collections(self):
        for rec in self:
            df, dt = rec.date_from, rec.date_to

            def dt_start(d):
                return fields.Datetime.to_datetime(d) if d else None

            def dt_end(d):
                return fields.Datetime.to_datetime(d).replace(
                    hour=23, minute=59, second=59
                ) if d else None

            cash_domain = [("payment_method", "=", "cash")]
            if df:
                cash_domain.append(("date", ">=", dt_start(df)))
            if dt:
                cash_domain.append(("date", "<=", dt_end(dt)))
            cash_result = self.env["fuel.credit.payment"].read_group(
                domain=cash_domain,
                fields=["amount_paid:sum"],
                groupby=[],
            )
            rec.total_cash_credit_received = cash_result[0]["amount_paid"] if cash_result else 0.0

            cheque_domain = [("payment_method", "=", "cheque")]
            if df:
                cheque_domain.append(("date", ">=", dt_start(df)))
            if dt:
                cheque_domain.append(("date", "<=", dt_end(dt)))
            cheque_result = self.env["fuel.credit.payment"].read_group(
                domain=cheque_domain,
                fields=["amount_paid:sum"],
                groupby=[],
            )
            rec.total_cheque_credit_received = cheque_result[0]["amount_paid"] if cheque_result else 0.0

    @api.depends_context('company')
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = self.env.company.currency_id

    # ------------------------------------------------------------------
    # Population helpers (called in create and refresh)
    # ------------------------------------------------------------------

    def _populate_tank_levels(self):
        """
        For every product marked is_fuel_product=True, display the live
        quantity on hand from Odoo's stock (stock.quant at internal locations).

        The 'last_close_date' is still pulled from the most recent approved
        shift-close balance line so operators can see when the last physical
        dip measurement was taken.
        """
        self.ensure_one()
        TankLine = self.env["fuel.dashboard.tank.level"]
        TankLine.search([("dashboard_id", "=", self.id)]).unlink()

        fuel_templates = self.env["product.template"].search([
            ("is_fuel_product", "=", True),
        ])
        if not fuel_templates:
            return

        # Map product_id → tank capacity from the template
        capacity_by_product: dict[int, float] = {}
        fuel_products = self.env["product.product"].browse()
        for tmpl in fuel_templates:
            product = tmpl.product_variant_ids[:1]
            if product:
                fuel_products |= product
                capacity_by_product[product.id] = tmpl.fuel_tank_capacity_liters or 0.0

        # ── Live stock quantity on hand (internal locations only) ─────────
        # Single read_group → one SQL query for all fuel products at once.
        quant_groups = self.env["stock.quant"].read_group(
            domain=[
                ("product_id", "in", fuel_products.ids),
                ("location_id.usage", "=", "internal"),
            ],
            fields=["product_id", "quantity:sum"],
            groupby=["product_id"],
        )
        qty_on_hand: dict[int, float] = {
            g["product_id"][0]: g["quantity"] for g in quant_groups
        }

        # ── Last physical dip date from balance lines (reference only) ────
        all_lines = self.env["fuel.station.fuel.balance.line"].search([
            ("product_id", "in", fuel_products.ids),
            ("close_id.state", "=", "approved"),
        ], order="date desc, id desc")
        latest_by_product: dict[int, object] = {}
        for line in all_lines:
            pid = line.product_id.id
            if pid not in latest_by_product:
                latest_by_product[pid] = line

        # Build all tank level lines and create in a single batch
        vals_list = []
        for product in fuel_products:
            current = max(qty_on_hand.get(product.id, 0.0), 0.0)
            capacity = capacity_by_product.get(product.id, 0.0)
            pct = round(min((current / capacity * 100), 100.0), 1) if capacity else 0.0
            fill_status = 'success' if pct >= 50 else ('warning' if pct >= 25 else 'danger')
            latest = latest_by_product.get(product.id)
            vals_list.append({
                "dashboard_id": self.id,
                "product_id": product.id,
                "current_level": current,
                "tank_capacity": capacity,
                "fill_percent": pct,
                "fill_status": fill_status,
                "last_close_date": latest.close_id.date if latest else False,
            })

        if vals_list:
            TankLine.create(vals_list)

        # Stamp refresh time and live alert counts
        self.last_refreshed = fields.Datetime.now()
        self.pending_session_count = self.env["fuel.attendant.session"].search_count(
            [("state", "=", "draft")]
        )
        self.unpaid_credit_count = self.env["fuel.credit.sale"].search_count(
            [("payment_state", "=", "unpaid")]
        )
        self.pending_delivery_count = self.env["fuel.delivery"].search_count(
            [("state", "=", "draft")]
        )

    def _populate_attendant_ranks(self):
        """
        Aggregate total sales by attendant across approved sessions in the
        selected period and keep the top 5.
        """
        self.ensure_one()
        RankLine = self.env["fuel.dashboard.attendant.rank"]
        RankLine.search([("dashboard_id", "=", self.id)]).unlink()

        domain = [("state", "=", "approved")]
        if self.date_from:
            domain.append(("date", ">=", self.date_from))
        if self.date_to:
            domain.append(("date", "<=", self.date_to))

        # search_read fetches only the columns we need — avoids loading full records.
        sessions = self.env["fuel.attendant.session"].search_read(
            domain, ["attendant_id", "total_sales"]
        )
        if not sessions:
            return

        session_ids = [s["id"] for s in sessions]

        # Single read_group for litres per session — avoids N+1 on line_ids
        line_groups = self.env["fuel.attendant.session.line"].read_group(
            domain=[("session_id", "in", session_ids)],
            fields=["session_id", "litres_sold:sum"],
            groupby=["session_id"],
        )
        litres_by_session: dict[int, float] = {
            g["session_id"][0]: g["litres_sold"] for g in line_groups
        }

        totals: dict[int, dict] = {}
        for s in sessions:
            aid = s["attendant_id"][0] if s["attendant_id"] else None
            if not aid:
                continue
            if aid not in totals:
                totals[aid] = {
                    "attendant_id": aid,
                    "total_sales": 0.0,
                    "litres_sold": 0.0,
                    "sessions": 0,
                }
            totals[aid]["total_sales"] += s["total_sales"] or 0.0
            totals[aid]["litres_sold"] += litres_by_session.get(s["id"], 0.0)
            totals[aid]["sessions"] += 1

        top5 = sorted(totals.values(), key=lambda x: x["total_sales"], reverse=True)[:5]
        grand_total = sum(d["total_sales"] for d in totals.values())
        medals = {1: '🥇', 2: '🥈', 3: '🥉'}

        vals_list = []
        for rank, data in enumerate(top5, 1):
            pct = round(data["total_sales"] / grand_total * 100, 1) if grand_total else 0.0
            vals_list.append({
                "dashboard_id": self.id,
                "rank": rank,
                "rank_label": medals.get(rank, str(rank)),
                "attendant_id": data["attendant_id"],
                "total_sales": data["total_sales"],
                "litres_sold": data["litres_sold"],
                "session_count": data["sessions"],
                "pct_of_total": pct,
            })
        if vals_list:
            RankLine.create(vals_list)

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _reload_action(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Fuel Station Dashboard",
            "res_model": "fuel.dashboard",
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref("fuel_station.view_fuel_dashboard_form").id,
            "target": "main",
            "context": {"form_view_initial_mode": "readonly"},
        }

    # ------------------------------------------------------------------
    # Quick period preset actions
    # ------------------------------------------------------------------

    def action_set_today(self):
        self.ensure_one()
        today = fields.Date.today()
        self.write({"date_from": today, "date_to": today})
        return self._reload_action()

    def action_set_this_week(self):
        self.ensure_one()
        today = date_type.today()
        start = today - timedelta(days=today.weekday())
        self.write({"date_from": start, "date_to": today})
        return self._reload_action()

    def action_set_this_month(self):
        self.ensure_one()
        today = date_type.today()
        self.write({"date_from": today.replace(day=1), "date_to": today})
        return self._reload_action()

    def action_set_last_month(self):
        self.ensure_one()
        today = date_type.today()
        first_this = today.replace(day=1)
        last_end = first_this - timedelta(days=1)
        last_start = last_end.replace(day=1)
        self.write({"date_from": last_start, "date_to": last_end})
        return self._reload_action()

    # ------------------------------------------------------------------
    # Drill-through actions
    # ------------------------------------------------------------------

    def action_open_credit_sales_period(self):
        self.ensure_one()
        domain = [("session_id.state", "=", "approved")]
        if self.date_from:
            domain.append(("date", ">=", fields.Datetime.to_datetime(self.date_from)))
        if self.date_to:
            domain.append(("date", "<=", fields.Datetime.to_datetime(self.date_to).replace(
                hour=23, minute=59, second=59
            )))
        return {
            "type": "ir.actions.act_window",
            "name": "Credit Sales",
            "res_model": "fuel.credit.sale",
            "view_mode": "list,form",
            "domain": domain,
        }

    def action_open_unpaid_credits(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Unpaid Credit Sales",
            "res_model": "fuel.credit.sale",
            "view_mode": "list,form",
            "domain": [("payment_state", "=", "unpaid")],
        }

    def action_open_pending_sessions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Draft Sessions",
            "res_model": "fuel.attendant.session",
            "view_mode": "list,form",
            "domain": [("state", "=", "draft")],
        }

    def action_open_petty_cash_deposits(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Petty Cash Deposits",
            "res_model": "fuel.petty.cash.replenishment",
            "view_mode": "list,form",
            "domain": [],
        }

    def action_open_period_expenses(self):
        self.ensure_one()
        domain = [("state", "=", "posted")]
        if self.date_from:
            domain.append(("date", ">=", self.date_from))
        if self.date_to:
            domain.append(("date", "<=", self.date_to))
        return {
            "type": "ir.actions.act_window",
            "name": "Cash Expenses",
            "res_model": "fuel.petty.cash.expense",
            "view_mode": "list,form",
            "domain": domain,
        }

    def action_open_pending_deliveries(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Draft Deliveries",
            "res_model": "fuel.delivery",
            "view_mode": "list,form",
            "domain": [("state", "=", "draft")],
        }

    def action_open_cash_credit_payments(self):
        self.ensure_one()
        domain = [("payment_method", "=", "cash")]
        if self.date_from:
            domain.append(("date", ">=", fields.Datetime.to_datetime(self.date_from)))
        if self.date_to:
            domain.append(("date", "<=", fields.Datetime.to_datetime(self.date_to).replace(
                hour=23, minute=59, second=59
            )))
        return {
            "type": "ir.actions.act_window",
            "name": "Cash Credit Payments",
            "res_model": "fuel.credit.payment",
            "view_mode": "list,pivot,form",
            "domain": domain,
        }

    def action_open_cheque_credit_payments(self):
        self.ensure_one()
        domain = [("payment_method", "=", "cheque")]
        if self.date_from:
            domain.append(("date", ">=", fields.Datetime.to_datetime(self.date_from)))
        if self.date_to:
            domain.append(("date", "<=", fields.Datetime.to_datetime(self.date_to).replace(
                hour=23, minute=59, second=59
            )))
        return {
            "type": "ir.actions.act_window",
            "name": "Cheque Credit Payments",
            "res_model": "fuel.credit.payment",
            "view_mode": "list,pivot,form",
            "domain": domain,
        }

    # ------------------------------------------------------------------
    # Entry point actions
    # ------------------------------------------------------------------

    @api.model
    def action_open(self):
        """Entry point called by the server action / menu item."""
        record = self.create({})
        return {
            "type": "ir.actions.act_window",
            "name": "Fuel Station Dashboard",
            "res_model": "fuel.dashboard",
            "res_id": record.id,
            "view_mode": "form",
            "view_id": self.env.ref("fuel_station.view_fuel_dashboard_form").id,
            "target": "main",
            "context": {"form_view_initial_mode": "readonly"},
        }

    def action_refresh(self):
        """Refresh all sub-lines and recompute for the current period."""
        self.ensure_one()
        self._populate_tank_levels()
        self._populate_attendant_ranks()
        self.invalidate_recordset()
        return self._reload_action()


# ---------------------------------------------------------------------------
# Tank level line
# ---------------------------------------------------------------------------

class FuelDashboardTankLevel(models.TransientModel):
    _name = "fuel.dashboard.tank.level"
    _description = "Dashboard — Tank Level Line"
    _order = "product_id"

    dashboard_id = fields.Many2one("fuel.dashboard", ondelete="cascade", required=True)
    product_id = fields.Many2one("product.product", string="Fuel Type", readonly=True)
    current_level = fields.Float(string="Current Level (L)", digits=(16, 2), readonly=True)
    tank_capacity = fields.Float(string="Capacity (L)", digits=(16, 2), readonly=True)
    fill_percent = fields.Float(string="Fill %", digits=(5, 1), readonly=True)
    fill_status = fields.Char(string="Status", readonly=True)  # 'success' | 'warning' | 'danger'
    last_close_date = fields.Date(string="Last Dip", readonly=True)


# ---------------------------------------------------------------------------
# Attendant ranking line
# ---------------------------------------------------------------------------

class FuelDashboardAttendantRank(models.TransientModel):
    _name = "fuel.dashboard.attendant.rank"
    _description = "Dashboard — Attendant Ranking Line"
    _order = "rank"

    dashboard_id = fields.Many2one("fuel.dashboard", ondelete="cascade", required=True)
    rank = fields.Integer(string="#", readonly=True)
    rank_label = fields.Char(string="Rank", readonly=True)
    attendant_id = fields.Many2one("fuel.attendant", string="Attendant", readonly=True)
    total_sales = fields.Float(string="Sales Amount", digits=(16, 2), readonly=True)
    litres_sold = fields.Float(string="Litres Sold", digits=(16, 2), readonly=True)
    session_count = fields.Integer(string="Sessions", readonly=True)
    pct_of_total = fields.Float(string="Share %", digits=(5, 1), readonly=True)
