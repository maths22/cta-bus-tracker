data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

provider "aws" {
  region = "us-east-2"

  default_tags {
    tags = {
      Environment = "Production"
      Project     = "CTA-Bus-Tracker"
    }
  }
}

provider "aws" {
  region = "us-east-1"

  alias = "iad"

  default_tags {
    tags = {
      Environment = "Production"
      Project     = "CTA-Bus-Tracker"
    }
  }
}