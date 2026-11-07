variable "kubeconfig" {
  type    = string
  default = "~/.kube/config"
}

variable "kube_context" {
  type    = string
  default = "kind-regintel"
}

variable "namespace" {
  type    = string
  default = "regintel"
}

variable "values_file" {
  type    = string
  default = "../k8s/helm/regintel/values-local.yaml"
}

variable "image_repository" {
  type    = string
  default = "regintel-api"
}

variable "image_tag" {
  type    = string
  default = "local"
}

variable "api_keys_json" {
  type      = string
  sensitive = true
}

variable "gateway_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "postgres_dsn" {
  type      = string
  sensitive = true
  default   = ""
}
