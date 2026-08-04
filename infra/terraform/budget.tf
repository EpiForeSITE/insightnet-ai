# This is a DIFFERENT layer from monthly_budget_micros in cloud_run.tf, and the two
# are easy to conflate. MONTHLY_BUDGET_MICROS is enforced by server/budget.py before
# every model call, against a Firestore counter, in real time. This budget is
# Google's own billing-account-level control: it reacts to billing data that trails
# actual usage by hours, and whether it actually stops spend ("spend cap") versus only
# alerts is a setting on the budget in the Cloud Billing console, not something this
# resource controls — check "Spend cap status" there after applying.
#
# In other words: the app-level cap is the one guaranteed to be immediate; treat this
# one as the slower outer backstop, not the primary control.
resource "google_billing_budget" "ask_insightnet" {
  billing_account = var.billing_account_id
  display_name    = "ask insightnet"

  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.budget_amount_usd)
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.8
  }
  threshold_rules {
    threshold_percent = 1.0
  }
}
