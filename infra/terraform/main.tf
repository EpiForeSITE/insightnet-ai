# The project number, not the project id, is what org-scoped and billing-scoped
# resources address themselves by (google_org_policy_policy, google_billing_budget).
data "google_project" "this" {
  project_id = var.project_id
}
