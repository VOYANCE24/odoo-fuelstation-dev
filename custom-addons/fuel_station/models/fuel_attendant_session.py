from odoo import fields, models, api
from odoo.exceptions import ValidationError


class FuelAttendantSession(models.Model):
    _name = "fuel.attendant.session"
    _description = "Attendant Shift Session (Closing)"
    _order = "date desc, id desc"


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
    payout_ids = fields.One2many(
        "fuel.payout", "session_id", string="Payouts"
    )
    credit_payment_ids = fields.One2many(
        "fuel.credit.payment", "session_id", string="Credit Payments"
    )

    # Linked accounting documents
    move_id = fields.Many2one(
        "account.move",
        string="Cash Receipt Invoice",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    shortage_move_id = fields.Many2one(
        "account.move",
        string="Shortage Invoice",
        readonly=True,
        copy=False,
        ondelete="set null",
    )

    note = fields.Text(string="Notes")

    # Linked stock delivery (fuel dispensed → reduces inventory)
    picking_id = fields.Many2one(
        "stock.picking",
        string="Delivery",
        readonly=True,
        copy=False,
        ondelete="set null",
    )

    total_sales = fields.Float(compute="_compute_totals", store=True)
    total_credit_sales = fields.Float(compute="_compute_totals", store=True)
    total_cash_sales = fields.Float(compute="_compute_totals", store=True, string="Cash Sales")
    total_payouts = fields.Float(compute="_compute_totals", store=True, string="Total Payouts")
    total_cash_credit_payments = fields.Float(
        compute="_compute_totals", store=True, string="Cash Credit Payments"
    )
    total_cheque_credit_payments = fields.Float(
        compute="_compute_totals", store=True, string="Cheque Credit Payments"
    )
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
    credit_payment_count = fields.Integer(compute='_compute_counts')

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("fuel.attendant.session")
                    or "AS/"
                )
        return super().create(vals_list)

    def unlink(self):
        """
        Only draft sessions can be deleted.
        Approved sessions must be reset to draft first (which reverses all
        accounting and stock documents) before they can be removed.
        """
        for session in self:
            if session.state == "approved":
                raise ValidationError(
                    f"Cannot delete approved session '{session.name}'. "
                    "Click 'Reset to Draft' to reverse all accounting entries "
                    "and stock moves before deleting."
                )
        return super().unlink()

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    @api.depends(
        "line_ids.total",
        "credit_sale_ids.amount",
        "cash_deposit_ids.amount",
        "payout_ids.amount",
        "credit_payment_ids.amount_paid",
        "credit_payment_ids.payment_method",
    )
    def _compute_totals(self):
        for session in self:
            session.total_sales = sum(session.line_ids.mapped("total"))
            session.total_credit_sales = sum(session.credit_sale_ids.mapped("amount"))
            session.total_cash_sales = session.total_sales - session.total_credit_sales
            session.total_payouts = sum(session.payout_ids.mapped("amount"))
            cash_payments = session.credit_payment_ids.filtered(
                lambda p: p.payment_method == "cash"
            )
            cheque_payments = session.credit_payment_ids.filtered(
                lambda p: p.payment_method == "cheque"
            )
            session.total_cash_credit_payments = sum(cash_payments.mapped("amount_paid"))
            session.total_cheque_credit_payments = sum(cheque_payments.mapped("amount_paid"))
            session.expected_cash = (
                session.total_sales
                - session.total_credit_sales
                - session.total_payouts
                + session.total_cash_credit_payments
            )
            session.total_cash_deposited = sum(session.cash_deposit_ids.mapped("amount"))
            session.cash_difference = (
                session.total_cash_deposited - session.expected_cash
            )

    @api.depends_context('company')
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = self.env.company.currency_id

    @api.depends('credit_sale_ids', 'cash_deposit_ids', 'credit_payment_ids')
    def _compute_counts(self):
        for rec in self:
            rec.credit_sale_count = len(rec.credit_sale_ids)
            rec.cash_deposit_count = len(rec.cash_deposit_ids)
            rec.credit_payment_count = len(rec.credit_payment_ids)

    # ------------------------------------------------------------------
    # Helpers — lookups
    # ------------------------------------------------------------------

    def _shift_window_domain(self):
        self.ensure_one()
        start_utc, end_utc = self.shift_id.get_window(self.date)
        return [
            ("date", ">=", fields.Datetime.to_string(start_utc)),
            ("date", "<", fields.Datetime.to_string(end_utc)),
        ]

    def _get_income_account(self):
        """Return the first active income account for generic invoice lines."""
        return self.env["account.account"].search([
            ("account_type", "in", ["income", "income_other"]),
        ], limit=1)

    def _get_cash_sales_partner(self):
        """Return the 'Cash Sales' partner, creating it on first use."""
        Partner = self.env["res.partner"].sudo()
        partner = Partner.search([("name", "=", "Cash Sales")], limit=1)
        if not partner:
            partner = Partner.create({
                "name": "Cash Sales",
                "customer_rank": 1,
                "is_company": False,
            })
        return partner

    # ------------------------------------------------------------------
    # Helpers — invoice building
    # ------------------------------------------------------------------

    def _build_cash_receipt_lines(self):
        """
        Build invoice_line_ids vals for the cash receipt invoice.

        The cash receipt invoice must equal the cash actually deposited
        (total_cash_deposited), so that no income account is ever debited.

        Strategy
        --------
        1. Compute expected cash per product
               = (session litres − credit litres) × price
        2. Determine a distribution ratio:
               ratio = cash_deposited / total_expected_cash   (shortage case)
               ratio = 1.0                                    (exact / overage)
        3. Each product line = expected_value × ratio
               → when shortage: lines sum to cash_deposited  (no negative line)
               → when exact:    lines sum to expected_cash
        4. For overage: add a separate 'Product Overage' line.
               → lines still sum to cash_deposited

        This ensures the invoice total always equals cash_deposited, and
        income accounts only receive clean credits — no debits from adjustments.
        """
        self.ensure_one()

        # --- aggregate session pump lines by product ---
        session_by_product = {}
        for sl in self.line_ids:
            if (sl.litres_sold or 0.0) <= 0:
                continue
            pid = sl.product_id.id or 0
            if pid not in session_by_product:
                session_by_product[pid] = {
                    "value": 0.0,
                    "litres": 0.0,
                    "name": sl.product_id.name or "Fuel",
                    "product_id": sl.product_id.id or False,
                }
            session_by_product[pid]["value"] += sl.total
            session_by_product[pid]["litres"] += sl.litres_sold

        # --- aggregate credit sales by product (iterate lines) ---
        credit_by_product = {}
        for cs in self.credit_sale_ids:
            for ln in cs.line_ids:
                pid = ln.product_id.id or 0
                if pid not in credit_by_product:
                    credit_by_product[pid] = {"value": 0.0, "litres": 0.0}
                credit_by_product[pid]["value"] += ln.amount
                credit_by_product[pid]["litres"] += ln.litres

        # --- compute expected cash per product ---
        cash_by_product = {}
        total_expected_cash = 0.0
        for pid, sess in session_by_product.items():
            cred = credit_by_product.get(pid, {"value": 0.0, "litres": 0.0})
            exp_value = max(sess["value"] - cred["value"], 0.0)
            cash_litres = max(sess["litres"] - cred["litres"], 0.0)
            if exp_value > 0 and cash_litres > 0:
                cash_by_product[pid] = {
                    "expected_value": exp_value,
                    "cash_litres": cash_litres,
                    "name": sess["name"],
                    "product_id": sess["product_id"],
                }
                total_expected_cash += exp_value

        # --- determine distribution ratio ---
        cash_diff = self.cash_difference          # negative = shortage
        cash_deposited = max(self.total_cash_deposited, 0.0)

        if cash_diff < 0 and total_expected_cash > 0:
            # Shortage: scale each product line down proportionally so the
            # invoice total = cash_deposited.  No negative line needed.
            ratio = cash_deposited / total_expected_cash
        else:
            # Exact match or overage: use full expected cash per product.
            ratio = 1.0

        # --- build one line per product ---
        lines = []
        for pid, data in cash_by_product.items():
            actual_value = data["expected_value"] * ratio
            price = actual_value / data["cash_litres"]
            line = {
                "name": data["name"],
                "quantity": data["cash_litres"],
                "price_unit": price,
            }
            if data["product_id"]:
                line["product_id"] = data["product_id"]
            lines.append((0, 0, line))

        # --- overage line (ratio = 1.0, product lines = expected cash) ---
        if cash_diff > 0:
            ov = {
                "name": "Product Overage",
                "quantity": 1.0,
                "price_unit": cash_diff,
            }
            acc = self._get_income_account()
            if acc:
                ov["account_id"] = acc.id
            lines.append((0, 0, ov))

        return lines

    # ------------------------------------------------------------------
    # Helpers — document creation
    # ------------------------------------------------------------------

    def _create_cash_receipt_invoice(self):
        """
        Create and post the cash receipt invoice.
        Invoice total = cash_deposited (proportional product lines, no negatives).
        """
        self.ensure_one()
        lines = self._build_cash_receipt_lines()
        if not lines:
            return None

        move = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self._get_cash_sales_partner().id,
            "invoice_date": self.date,
            "ref": self.name,
            "narration": (
                f"Cash sales — {self.attendant_id.name} ({self.shift_id.name})\n"
                f"Note: unit prices reflect actual cash collected, not pump price."
            ),
            "invoice_line_ids": lines,
        })
        move.action_post()
        return move

    def _clear_invoice(self, move):
        """
        Register an inbound payment equal to the invoice total and reconcile
        it so the invoice shows as Paid/Cleared.
        """
        journal = self.env["account.journal"].search([
            ("type", "in", ["cash", "bank"]),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        if not journal:
            return

        payment = self.env["account.payment"].create({
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": move.partner_id.id,
            "amount": move.amount_total,
            "journal_id": journal.id,
            "date": self.date,
            "memo": f"Auto-clear: {self.name}",
        })
        payment.action_post()

        inv_line = move.line_ids.filtered(
            lambda l: l.account_id.account_type == "asset_receivable"
        )
        pay_line = payment.move_id.line_ids.filtered(
            lambda l: l.account_id.account_type == "asset_receivable"
        )
        if inv_line and pay_line:
            (inv_line + pay_line).reconcile()

    def _create_credit_invoices(self):
        """
        Create one customer invoice per credit sale (one line per sale line).
        Posted but left unpaid. Updates move_id and invoice_ref on each record.
        """
        self.ensure_one()
        product_name = {}
        for cs in self.credit_sale_ids:
            if cs.move_id or not cs.line_ids:
                continue
            invoice_lines = []
            for ln in cs.line_ids:
                if not ln.litres:
                    continue
                pid = ln.product_id.id if ln.product_id else None
                pname = product_name.get(pid) or (
                    ln.product_id.name if ln.product_id else "Fuel (Credit Sale)"
                )
                if pid:
                    product_name[pid] = pname
                desc = pname
                if ln.vehicle_plate:
                    desc = f"{pname} — {ln.vehicle_plate}"
                lv = {
                    "name": desc,
                    "quantity": ln.litres,
                    "price_unit": ln.price,
                }
                if pid:
                    lv["product_id"] = pid
                invoice_lines.append((0, 0, lv))

            if not invoice_lines:
                continue

            move = self.env["account.move"].create({
                "move_type": "out_invoice",
                "partner_id": cs.customer_id.id,
                "invoice_date": self.date,
                "ref": cs.name,
                "narration": (
                    f"Credit sale — {cs.customer_id.name} — "
                    f"{self.attendant_id.name} ({self.shift_id.name})"
                ),
                "invoice_line_ids": invoice_lines,
            })
            move.action_post()
            cs.write({"move_id": move.id, "invoice_ref": move.name})

    def _create_shortage_invoice(self, amount):
        """
        Create and post an invoice to the attendant for the cash shortage.
        Left unpaid — sits as open AR on the attendant's account.
        """
        self.ensure_one()
        shortage_vals = {
            "name": f"Cash Shortage — {self.name}",
            "quantity": 1.0,
            "price_unit": amount,
        }
        acc = self._get_income_account()
        if acc:
            shortage_vals["account_id"] = acc.id

        move = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.attendant_id.partner_id.id,
            "invoice_date": self.date,
            "ref": f"SHORTAGE/{self.name}",
            "narration": (
                f"Cash shortage — {self.attendant_id.name} ({self.shift_id.name})"
            ),
            "invoice_line_ids": [(0, 0, shortage_vals)],
        })
        move.action_post()
        return move

    def _create_stock_dispensing(self):
        """
        Create and validate a delivery (stock.picking) reducing inventory
        by the total litres dispensed across ALL session lines.
        This runs for every product, regardless of cash vs credit split —
        physical fuel left the tank in full.
        Returns the picking or None.
        """
        self.ensure_one()

        # Aggregate total litres dispensed per product
        litres_by_product = {}
        for sl in self.line_ids:
            if (sl.litres_sold or 0.0) <= 0 or not sl.product_id:
                continue
            pid = sl.product_id.id
            litres_by_product[pid] = litres_by_product.get(pid, 0.0) + sl.litres_sold

        if not litres_by_product:
            return None

        # Delivery operation type for this company
        picking_type = self.env["stock.picking.type"].search([
            ("code", "=", "outgoing"),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        if not picking_type:
            return None

        src_location = picking_type.default_location_src_id
        dest_location = self.env.ref(
            "stock.stock_location_customers", raise_if_not_found=False
        ) or self.env["stock.location"].search(
            [("usage", "=", "customer")], limit=1
        )
        if not src_location or not dest_location:
            return None

        move_vals = []
        for pid, litres in litres_by_product.items():
            product = self.env["product.product"].browse(pid)
            move_vals.append((0, 0, {
                "description_picking": product.display_name,
                "product_id": pid,
                "product_uom": product.uom_id.id,
                "product_uom_qty": litres,
                "location_id": src_location.id,
                "location_dest_id": dest_location.id,
            }))

        picking = self.env["stock.picking"].create({
            "picking_type_id": picking_type.id,
            "location_id": src_location.id,
            "location_dest_id": dest_location.id,
            "scheduled_date": fields.Datetime.now(),
            "origin": self.name,
            "move_ids": move_vals,
        })

        picking.action_confirm()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
        picking.with_context(skip_backorder=True).button_validate()
        return picking

    def _reverse_stock_dispensing(self, picking):
        """
        Create a return picking to restore inventory from a done delivery.
        For non-done pickings simply cancel and delete.
        """
        if not picking:
            return
        if picking.state == "done":
            return_type = (
                picking.picking_type_id.return_picking_type_id
                or picking.picking_type_id
            )
            done_moves = picking.move_ids.filtered(lambda m: m.state == "done")
            if not done_moves:
                return
            return_picking = self.env["stock.picking"].create({
                "picking_type_id": return_type.id,
                "location_id": picking.location_dest_id.id,
                "location_dest_id": picking.location_id.id,
                "origin": f"Return: {picking.name}",
                "move_ids": [(0, 0, {
                    "description_picking": f"Return: {move.description_picking or move.product_id.display_name}",
                    "product_id": move.product_id.id,
                    "product_uom": move.product_uom.id,
                    "product_uom_qty": move.quantity,
                    "location_id": picking.location_dest_id.id,
                    "location_dest_id": picking.location_id.id,
                    "origin_returned_move_id": move.id,
                }) for move in done_moves],
            })
            return_picking.action_confirm()
            for move in return_picking.move_ids:
                move.quantity = move.product_uom_qty
            return_picking.with_context(skip_backorder=True).button_validate()
        elif picking.state != "cancel":
            picking.action_cancel()
            picking.unlink()
        elif picking.state == "cancel":
            picking.unlink()

    def _cancel_invoice(self, move):
        """Cancel and delete a single account.move with any linked payments."""
        if not move or not move.exists():
            return
        if move.state == "posted":
            payments = self.env["account.payment"].search([
                ("reconciled_invoice_ids", "in", [move.id]),
            ])
            for payment in payments:
                if payment.state != "draft":
                    payment.action_draft()
                payment.unlink()
            move.button_draft()
        move.unlink()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_populate_shift_transactions(self):
        """Pull unlinked credit sales, cash deposits, payouts, and credit payments for this attendant/shift."""
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

            payouts = self.env["fuel.payout"].search(base_domain)
            payouts.write({"session_id": session.id})

            payments = self.env["fuel.credit.payment"].search(base_domain)
            payments.write({"session_id": session.id})

    def action_approve(self):
        for session in self:
            if session.state != "draft":
                continue
            if not session.line_ids:
                raise ValidationError(
                    "Add at least one sales line before approving the session."
                )
            shortage = session.cash_difference
            if shortage < 0 and not session.attendant_id.partner_id:
                raise ValidationError(
                    f"Attendant '{session.attendant_id.name}' has no partner set. "
                    "Open the attendant record and set a Partner before approving "
                    "a session that has a cash shortage."
                )

            session.write({
                "state": "approved",
                "approver_id": self.env.user.id,
                "approved_at": fields.Datetime.now(),
            })

            # 1. Cash receipt invoice (proportional, auto-cleared = Paid)
            cash_move = session._create_cash_receipt_invoice()
            if cash_move:
                session._clear_invoice(cash_move)
                session.move_id = cash_move.id

            # 2. Credit sale invoices (one per credit sale, unpaid/open AR)
            session._create_credit_invoices()

            # 3. Shortage invoice to attendant (only if shortage)
            if shortage < 0:
                shortage_move = session._create_shortage_invoice(abs(shortage))
                if shortage_move:
                    session.shortage_move_id = shortage_move.id

            # 4. Stock dispensing delivery (reduces inventory for all litres sold)
            picking = session._create_stock_dispensing()
            if picking:
                session.picking_id = picking.id

            # 5. Create payout expenses (one per payout)
            session._create_payout_expenses()

    def action_reset_to_draft(self):
        """
        Reverse all documents linked to this session and reset to Draft.
        Managers only. This allows the session to be corrected or deleted.
        """
        for session in self:
            if session.state != "approved":
                continue

            # 1. Reverse stock delivery
            if session.picking_id:
                session._reverse_stock_dispensing(session.picking_id)

            # 2. Cancel credit sale invoices
            for cs in session.credit_sale_ids:
                if cs.move_id:
                    move = cs.move_id
                    cs.write({"move_id": False, "invoice_ref": False})
                    session._cancel_invoice(move)

            # 3. Cancel session-level invoices
            for move in filter(None, [session.move_id, session.shortage_move_id]):
                session._cancel_invoice(move)

            # 4. Cancel payout expenses
            for payout in session.payout_ids:
                if payout.expense_id:
                    exp = payout.expense_id
                    if exp.state == "posted":
                        exp.action_reset_to_draft()
                    payout.expense_id = False
                    payout.state = "draft"

            session.write({
                "state": "draft",
                "approver_id": False,
                "approved_at": False,
                "move_id": False,
                "shortage_move_id": False,
                "picking_id": False,
            })

    def _create_payout_expenses(self):
        """Create and auto-post a petty cash expense for each payout on this session."""
        self.ensure_one()
        for payout in self.payout_ids:
            if payout.expense_id:
                continue
            if not payout.line_ids:
                continue
            expense_lines = [
                (0, 0, {
                    "category_id": line.category_id.id,
                    "description": line.description,
                    "qty": line.qty,
                    "rate": line.rate,
                })
                for line in payout.line_ids
            ]
            expense = self.env["fuel.petty.cash.expense"].create({
                "date": fields.Date.to_date(payout.date) if payout.date else self.date,
                "payment_source": "session_payout",
                "payout_id": payout.id,
                "shift_id": payout.shift_id.id,
                "vendor_id": payout.paid_to.id if payout.paid_to else False,
                "paid_by": self.env.user.id,
                "line_ids": expense_lines,
            })
            # action_post skips balance check for session_payout source
            expense.action_post()
            payout.expense_id = expense.id
            payout.state = "expensed"

    def action_view_invoice(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": self.move_id.id,
        }

    def action_view_shortage_invoice(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": self.shortage_move_id.id,
        }

    def action_view_delivery(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "view_mode": "form",
            "res_id": self.picking_id.id,
        }

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

    def action_open_credit_payments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Credit Payments',
            'res_model': 'fuel.credit.payment',
            'view_mode': 'list,form',
            'domain': [('session_id', '=', self.id)],
            'context': {
                'default_session_id': self.id,
                'default_shift_id': self.shift_id.id,
                'default_attendant_id': self.attendant_id.id,
            },
        }
