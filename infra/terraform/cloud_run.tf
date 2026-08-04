locals {
  # Mirrors the --set-env-vars list in deploy-ask.yml exactly. Everything else the
  # service reads (INSIGHTNET_MODEL, PRICE_IN_MICROS_PER_MTOK, ...) stays at the code
  # default in server/config.py unless overridden here.
  env_vars = {
    GOOGLE_CLOUD_PROJECT  = var.project_id
    GOOGLE_CLOUD_LOCATION = var.region
    ALLOWED_ORIGINS       = var.allowed_origins
    DAILY_QUERY_CAP       = tostring(var.daily_query_cap)
    MONTHLY_BUDGET_MICROS = tostring(var.monthly_budget_micros)
    IP_SALT               = var.ip_salt
  }
}

resource "google_cloud_run_v2_service" "ask" {
  project  = var.project_id
  name     = "insightnet-ask"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account                  = google_service_account.runtime.email
    timeout                          = "60s"
    max_instance_request_concurrency = 8

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      # A public placeholder, replaced on the very first CI deploy. Terraform is
      # responsible for the service's shape — scaling, identity, env structure — never
      # for which image happens to be live; the `lifecycle` block below says so
      # explicitly so a routine `apply` can never roll a deploy backward.
      image = var.placeholder_image

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.env_vars
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [google_project_service.apis]
}

# Public access. Requires the org policy exception above — see org_policy.tf for why
# this cannot be granted without it, and what applying that exception actually trades.
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.ask.name
  role     = "roles/run.invoker"
  member   = "allUsers"

  depends_on = [google_org_policy_policy.allow_public_run_invoker]
}
