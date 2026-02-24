from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FuelDelivery(models.Model):
    _name = "fuel.delivery"
    _description = "Fuel Delivery Measurements"
    _order = "id desc"

    name = fields.Char(string="Delivery Ref", required=True, default=lambda self: self.env["ir.sequence"].next_by_code("fuel.delivery") or "New")

    delivery_date = fields.Date(default=fields.Date.context_today, required=True)
    state = fields.Selection([("draft", "Draft"), ("done", "Done")], default="draft", required=True)

    delivery_line_ids = fields.One2many("fuel.delivery.line", "delivery_id", string="Delivered Litres")

    picking_id = fields.Many2one(
        "stock.picking",
        string="Receipt (Picking)",
        required=True,
        ondelete="cascade",
        domain=[("picking_type_id.code", "=", "incoming")],
    )

    truck_id = fields.Char(string="Truck ID / Plate")

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("measured", "Measured"),
            ("applied", "Applied to Stock"),
        ],
        default="draft",
        required=True,
    )

    compartment_line_ids = fields.One2many(
        "fuel.delivery.compartment",
        "delivery_id",
        string="Truck Compartments",
        copy=True,
    )

    tankdip_line_ids = fields.One2many(
        "fuel.delivery.tankdip",
        "delivery_id",
        string="Station Tank Dips",
        copy=True,
    )

    notes = fields.Text()

    def action_mark_measured(self):
        for rec in self:
            rec.state = "measured"

    def action_apply_measured_quantities(self):
        """
        Update stock moves (picking moves) quantities based on measured liters.
        - We do not block on mismatch; we just record and adjust move qty_done.
        """
        for rec in self:
            if not rec.picking_id:
                raise ValidationError("Please select a receipt (picking).")

            picking = rec.picking_id

            # Sum measured liters per product from compartments
            product_qty_map = {}
            for line in rec.compartment_line_ids:
                if not line.product_id:
                    continue
                product_qty_map.setdefault(line.product_id.id, 0.0)
                product_qty_map[line.product_id.id] += (line.measured_volume_liters or 0.0)

            if not product_qty_map:
                raise ValidationError("No measured volumes found on compartment lines.")

            # Update picking stock moves
            moves = picking.move_ids.filtered(lambda m: m.product_id and m.state not in ("done", "cancel"))
            for move in moves:
                measured_qty = product_qty_map.get(move.product_id.id)
                if measured_qty is None:
                    continue

                # Set qty_done to measured liters (assuming UoM is Liters or convertible)
                # For v1 we assume product UoM is compatible with liters.
                move.quantity_done = measured_qty

            rec.state = "applied"


class FuelDeliveryCompartment(models.Model):
    _name = "fuel.delivery.compartment"
    _description = "Fuel Delivery Compartment Measurement"
    _order = "sequence, id"

    delivery_id = fields.Many2one("fuel.delivery", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)

    compartment_code = fields.Char(string="Compartment", required=True, help="Identifier e.g. C1, C2, 1, 2, etc.")

    product_id = fields.Many2one(
        "product.product",
        string="Fuel Product",
        required=False,
        domain="[('id', 'in', picking_product_ids)]",
    )

    # helper: allowed products from picking lines
    picking_product_ids = fields.Many2many(
        "product.product",
        compute="_compute_picking_products",
        string="Allowed Products",
        store=False,
    )

    expected_depth_mm = fields.Float(string="Expected Depth (mm)")
    measured_depth_mm = fields.Float(string="Measured Depth (mm)")
    depth_diff_mm = fields.Float(string="Depth Diff (mm)", compute="_compute_diffs", store=False)

    expected_density = fields.Float(string="Expected Density")
    measured_density = fields.Float(string="Measured Density")
    density_diff = fields.Float(string="Density Diff", compute="_compute_diffs", store=False)

    calibration_profile_id = fields.Many2one(
        "fuel.calibration.profile",
        string="Calibration Profile",
        ondelete="set null",
        domain=[("profile_type", "=", "truck")],
        help="If set, measured depth will compute measured volume via calibration.",
    )

    measured_volume_liters = fields.Float(
        string="Measured Volume (L)",
        compute="_compute_measured_volume",
        store=False,
    )

    @api.depends("delivery_id.picking_id")
    def _compute_picking_products(self):
        for rec in self:
            picking = rec.delivery_id.picking_id
            products = picking.move_ids.mapped("product_id") if picking else self.env["product.product"]
            rec.picking_product_ids = [(6, 0, products.ids)]

    @api.depends("expected_depth_mm", "measured_depth_mm", "expected_density", "measured_density")
    def _compute_diffs(self):
        for rec in self:
            rec.depth_diff_mm = (rec.measured_depth_mm or 0.0) - (rec.expected_depth_mm or 0.0)
            rec.density_diff = (rec.measured_density or 0.0) - (rec.expected_density or 0.0)

    @api.depends("measured_depth_mm", "calibration_profile_id")
    def _compute_measured_volume(self):
        for rec in self:
            if rec.calibration_profile_id and rec.measured_depth_mm is not False:
                rec.measured_volume_liters = rec.calibration_profile_id.volume_from_depth_mm(rec.measured_depth_mm)
            else:
                rec.measured_volume_liters = 0.0


class FuelDeliveryTankDip(models.Model):
    _name = "fuel.delivery.tankdip"
    _description = "Fuel Station Tank Dip"
    _order = "sequence, id"

    delivery_id = fields.Many2one("fuel.delivery", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)

    tank_code = fields.Char(string="Tank", required=True, help="Identifier e.g. PMS-1, AGO-1")

    product_id = fields.Many2one(
        "product.product",
        string="Fuel Product",
        required=False,
        domain="[('id', 'in', picking_product_ids)]",
    )

    picking_product_ids = fields.Many2many(
        "product.product",
        compute="_compute_picking_products",
        string="Allowed Products",
        store=False,
    )

    calibration_profile_id = fields.Many2one(
        "fuel.calibration.profile",
        string="Calibration Profile",
        ondelete="set null",
        domain=[("profile_type", "=", "tank")],
    )

    depth_before_mm = fields.Float(string="Depth Before (mm)")
    depth_after_mm = fields.Float(string="Depth After (mm)")

    volume_before_liters = fields.Float(string="Volume Before (L)", compute="_compute_volumes", store=False)
    volume_after_liters = fields.Float(string="Volume After (L)", compute="_compute_volumes", store=False)
    delta_volume_liters = fields.Float(string="Delta (L)", compute="_compute_volumes", store=False)

    @api.depends("delivery_id.picking_id")
    def _compute_picking_products(self):
        for rec in self:
            picking = rec.delivery_id.picking_id
            products = picking.move_ids.mapped("product_id") if picking else self.env["product.product"]
            rec.picking_product_ids = [(6, 0, products.ids)]

    @api.depends("depth_before_mm", "depth_after_mm", "calibration_profile_id")
    def _compute_volumes(self):
        for rec in self:
            if rec.calibration_profile_id:
                rec.volume_before_liters = rec.calibration_profile_id.volume_from_depth_mm(rec.depth_before_mm)
                rec.volume_after_liters = rec.calibration_profile_id.volume_from_depth_mm(rec.depth_after_mm)
            else:
                rec.volume_before_liters = 0.0
                rec.volume_after_liters = 0.0
            rec.delta_volume_liters = rec.volume_after_liters - rec.volume_before_liters