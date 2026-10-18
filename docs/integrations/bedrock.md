# Amazon Bedrock (advanced)

## What it unlocks

Amazon Bedrock lets the app call supported foundation models through your AWS account. This setup is intended for users already comfortable managing AWS credentials.

## Cost

AWS charges vary by model, region, and usage. Review [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/) before use.

## Get your credentials

1. In the AWS console, choose an AWS region where your model is available.
2. Open Amazon Bedrock and request or enable access to the model you plan to use.
3. Create AWS credentials with permissions to invoke that model. Keep the credentials private.

## Connect it

Bedrock credentials are supplied to Docker as environment variables. Create `docker-compose.override.yml` next to `docker-compose.yml` with:

```yaml
services:
  app:
    environment:
      AWS_ACCESS_KEY_ID: "replace-with-your-access-key"
      AWS_SECRET_ACCESS_KEY: "replace-with-your-secret-key"
      AWS_DEFAULT_REGION: "us-east-1"
  scheduler:
    environment:
      AWS_ACCESS_KEY_ID: "replace-with-your-access-key"
      AWS_SECRET_ACCESS_KEY: "replace-with-your-secret-key"
      AWS_DEFAULT_REGION: "us-east-1"
```

Replace the example values, protect this file, and never commit it. In Settings choose **Bedrock**, select an enabled model and region, then test the connection. Remove the override and revoke the credentials if you no longer use them.
