output "table_name" {
  value = aws_dynamodb_table.table.name
}

output "role_arn" {
  value = aws_iam_role.lambda_role.arn
}

output "distribution_id" {
  value = aws_cloudfront_distribution.distribution.id
}