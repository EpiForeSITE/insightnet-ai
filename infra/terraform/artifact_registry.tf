resource "google_artifact_registry_repository" "insightnet" {
  project       = var.project_id
  location      = var.region
  repository_id = "insightnet"
  format        = "DOCKER"
  description   = "Ask InsightNet container images"

  depends_on = [google_project_service.apis]
}
