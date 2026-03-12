from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FuelDelivery(models.Model):
    _name = "fuel.delivery"
    _description = "Fuel Delivery Measurements"
    _order = "id desc"


    name = fields.Char(
        string="Delivery Ref",
        required=True,
        default=lambda self: self.env["ir.sequence"].next_by_code("fuel.delivery") or "New",
    )

    delivery_date = fields.Date(default=fields.Date.context_today, required=True, index=True)

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("measured", "Measured"),
            ("applied", "Applied to Stock"),
        ],
        default="draft",
        required=True,
        index=True,
    )

    picking_id = fields.Many2one(
        "stock.picking",
        string="Receipt (Picking)",
        required=True,
        ondelete="cascade",
        domain=[("picking_type_id.code", "=", "incoming")],
    )

    truck_id = fields.Char(string="Truck ID / Plate")

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

    # Explicit delivery lines (per-product received litres) used by balance lines.
    delivery_line_ids = fields.One2many(
        "fuel.delivery.line",
        "delivery_id",
        string="Delivered Litres",
    )

    fuel_delivery_count = fields.Integer(
        compute="_compute_fuel_delivery_count",
        string="Fuel Deliveries",
    )

    compartment_total_liters = fields.Float(
        string="Compartment Total (L)",
        compute="_compute_delivery_variance",
        store=False,
        help="Sum of measured volumes across all compartment lines.",
    )
    tankdip_delta_liters = fields.Float(
        string="Tank Dip Delta (L)",
        compute="_compute_delivery_variance",
        store=False,
        help="Sum of volume deltas (after − before) across all tank dip lines.",
    )
    delivery_variance_liters = fields.Float(
        string="Delivery Variance (L)",
        compute="_compute_delivery_variance",
        store=False,
        help=(
            "= Compartment Total − Tank Dip Delta. "
            "Zero means the tank received exactly what the truck brought. "
            "Positive = overage in truck measurement; Negative = under-delivery."
        ),
    )

    notes = fields.Text()

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    def _compute_fuel_delivery_count(self):
        # Use read_group to count per picking in a single SQL query.
        picking_ids = self.mapped("picking_id").ids
        groups = self.read_group(
            domain=[("picking_id", "in", picking_ids)],
            fields=["picking_id"],
            groupby=["picking_id"],
        )
        count_by_picking = {g["picking_id"][0]: g["picking_id_count"] for g in groups}
        for rec in self:
            rec.fuel_delivery_count = count_by_picking.get(rec.picking_id.id, 0)

    @api.depends(
        "compartment_line_ids.measured_volume_liters",
        "tankdip_line_ids.delta_volume_liters",
    )
    def _compute_delivery_variance(self):
        for rec in self:
            compartment_total = sum(
                rec.compartment_line_ids.mapped("measured_volume_liters")
            )
            tankdip_delta = sum(
                rec.tankdip_line_ids.mapped("delta_volume_liters")
            )
            rec.compartment_total_liters = compartment_total
            rec.tankdip_delta_liters = tankdip_delta
            rec.delivery_variance_liters = compartment_total - tankdip_delta

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def action_mark_measured(self):
        for rec in self:
            if rec.state != "draft":
                continue
            rec.state = "measured"

    def action_apply_measured_quantities(self):
        """
        Write measured compartment volumes back to the linked stock picking's move lines.

        Odoo 17+ removed `quantity_done` on stock.move in favour of `quantity` on
        stock.move.line.  We update the move's `quantity` field (which in Odoo 17/18/19
        is the immediate-transfer quantity on the move level, auto-synced to move lines).

        If the picking is already done/cancelled we skip it gracefully.
        """
        for rec in self:
            if not rec.picking_id:
                raise ValidationError("Please select a receipt (picking).")

            picking = rec.picking_id

            if picking.state in ("done", "cancel"):
                raise ValidationError(
                    f"Picking {picking.name} is already {picking.state}. "
                    "Cannot apply measured quantities."
                )

            # Sum measured liters per product from compartment lines.
            product_qty_map: dict[int, float] = {}
            for line in rec.compartment_line_ids:
                if not line.product_id:
                    continue
                product_qty_map.setdefault(line.product_id.id, 0.0)
                product_qty_map[line.product_id.id] += line.measured_volume_liters or 0.0

            if not product_qty_map:
                raise ValidationError(
                    "No measured volumes found on compartment lines. "
                    "Please fill in measured depth and calibration profiles first."
                )

            # Apply to stock moves.
            # In Odoo 17+ the immediate qty on a move is `move.quantity`.
            # `quantity_done` is a computed summary and is read-only.
            moves = picking.move_ids.filtered(
                lambda m: m.product_id and m.state not in ("done", "cancel")
            )
            updated = False
            for move in moves:
                measured_qty = product_qty_map.get(move.product_id.id)
                if measured_qty is None:
                    continue
                move.quantity = measured_qty
                updated = True

            if not updated:
                raise ValidationError(
                    "None of the picking's move products matched the compartment lines. "
                    "Check that the products are consistent."
                )

            # Auto-populate delivery_line_ids from compartment measurements so
            # fuel balance lines can read received litres without manual entry.
            # Remove existing lines first to avoid duplication on re-apply.
            rec.delivery_line_ids.unlink()
            for product_id, qty in product_qty_map.items():
                self.env["fuel.delivery.line"].create({
                    "delivery_id": rec.id,
                    "product_id": product_id,
                    "received_litres": qty,
                })

            rec.state = "applied"


