# Domain Restricted Sharing blocks `allUsers` on any IAM binding by default, which is
# what made `gcloud run services add-iam-policy-binding ... --member=allUsers` fail
# with FAILED_PRECONDITION the first time this was deployed by hand. This exempts the
# whole project from that constraint — the narrower value
# (principalSet://goog/public:all) is rejected outright by Google's managed constraint,
# so there is no scoped alternative to `allow_all`.
#
# Be clear-eyed about the trade: anything in this project can be made public after
# this applies, not just this one Cloud Run service. That is the entire reason this
# lives in its own dedicated project rather than alongside anything else.
#
# Applying this resource requires the identity running `terraform apply` to already
# hold roles/orgpolicy.policyAdmin at the ORGANIZATION, not the project — a permission
# Terraform cannot grant itself. Bootstrap once, by hand, before the first apply:
#
#   gcloud organizations add-iam-policy-binding YOUR_ORG_ID \
#     --member="user:you@example.com" --role="roles/orgpolicy.policyAdmin"
#
# Set manage_org_policy = false to skip this resource — e.g. if an org admin applies
# the exception separately and you'd rather that org-level change stay out of a state
# file other collaborators can `apply`.
resource "google_org_policy_policy" "allow_public_run_invoker" {
  count = var.manage_org_policy ? 1 : 0

  name   = "projects/${data.google_project.this.number}/policies/iam.allowedPolicyMemberDomains"
  parent = "projects/${data.google_project.this.number}"

  spec {
    rules {
      allow_all = "TRUE"
    }
  }

  depends_on = [google_project_service.apis]
}
