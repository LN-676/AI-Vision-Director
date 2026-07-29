variable "project_id" {
  description = "Google Cloud and Firebase project ID."
  type        = string
  default     = "bright-torus-483009-k2"
}

variable "billing_account_id" {
  description = "Billing account used by the US$1 notification budget."
  type        = string
  default     = "016F38-D5506F-3E7770"
}

variable "region" {
  description = "Taiwan region for Cloud Run, Cloud SQL, and Artifact Registry."
  type        = string
  default     = "asia-east1"
}

variable "api_image" {
  description = "Immutable Artifact Registry API image reference including digest."
  type        = string
}

variable "dashboard_image" {
  description = "Immutable Artifact Registry dashboard image reference including digest."
  type        = string
}

variable "benchmark_image" {
  description = "CUDA-enabled immutable benchmark worker image. Falls back to api_image for planning compatibility."
  type        = string
  default     = ""
}

variable "cors_allow_origins" {
  description = "Comma-separated HTTPS origins permitted to call the API."
  type        = string
  default     = "https://bright-torus-483009-k2.web.app,https://bright-torus-483009-k2.firebaseapp.com"
}

variable "custom_domain" {
  description = "Optional custom dashboard domain configured in Firebase Hosting."
  type        = string
  default     = ""
}

variable "enable_gpu_benchmark" {
  description = "Create the opt-in L4 Cloud Run benchmark job. Disabled by default for cost safety."
  type        = bool
  default     = false
}

variable "gpu_region" {
  description = "Cloud Run region with NVIDIA L4 job capacity."
  type        = string
  default     = "asia-southeast1"
}

variable "alert_email" {
  description = "Optional email address for Cloud Monitoring incident notifications."
  type        = string
  default     = ""
}

variable "enable_advanced_cloud" {
  description = "Enable stateful Phase 6 API mutations and cloud benchmark submission."
  type        = bool
  default     = false
}
