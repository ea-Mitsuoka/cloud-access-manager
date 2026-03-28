output "executor_service_account_email" {
  value = google_service_account.executor.email
}

output "scheduler_invoker_service_account_email" {
  value = google_service_account.scheduler_invoker.email
}

output "gas_invoker_service_account_email" {
  value = google_service_account.gas_invoker.email
}
