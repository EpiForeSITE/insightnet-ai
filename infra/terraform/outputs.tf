output "wif_provider" {
  description = "Value for the WIF_PROVIDER GitHub Actions secret."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "wif_service_account" {
  description = "Value for the WIF_SERVICE_ACCOUNT GitHub Actions secret."
  value       = google_service_account.deploy.email
}

output "cloud_run_url" {
  description = "The service's public URL. Answers with the placeholder image's response until deploy-ask.yml has pushed a real one."
  value       = google_cloud_run_v2_service.ask.uri
}

output "artifact_registry_repository" {
  description = "Fully-qualified repository name, for reference against deploy-ask.yml's IMAGE variable."
  value       = google_artifact_registry_repository.insightnet.name
}
