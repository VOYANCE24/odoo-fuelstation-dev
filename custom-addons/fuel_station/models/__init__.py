# ---------------------------------------------------------------------------
# Import order matters in Odoo 19.
# Models referenced by Many2one in other models must be imported first.
# ---------------------------------------------------------------------------

# -- Configuration & master data --
from . import fuel_station_config
from . import calibration
from . import product_fuel_extend      # extends product.template with fuel fields
from . import res_partner_fuel_extend  # extends res.partner with fuel credit limit
from . import fuel_price               # fuel price table with get_current_price()
from . import fuel_shift
from . import fuel_pump
from . import fuel_nozzle      # fuel.nozzle depends on fuel.pump
from . import fuel_attendant

# -- Stock / delivery --
from . import stock_picking
from . import fuel_delivery
from . import fuel_delivery_line

# -- Transactional leaf models --
from . import fuel_credit_sale_line
from . import fuel_credit_sale
from . import fuel_cash_deposit
from . import fuel_credit_payment

# -- Session layer --
from . import fuel_attendant_session_line
from . import fuel_attendant_session

# -- Shift close aggregate layer --
# fuel_station_shift_close BEFORE fuel_station_fuel_balance_line
from . import fuel_station_shift_close
from . import fuel_station_fuel_balance_line

# -- Dashboard (transient, no cross-dependency constraints) --
from . import fuel_dashboard

# -- Reporting wizards --
from . import fuel_customer_statement_wizard

# -- Petty cash / cash expenses --
from . import fuel_petty_cash_category
from . import fuel_petty_cash_config
from . import fuel_petty_cash_expense_line
from . import fuel_petty_cash_expense
from . import fuel_petty_cash_replenishment

# -- Payouts --
from . import fuel_payout_line
from . import fuel_payout