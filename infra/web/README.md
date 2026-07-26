# Live web hosting

The web client is hosted from a private S3 bucket through CloudFront. The bucket is not public;
CloudFront uses an Origin Access Control and signs S3 requests with SigV4.

The unified `Release sandbox components` workflow owns web deployment decisions. After a merge to
`main`, when web files changed since the previous successful release, it deploys the hosting stack,
publishes `web/dist`, and invalidates CloudFront. The component workflow remains available through
manual dispatch.