# ---------------------------------------------------------------------------
# Compartment measurement
# ---------------------------------------------------------------------------

class FuelDeliveryCompartment(models.Model):
    _name = "fuel.delivery.compartment"
    _description = "Fuel Delivery Compartment Measurement"
    _order = "sequence, id"

    delivery_id = fields.Many2one("fuel.delivery", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)

    compartment_code = fields.Char(
        string="Compartment",
        required=True,
        help="Identifier e.g. C1, C2, 1, 2, etc.",
    )

    product_id = fields.Many2one(
        "product.product",
        string="Fuel Product",
        required=False,
        domain="[('id', 'in', picking_product_ids)]",
    )

    # Helper: allowed products from the linked picking's moves.
    picking_product_ids = fields.Many2many(
        "product.product",
        compute="_compute_picking_products",
        string="Allowed Products",
        store=False,
    )

    expected_depth_cm = fields.Float(string="Expected Depth (cm)")
    measured_depth_cm = fields.Float(string="Measured Depth (cm)")
    depth_diff_cm = fields.Float(
        string="Depth Diff (cm)", compute="_compute_diffs", store=False
    )

    expected_density = fields.Float(string="Expected Density")
    measured_density = fields.Float(string="Measured Density")
    density_diff = fields.Float(
        string="Density Diff", compute="_compute_diffs", store=False
    )

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
        store=True,
    )

    @api.depends("delivery_id.picking_id")
    def _compute_picking_products(self):
        for rec in self:
            picking = rec.delivery_id.picking_id
            products = (
                picking.move_ids.mapped("product_id")
                if picking
                else self.env["product.product"]
            )
            rec.picking_product_ids = [(6, 0, products.ids)]

    @api.depends("expected_depth_cm", "measured_depth_cm", "expected_density", "measured_density")
    def _compute_diffs(self):
        for rec in self:
            rec.depth_diff_cm = (rec.measured_depth_cm or 0.0) - (rec.expected_depth_cm or 0.0)
            rec.density_diff = (rec.measured_density or 0.0) - (rec.expected_density or 0.0)

    @api.depends("measured_depth_cm", "calibration_profile_id")
    def _compute_measured_volume(self):
        for rec in self:
            if rec.calibration_profile_id and rec.measured_depth_cm is not False:
                rec.measured_volume_liters = rec.calibration_profile_id.volume_from_depth_cm(
                    rec.measured_depth_cm
                )
            else:
                rec.measured_volume_liters = 0.0


# ---------------------------------------------------------------------------
# Tank dip
# ---------------------------------------------------------------------------

class FuelDeliveryTankDip(models.Model):
    _name = "fuel.delivery.tankdip"
    _description = "Fuel Station Tank Dip"
    _order = "sequence, id"

    delivery_id = fields.Many2one("fuel.delivery", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)

    tank_code = fields.Char(
        string="Tank", required=True, help="Identifier e.g. PMS-1, AGO-1"
    )

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

    depth_before_cm = fields.Float(string="Depth Before (cm)")
    depth_after_cm = fields.Float(string="Depth After (cm)")

    volume_before_liters = fields.Float(
        string="Volume Before (L)", compute="_compute_volumes", store=True
    )
    volume_after_liters = fields.Float(
        string="Volume After (L)", compute="_compute_volumes", store=True
    )
    delta_volume_liters = fields.Float(
        string="Delta (L)", compute="_compute_volumes", store=True
    )

    @api.depends("delivery_id.picking_id")
    def _compute_picking_products(self):
        for rec in self:
            picking = rec.delivery_id.picking_id
            products = (
                picking.move_ids.mapped("product_id")
                if picking
                else self.env["product.product"]
            )
            rec.picking_product_ids = [(6, 0, products.ids)]

    @api.depends("depth_before_cm", "depth_after_cm", "calibration_profile_id")
    def _compute_volumes(self):
        for rec in self:
            if rec.calibration_profile_id:
                rec.volume_before_liters = rec.calibration_profile_id.volume_from_depth_cm(
                    rec.depth_before_cm
                )
                rec.volume_after_liters = rec.calibration_profile_id.volume_from_depth_cm(
                    rec.depth_after_cm
                )
            else:
                rec.volume_before_liters = 0.0
                rec.volume_after_liters = 0.0
            rec.delta_volume_liters = rec.volume_after_liters - rec.volume_before_liters