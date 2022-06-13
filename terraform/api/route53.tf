data "aws_route53_zone" "zone" {
  name         = "maths22.com"
  private_zone = false
}