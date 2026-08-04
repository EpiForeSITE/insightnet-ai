# Reproducing the Ask InsightNet GCP setup

This is Terraform for everything the GCP side of Ask InsightNet needed: enabled APIs, two service accounts, Workload Identity Federation, the Artifact Registry repository, Firestore, the Cloud Run service's shape, the Domain Restricted Sharing exception that makes it public, and the billing budget.

It exists because none of that was ever committed anywhere — it was run by hand, once, against the console and `gcloud`. If you needed to rebuild this (a second environment, disaster recovery, handing the project to someone else) there was nothing to read but a chat transcript. This directory is that transcript turned into something you can `plan` and `apply`.

## What Terraform does not do

- **Create the GCP project or link billing.** Terraform needs a project to run against.
  ```bash
  gcloud projects create YOUR_PROJECT_ID --organization=YOUR_ORG_ID
  gcloud billing projects link YOUR_PROJECT_ID --billing-account=YOUR_BILLING_ACCOUNT_ID
  ```
- **Grant itself org-level permissions.** `org_policy.tf` needs the identity running `terraform apply` to already hold `roles/orgpolicy.policyAdmin` at the **organization**, not the project. Terraform cannot bootstrap a permission it doesn't have. Grant it once, by hand, to whoever will run `apply`:
  ```bash
  gcloud organizations add-iam-policy-binding YOUR_ORG_ID \
    --member="user:you@example.com" --role="roles/orgpolicy.policyAdmin"
  ```
  If you'd rather that org-level change not sit in a state file other people can `apply`, set `manage_org_policy = false` in your `.tfvars` and apply the exception separately — the exact commands are in `org_policy.tf`.
- **Build or push the container image.** `deploy-ask.yml` does that on every push to `main`. Terraform creates the Cloud Run service pointed at a public placeholder image so there's a service to attach IAM and scaling settings to; the real image lands on the first CI deploy, and Terraform is told to stop looking at that field — see the `lifecycle` block in `cloud_run.tf`. Without it, a routine `terraform apply` would silently roll a live deploy back to the placeholder.
- **Embed the retrieval index.** That's `insightnet-rag`; unrelated to infrastructure.

## Adopting resources that already exist

If you're pointing this at the `ask-insightnet` project as it stands today, a fresh `terraform apply` will fail with "already exists" on nearly everything — not silently recreate it. Import instead. This is read/write only against Terraform's own state file; it doesn't touch anything live.

```bash
cd infra/terraform
terraform init

PROJECT=ask-insightnet
REGION=us-central1

for api in run.googleapis.com aiplatform.googleapis.com artifactregistry.googleapis.com \
           firestore.googleapis.com iamcredentials.googleapis.com sts.googleapis.com \
           orgpolicy.googleapis.com billingbudgets.googleapis.com; do
  terraform import "google_project_service.apis[\"$api\"]" "$PROJECT/$api"
done

terraform import google_artifact_registry_repository.insightnet \
  "projects/$PROJECT/locations/$REGION/repositories/insightnet"

terraform import google_firestore_database.default \
  "projects/$PROJECT/databases/(default)"

terraform import google_service_account.runtime \
  "projects/$PROJECT/serviceAccounts/insightnet-ask@$PROJECT.iam.gserviceaccount.com"
terraform import google_service_account.deploy \
  "projects/$PROJECT/serviceAccounts/insightnet-deploy@$PROJECT.iam.gserviceaccount.com"

terraform import google_iam_workload_identity_pool.github \
  "projects/$PROJECT/locations/global/workloadIdentityPools/github"
terraform import google_iam_workload_identity_pool_provider.github \
  "projects/$PROJECT/locations/global/workloadIdentityPools/github/providers/github-provider"

terraform import google_cloud_run_v2_service.ask \
  "projects/$PROJECT/locations/$REGION/services/insightnet-ask"

terraform import 'google_org_policy_policy.allow_public_run_invoker[0]' \
  "projects/$PROJECT/policies/iam.allowedPolicyMemberDomains"
```

`google_project_iam_member`, `google_service_account_iam_member`, and `google_cloud_run_v2_service_iam_member` are additive bindings, not standalone resources — applying them re-asserts a binding that's already there, and Terraform reports no change. They don't need an import step.

The billing budget's resource ID isn't something this conversation ever captured (it was created through the console). Find it, then import it:
```bash
gcloud billing budgets list --billing-account=YOUR_BILLING_ACCOUNT_ID --format='value(name)'
terraform import google_billing_budget.ask_insightnet "YOUR_BILLING_ACCOUNT_ID:BUDGET_ID"
```

After importing everything, run `terraform plan`. It should report no changes. If it doesn't, read the diff before applying anything — it's telling you exactly where the live configuration and this file disagree, and one of the two is wrong.

## State

Configured for local state (`terraform.tfstate`, gitignored) — zero extra setup, at the cost of living only on whichever machine ran `apply`. Fine for one maintainer. For shared state later, the standard fix is a small `gcs` backend bucket created once outside Terraform (state for the bucket that holds your state has to start somewhere), then referenced in a `backend "gcs" {}` block here.

## Running it

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # fill in project_id and billing_account_id
terraform init
terraform plan                                  # review before applying anything
TF_VAR_ip_salt=$(openssl rand -hex 32) terraform apply
```

`ip_salt` is deliberately not in `terraform.tfvars.example` — it's a secret, not config. Whatever value you use here must match the `IP_SALT` GitHub Actions secret; both feed the same `sha256(salt + ip)` hash in `server/budget.py`, from two different places.

## What's still not Terraform, on purpose

The org-level grant of `orgpolicy.policyAdmin` (above) stays a manual `gcloud` one-liner rather than a resource here — putting an org-scoped IAM change in the same state file as application infrastructure means anyone who can run `terraform apply` on this project can grant themselves broader org access than the project needs. One sentence in this README is a smaller blast radius than that.

## Note on validation

This was written and reviewed carefully, but not run: Terraform isn't installed in the environment this was authored in, so `terraform validate` and `terraform plan` were never executed against it. Treat the first `terraform plan` you run as the real check, the same way you'd review a PR before merging it — and if something doesn't match the live project, the plan output is the ground truth, not this file.
