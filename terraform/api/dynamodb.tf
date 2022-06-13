resource "random_uuid" "table_suffix" {
}

resource "aws_dynamodb_table" "table" {
  name           = "bus-tracker-app-${random_uuid.table_suffix.result}"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "key"
  range_key      = "range_key"

  attribute {
    name = "key"
    type = "S"
  }

  attribute {
    name = "range_key"
    type = "S"
  }
}

