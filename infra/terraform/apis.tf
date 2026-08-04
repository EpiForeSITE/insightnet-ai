# Deliberately no cloudbuild.googleapis.com: deploy-ask.yml builds the container image
# on the GitHub Actions runner and pushes straight to Artifact Registry, precisely to
# avoid the storage and serviceusage permissions `gcloud builds submit` would otherwise
# need on the deploy identity — see the comment in that workflow for the failure this
# was chosen to route around.
locals {
  required_apis = [
    "run.googleapis.com",
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "firestore.googleapis.com",
    "iamcredentials.googleapis.com", # workload identity token exchange
    "sts.googleapis.com",            # workload identity token exchange
    "orgpolicy.googleapis.com",      # only exercised if manage_org_policy = true
    "billingbudgets.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.required_apis)
  project  = var.project_id
  service  = each.value

  # Leave the service enabled if this project is ever destroyed piecemeal — disabling
  # aiplatform.googleapis.com out from under a still-running Cloud Run revision is a
  # worse failure mode than a lingering enabled API.
  disable_on_destroy = false
}
