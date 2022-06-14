#!/usr/bin/env bash

export AWS_REGION=us-east-2
aws s3 sync ./wwwroot s3://cta-bus-history-tracker
aws cloudfront create-invalidation --distribution-id E1FUH5MRAQGTJZ --paths "/*"