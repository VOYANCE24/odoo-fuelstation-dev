from odoo import fields, models, api
from datetime import date as date_type
from dateutil.relativedelta import relativedelta


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
        string="Cash Credit Collected",
        compute="_compute_receivables",
        digits=(16, 2),
    )

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

    # ------------------------------------------------------------------
    # Compute — KPIs
    # ------------------------------------------------------------------

    @api.depends("date_from", "date_to")
    def _compute_kpis(self):
        SessionLine = self.env["fuel.attendant.session.line"]
        BalanceLine = self.env["fuel.station.fuel.balance.line"]

        for rec in self:
            df, dt = rec.date_from, rec.date_to

            # Approved session sales lines in the period
            sl_domain = [("session_id.state", "=", "approved")]
            if df:
                sl_domain.append(("date", ">=", df))
            if dt:
                sl_domain.append(("date", "<=", dt))
            session_lines = SessionLine.search(sl_domain)
            rec.total_litres_sold = sum(session_lines.mapped("litres_sold"))
            rec.total_revenue = sum(session_lines.mapped("total"))

            # Credit sales in the period (approved sessions)
            cs_domain = [("session_id.state", "=", "approved")]
            if df:
                cs_domain.append(("date", ">=", fields.Datetime.to_datetime(df)))
            if dt:
                cs_domain.append(("date", "<=", fields.Datetime.to_datetime(dt).replace(
                    hour=23, minute=59, second=59
                )))
            credit_sales = self.env["fuel.credit.sale"].search(cs_domain)
            rec.total_credit_sales = sum(credit_sales.mapped("amount"))

            # Variance / loss from approved shift closes
            bl_domain = [("close_id.state", "=", "approved")]
            if df:
                bl_domain.append(("date", ">=", df))
            if dt:
                bl_domain.append(("date", "<=", dt))
            balance_lines = BalanceLine.search(bl_domain)
            # litre_difference > 0 means loss (expected outflow > actual pump sales)
            loss_lines = balance_lines.filtered(lambda l: l.litre_difference > 0)
            rec.total_loss_litres = sum(loss_lines.mapped("litre_difference"))
            rec.total_loss_value = sum(loss_lines.mapped("loss_value"))

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
            total_credit = sum(
                self.env["fuel.credit.sale"].search(cs_domain).mapped("amount")
            )

            cp_domain = []
            if df:
                cp_domain.append(("date", ">=", dt_start(df)))
            if dt:
                cp_domain.append(("date", "<=", dt_end(dt)))
            payments = self.env["fuel.credit.payment"].search(cp_domain)
            total_paid = sum(payments.mapped("amount_paid"))
            cash_paid = sum(
                payments.filtered(lambda p: p.payment_method == "cash").mapped("amount_paid")
            )

            rec.total_receivables = max(total_credit - total_paid, 0.0)
            rec.total_cash_collected = cash_paid

    # ------------------------------------------------------------------
    # Population helpers (called in create and refresh)
    # ------------------------------------------------------------------

    def _populate_tank_levels(self):
        """
        For every product marked is_fuel_product=True, find the most recent
        approved shift-close balance line and read its closing_litres as the
        current tank level.
        """
        self.ensure_one()
        TankLine = self.env["fuel.dashboard.tank.level"]
        # Clear any existing lines (for refresh)
        TankLine.search([("dashboard_id", "=", self.id)]).unlink()

        fuel_templates = self.env["product.template"].search([
            ("is_fuel_product", "=", True),
        ])
        for tmpl in fuel_templates:
            product = tmpl.product_variant_ids[:1]
            if not product:
                continue

            latest = self.env["fuel.station.fuel.balance.line"].search([
                ("product_id", "=", product.id),
                ("close_id.state", "=", "approved"),
            ], order="date desc, id desc", limit=1)

            current = latest.closing_litres if latest else 0.0
            capacity = tmpl.fuel_tank_capacity_liters or 0.0
            pct = round(min((current / capacity * 100), 100.0), 1) if capacity else 0.0

            TankLine.create({
                "dashboard_id": self.id,
                "product_id": product.id,
                "current_level": current,
                "tank_capacity": capacity,
                "fill_percent": pct,
                "last_close_date": latest.close_id.date if latest else False,
            })

    def _populate_attendant_ranks(self):
        """
        Aggregate total sales by attendant across approved sessions in the
        selected period and keep the top 4.
        """
        self.ensure_one()
        RankLine = self.env["fuel.dashboard.attendant.rank"]
        RankLine.search([("dashboard_id", "=", self.id)]).unlink()

        domain = [("state", "=", "approved")]
        if self.date_from:
            domain.append(("date", ">=", self.date_from))
        if self.date_to:
            domain.append(("date", "<=", self.date_to))

        sessions = self.env["fuel.attendant.session"].search(domain)

        totals: dict[int, dict] = {}
        for s in sessions:
            aid = s.attendant_id.id
            if aid not in totals:
                totals[aid] = {
                    "attendant_id": aid,
                    "total_sales": 0.0,
                    "litres_sold": 0.0,
                    "sessions": 0,
                }
            totals[aid]["total_sales"] += s.total_sales
            totals[aid]["litres_sold"] += sum(s.line_ids.mapped("litres_sold"))
            totals[aid]["sessions"] += 1

        top4 = sorted(totals.values(), key=lambda x: x["total_sales"], reverse=True)[:4]

        for rank, data in enumerate(top4, 1):
            RankLine.create({
                "dashboard_id": self.id,
                "rank": rank,
                "attendant_id": data["attendant_id"],
                "total_sales": data["total_sales"],
                "litres_sold": data["litres_sold"],
                "session_count": data["sessions"],
            })

    # ------------------------------------------------------------------
    # Actions
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
        # Invalidate computed KPI fields
        self.invalidate_recordset()
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
    last_close_date = fields.Date(string="As of", readonly=True)


# ---------------------------------------------------------------------------
# Attendant ranking line
# ---------------------------------------------------------------------------

class FuelDashboardAttendantRank(models.TransientModel):
    _name = "fuel.dashboard.attendant.rank"
    _description = "Dashboard — Attendant Ranking Line"
    _order = "rank"

    dashboard_id = fields.Many2one("fuel.dashboard", ondelete="cascade", required=True)
    rank = fields.Integer(string="#", readonly=True)
    attendant_id = fields.Many2one("fuel.attendant", string="Attendant", readonly=True)
    total_sales = fields.Float(string="Sales Amount", digits=(16, 2), readonly=True)
    litres_sold = fields.Float(string="Litres Sold", digits=(16, 2), readonly=True)
    session_count = fields.Integer(string="Sessions", readonly=True)