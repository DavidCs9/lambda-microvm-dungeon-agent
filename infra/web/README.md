# Live web hosting

The web client is hosted from a private S3 bucket through CloudFront. The bucket is not public;
CloudFront uses an Origin Access Control and signs S3 requests with SigV4.

The `Deploy web sandbox` GitHub Actions workflow owns the hosting stack, publishes `web/dist`,
and invalidates CloudFront after each deployment.
