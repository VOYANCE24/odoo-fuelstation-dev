from odoo import fields, models, api

class FuelStationFuelBalanceLine(models.Model):
    _name = "fuel.station.fuel.balance.line"
    _description = "Fuel Balance Line (Per Fuel Product)"

    close_id = fields.Many2one("fuel.station.shift.close", required=True, ondelete="cascade")
    date = fields.Date(related="close_id.date", store=True, readonly=True)
    shift_id = fields.Many2one(related="close_id.shift_id", store=True, readonly=True)

    product_id = fields.Many2one("product.product", required=True)

    # For now manual litres; later you can compute from depth + calibration profiles
    opening_litres = fields.Float()
    closing_litres = fields.Float()

    delivered_litres = fields.Float(compute="_compute_numbers", store=True)
    pump_sold_litres = fields.Float(compute="_compute_numbers", store=True)

    expected_outflow = fields.Float(compute="_compute_variance", store=True)
    litre_difference = fields.Float(compute="_compute_variance", store=True)

    price = fields.Float()
    loss_value = fields.Float(compute="_compute_variance", store=True)

    @api.depends(
        "close_id.attendant_session_ids.line_ids.litres_sold",
        "close_id.attendant_session_ids.line_ids.product_id",
        "close_id.date",
        "close_id.shift_id",
    )
    def _compute_numbers(self):
        for l in self:
            sessions = l.close_id.attendant_session_ids
            sold_lines = sessions.mapped("line_ids").filtered(lambda x: x.product_id.id == l.product_id.id)
            l.pump_sold_litres = sum(sold_lines.mapped("litres_sold"))

            # deliveries: only done deliveries in shift window
            start_utc, end_utc = l.close_id.shift_id.get_window(l.close_id.date)
            deliveries = l.env["fuel.delivery"].search([
                ("state", "=", "done"),
                ("delivery_date", "=", l.close_id.date),
            ])

            dlines = deliveries.mapped("delivery_line_ids").filtered(lambda dl: dl.product_id.id == l.product_id.id)
            l.delivered_litres = sum(dlines.mapped("received_litres"))

    @api.depends("opening_litres", "closing_litres", "delivered_litres", "pump_sold_litres", "price")
    def _compute_variance(self):
        for l in self:
            opening = l.opening_litres or 0.0
            delivered = l.delivered_litres or 0.0
            closing = l.closing_litres or 0.0
            sold = l.pump_sold_litres or 0.0

            l.expected_outflow = opening + delivered - closing
            l.litre_difference = l.expected_outflow - sold
            l.loss_value = (l.litre_difference or 0.0) * (l.price or 0.0)