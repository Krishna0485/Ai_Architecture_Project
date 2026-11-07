output "namespace" {
  value = kubernetes_namespace.regintel.metadata[0].name
}

output "release" {
  value = helm_release.regintel.name
}

output "port_forward" {
  value = "kubectl -n ${var.namespace} port-forward svc/regintel-api 8080:80"
}
