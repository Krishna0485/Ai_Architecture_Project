# Optional: deploy RegIntel onto any Kubernetes cluster you can reach with a kubeconfig
# (kind/k3d locally, or a managed cluster such as EKS/GKE/AKS). Cloud-agnostic on purpose:
# provisioning the cluster itself is out of scope - tear the demo down after recording it.
terraform {
  required_version = ">= 1.6"
  required_providers {
    helm       = { source = "hashicorp/helm", version = "~> 2.16" }
    kubernetes = { source = "hashicorp/kubernetes", version = "~> 2.33" }
  }
}

provider "kubernetes" {
  config_path    = var.kubeconfig
  config_context = var.kube_context
}

provider "helm" {
  kubernetes {
    config_path    = var.kubeconfig
    config_context = var.kube_context
  }
}

resource "kubernetes_namespace" "regintel" {
  metadata { name = var.namespace }
}

# API keys and DSNs come from variables marked sensitive (pass via TF_VAR_* or a tfvars file
# that is git-ignored). Prefer the chart's ExternalSecret support in real environments.
resource "kubernetes_secret" "regintel" {
  metadata {
    name      = "regintel-secrets"
    namespace = kubernetes_namespace.regintel.metadata[0].name
  }
  data = {
    REGINTEL_API_KEYS        = var.api_keys_json
    REGINTEL_GATEWAY_API_KEY = var.gateway_api_key
    REGINTEL_POSTGRES_DSN    = var.postgres_dsn
  }
}

resource "helm_release" "regintel" {
  name       = "regintel"
  namespace  = kubernetes_namespace.regintel.metadata[0].name
  chart      = "${path.module}/../k8s/helm/regintel"
  values     = [file(var.values_file)]
  depends_on = [kubernetes_secret.regintel]

  set {
    name  = "image.repository"
    value = var.image_repository
  }
  set {
    name  = "image.tag"
    value = var.image_tag
  }
}
