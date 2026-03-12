from odoo import fields, models, api


class FuelAttendant(models.Model):
    _name = "fuel.attendant"
    _description = "Pump Attendant"
    _order = "name"

    name = fields.Char(required=True)
    employee_id = fields.Many2one("hr.employee")
    partner_id = fields.Many2one(
        "res.partner",
        string="Partner",
        help=(
            "Billing partner used when creating shortage invoices. "
            "Required whenever an approved session has a cash shortage."
        ),
    )
    active = fields.Boolean(default=True)

    # Shortage tracking (always fresh — not stored)
    shortage_invoice_count = fields.Integer(
        compute="_compute_shortage_stats",
        string="Open Shortages",
    )
    total_outstanding_shortage = fields.Float(
        compute="_compute_shortage_stats",
        string="Total Owed",
    )
    currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_currency_id",
    )

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    @api.depends()
    def _compute_shortage_stats(self):
        for att in self:
            if not att.id:
                att.shortage_invoice_count = 0
                att.total_outstanding_shortage = 0.0
                continue
            sessions = self.env["fuel.attendant.session"].search([
                ("attendant_id", "=", att.id),
                ("shortage_move_id", "!=", False),
            ])
            open_moves = sessions.mapped("shortage_move_id").filtered(
                lambda m: m.state == "posted"
                and m.payment_state not in ("paid", "in_payment", "reversed")
            )
            att.shortage_invoice_count = len(open_moves)
            att.total_outstanding_shortage = sum(open_moves.mapped("amount_residual"))

    @api.depends_context("company")
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = self.env.company.currency_id

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_view_shortage_invoices(self):
        self.ensure_one()
        sessions = self.env["fuel.attendant.session"].search([
            ("attendant_id", "=", self.id),
            ("shortage_move_id", "!=", False),
        ])
        return {
            "type": "ir.actions.act_window",
            "name": f"Shortage Invoices — {self.name}",
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", sessions.mapped("shortage_move_id").ids)],
        }
