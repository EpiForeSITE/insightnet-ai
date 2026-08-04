variable "project_id" {
  description = "The dedicated GCP project this service runs in."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Artifact Registry, and Vertex AI calls."
  type        = string
  default     = "us-central1"
}

variable "github_owner" {
  description = "GitHub org or user that owns the repository allowed to deploy."
  type        = string
  default     = "EpiForeSITE"
}

variable "github_repo" {
  description = "Repository name. The WIF provider's attribute_condition pins to this exact owner/repo, so no other repository's OIDC token is accepted."
  type        = string
  default     = "insightnet-explorer"
}

variable "billing_account_id" {
  description = "e.g. 01D6A9-E6F562-5900F6. Find it with: gcloud billing accounts list"
  type        = string
}

variable "allowed_origins" {
  description = "Comma-separated CORS allowlist for POST /ask. Must be an origin (scheme + host), never a path — browsers never send the path in the Origin header, so a trailing path here silently rejects your own site."
  type        = string
  default     = "https://epiforesite.github.io"
}

variable "daily_query_cap" {
  description = "Global daily request cap. See server/README.md for the cost model behind this default."
  type        = number
  default     = 400
}

variable "monthly_budget_micros" {
  description = "Hard stop on the service's own Firestore-tracked spend, in micro-dollars. 5_000_000 = $5."
  type        = number
  default     = 5000000
}

variable "budget_amount_usd" {
  description = "Cloud Billing budget amount. This is the console's alerting/spend-cap layer, independent of monthly_budget_micros above — see infra/terraform/README.md for how the layers relate."
  type        = number
  default     = 10
}

variable "ip_salt" {
  description = "Secret salt for hashing rate-limit keys (sha256(salt + ip)), so raw addresses are never stored. Generate with: openssl rand -hex 32. Pass this with TF_VAR_ip_salt or -var, never commit it, and keep it identical to the IP_SALT GitHub secret."
  type        = string
  sensitive   = true
}

variable "manage_org_policy" {
  description = "Whether Terraform manages the Domain Restricted Sharing exception that allows Cloud Run's public invoker binding. Requires the identity running `terraform apply` to already hold roles/orgpolicy.policyAdmin at the ORGANIZATION — see org_policy.tf. Set to false to apply that exception by hand instead."
  type        = bool
  default     = true
}

variable "placeholder_image" {
  description = "Image the Cloud Run service is created with before CI has pushed a real one. Never used again after the first deploy — see the lifecycle block in cloud_run.tf."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}
