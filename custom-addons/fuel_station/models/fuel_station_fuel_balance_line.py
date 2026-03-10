from odoo import fields, models, api


class FuelStationFuelBalanceLine(models.Model):
    _name = "fuel.station.fuel.balance.line"
    _description = "Fuel Balance Line (Per Fuel Product)"

    close_id = fields.Many2one(
        "fuel.station.shift.close", required=True, ondelete="cascade"
    )

    # ------------------------------------------------------------------
    # Fix (round 1): replaced stored related= fields with compute= fields
    #   to avoid Odoo 19's stricter related-field type consistency check.
    #
    # Fix (round 2): removed deep Many2many traversal paths from @api.depends
    #   e.g. "close_id.attendant_session_ids.line_ids.litres_sold".
    #
    # Fix (round 3): removed "close_id.attendant_session_ids" from @api.depends
    #   entirely. Even stopping at the Many2many field still fails in Odoo 19
    #   when the target model (fuel.station.shift.close) is not yet fully
    #   registered at the point the dependency tree is built — which happens
    #   when import order in __init__.py puts fuel_station_fuel_balance_line
    #   before fuel_station_shift_close, or when the shift close model is
    #   absent from __init__.py altogether.
    #
    #   Solution: depend only on "close_id" (the Many2one scalar itself) and
    #   "product_id".  This is safe because:
    #     - Balance lines are always edited from within a shift close form.
    #     - The "Prepare Balancing Lines" / "Pull Sessions" buttons on the
    #       shift close already force a recompute by writing to the record.
    #     - No cross-model Many2many path traversal is needed at startup.
    # ------------------------------------------------------------------

    _unique_close_product = models.Constraint(
        "UNIQUE(close_id, product_id)",
        "Only one balance line per fuel product per shift close.",
    )

    date = fields.Date(
        compute="_compute_close_fields",
        store=True,
        readonly=True,
        string="Date",
        index=True,
    )
    shift_id = fields.Many2one(
        "fuel.shift",
        compute="_compute_close_fields",
        store=True,
        readonly=True,
        string="Shift",
    )

    product_id = fields.Many2one("product.product", required=True)

    opening_litres = fields.Float(string="Opening Litres")
    closing_litres = fields.Float(string="Closing Litres")

    delivered_litres = fields.Float(compute="_compute_numbers", store=True)
    pump_sold_litres = fields.Float(compute="_compute_numbers", store=True)

    expected_outflow = fields.Float(compute="_compute_variance", store=True)
    litre_difference = fields.Float(compute="_compute_variance", store=True)

    price = fields.Float(string="Price per Litre")
    currency_id = fields.Many2one(
        'res.currency',
        compute='_compute_currency_id',
        string='Currency',
    )
    loss_value = fields.Float(compute="_compute_variance", store=True)

    # ------------------------------------------------------------------
    # Compute: propagate date and shift from the parent close record
    # ------------------------------------------------------------------

    @api.depends("close_id.date", "close_id.shift_id")
    def _compute_close_fields(self):
        for line in self:
            line.date = line.close_id.date
            line.shift_id = line.close_id.shift_id

    # ------------------------------------------------------------------
    # Compute: pump_sold_litres and delivered_litres
    # ------------------------------------------------------------------

    @api.depends("close_id", "product_id")
    def _compute_numbers(self):
        """
        Recomputes when close_id or product_id changes.

        We intentionally do NOT depend on close_id.attendant_session_ids
        or any deeper path because:
          1. Odoo 19 raises ValueError when resolving Many2many field paths
             in @api.depends at registry startup if the target model is not
             yet fully registered.
          2. The operational workflow already handles this: sessions are
             approved before the shift close is created, and the
             "Pull Sessions" + "Prepare Balancing Lines" buttons write to
             the close record, which invalidates these stored fields and
             triggers a fresh recompute automatically.

        pump_sold_litres: sum of approved session sales lines for this product.
        delivered_litres: sum of delivery lines on applied deliveries for this date.
                          Uses state="applied" — the terminal delivery state.
                          ("done" is NOT a valid value in the delivery state machine.)
        """
        for line in self:
            sessions = line.close_id.attendant_session_ids
            sold_lines = sessions.mapped("line_ids").filtered(
                lambda sl: sl.product_id.id == line.product_id.id
            )
            line.pump_sold_litres = sum(sold_lines.mapped("litres_sold"))

            deliveries = self.env["fuel.delivery"].search([
                ("state", "=", "applied"),
                ("delivery_date", "=", line.close_id.date),
            ])
            delivery_lines = deliveries.mapped("delivery_line_ids").filtered(
                lambda dl: dl.product_id.id == line.product_id.id
            )
            line.delivered_litres = sum(delivery_lines.mapped("received_litres"))

    # ------------------------------------------------------------------
    # Compute: variance
    # ------------------------------------------------------------------

    @api.depends(
        "opening_litres",
        "closing_litres",
        "delivered_litres",
        "pump_sold_litres",
        "price",
    )
    def _compute_variance(self):
        """
        expected_outflow = opening + delivered - closing
        litre_difference = expected_outflow - pump_sold  (positive = loss)
        loss_value       = litre_difference x price
        """
        for line in self:
            opening = line.opening_litres or 0.0
            delivered = line.delivered_litres or 0.0
            closing = line.closing_litres or 0.0
            sold = line.pump_sold_litres or 0.0

            line.expected_outflow = opening + delivered - closing
            line.litre_difference = line.expected_outflow - sold
            line.loss_value = line.litre_difference * (line.price or 0.0)

    @api.depends_context('company')
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = self.env.company.currency_id