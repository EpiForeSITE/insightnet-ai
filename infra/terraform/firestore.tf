# Backs server/budget.py's rate-limit counters, spend ledger, and answer cache.
resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = "nam5"
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.apis]
}
