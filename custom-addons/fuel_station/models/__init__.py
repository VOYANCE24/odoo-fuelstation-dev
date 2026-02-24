# ---------------------------------------------------------------------------
# Import order matters in Odoo 19.
#
# Models that are referenced by Many2one fields in OTHER models must be
# imported BEFORE the models that reference them.  If a model is imported
# after a model that already depends on it via @api.depends or stored
# related fields, Odoo's registry startup may fail to resolve field
# dependencies.
#
# Correct order here:
#   1. Base / configuration models (no cross-module dependencies)
#   2. Transactional leaf models
#   3. Aggregate / summary models that reference the above
# ---------------------------------------------------------------------------

# -- Configuration & master data (no dependencies on other custom models) --
from . import calibration
from . import fuel_shift
from . import fuel_pump
from . import fuel_attendant

# -- Stock / delivery (depends on calibration, pump) --
from . import stock_picking
from . import fuel_delivery
from . import fuel_delivery_line

# -- Transactional leaf models (depend on shift, pump, attendant) --
from . import fuel_credit_sale
from . import fuel_cash_deposit
from . import fuel_credit_payment

# -- Session layer (depends on credit_sale, cash_deposit, pump) --
from . import fuel_attendant_session_line
from . import fuel_attendant_session

# -- Shift close aggregate layer --
# fuel_station_shift_close must be imported BEFORE fuel_station_fuel_balance_line
# because fuel_station_fuel_balance_line holds a Many2one to fuel.station.shift.close
# and @api.depends("close_id", ...) requires the target model to be registered first.
from . import fuel_station_shift_close
from . import fuel_station_fuel_balance_line