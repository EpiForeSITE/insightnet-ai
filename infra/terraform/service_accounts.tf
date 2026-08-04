# Two identities, least privilege: the runtime account can only call Vertex AI and
# read/write Firestore, and never touches deployment; the deploy account can push
# images and roll out revisions, and never holds any of the runtime's permissions
# directly — it borrows them for exactly one deploy via serviceAccountUser below.

resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "insightnet-ask"
  display_name = "Ask InsightNet Cloud Run runtime"
}

resource "google_service_account" "deploy" {
  project      = var.project_id
  account_id   = "insightnet-deploy"
  display_name = "Ask InsightNet GitHub deployment"
}

resource "google_project_iam_member" "runtime_aiplatform_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "runtime_datastore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "deploy_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${google_service_account.deploy.email}"
}

# refresh-works.yml runs `insightnet-rag` as this same identity to rebuild the
# retrieval index, which is why it needs Vertex access too, not just Cloud Run.
resource "google_project_iam_member" "deploy_aiplatform_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.deploy.email}"
}

resource "google_artifact_registry_repository_iam_member" "deploy_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.insightnet.location
  repository = google_artifact_registry_repository.insightnet.repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.deploy.email}"
}

# Lets the deploy identity launch a Cloud Run revision that runs *as* the runtime
# identity, without the deploy identity ever holding aiplatform.user or
# datastore.user on its own account.
resource "google_service_account_iam_member" "deploy_can_run_as_runtime" {
  service_account_id = google_service_account.runtime.name
  role                = "roles/iam.serviceAccountUser"
  member              = "serviceAccount:${google_service_account.deploy.email}"
}
