This is a bonus blog post to [Django with AWS Lambda](https://blog.vadymkhodak.com/series/django-with-aws-lambda) series. If you are a Python developer and you need to create AWS resources but you don't want to learn [Terraform](https://blog.vadymkhodak.com/deploying-a-django-project-on-aws-lambda-using-serverless-part-3) or use [AWS Management Console](https://blog.vadymkhodak.com/deploy-django-app-on-aws-lambda-using-serverless-part-2) this blog post is for you. 

## Boto3 Introduction

We will use [Boto3 - the AWS SDK for Python](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html). Boto3 makes it easy to integrate your Python application, library, or script with AWS services including Amazon S3, Amazon EC2, Amazon DynamoDB, and more.

Boto3 has two levels of APIs:
- [Client (or "low-level") APIs](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/clients.html) provide one-to-one mappings to the underlying HTTP API operations.
- [Resource APIs](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/resources.html) hide explicit network calls but instead provide resource objects and collections to access attributes and perform actions.

## Let's start codding
First, we need to install [`boto3` python library](https://pypi.org/project/boto3/):
```bash
pip install boto3
```

> I used version `1.18.40` of `boto3` which was the latest version on the day of writing this post. It is always better to use the latest version of `boto3` as the AWS team is actively working on this library.

Second (optional), we can install [`python-dotenv` python library](https://pypi.org/project/python-dotenv/) to read environment variables from `.env` file:
```bash
pip install python-dotenv
```

> This step is optional, but I do recommend using environment variables for any sensitive or configurable parameters like passwords, AWS credentials, and such.

Third (if you decided to use environment variables), we should create `.env` file with the following variables:

```
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION_NAME=

DEFAULT_VPC_ID=
DB_INSTANCE_IDENTIFIER=
RDS_DB_NAME=
RDS_USERNAME=
RDS_PASSWORD=
S3_BUCKET_NAME=
```

> You can find your DEFAULT_VPC_ID using [AWS Management Console](https://console.aws.amazon.com/vpc/home?region=us-east-1#vpcs:)

Fourth, we need to create Python file where we will write our code to create all the necessary AWS resources for deploying a Django project on AWS Lambda.

```bash
touch django_aws_resources.py
```

## Using [Boto3 - the AWS SDK for Python](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html)

First, we need to import all libraries we are going to use, load the environment variables, and set up some helpful variables.


```python
import json # to dump Python object with S3 bucket policy to JSON string
import os  # to get the necessary environment variables  
import time  # to wait until AWS RDS instance will be created
from datetime import datetime  # to generate a unique timestamp for unique CallerReference

import boto3
from dotenv import load_dotenv

load_dotenv()

S3_BUCKET_NAME = os.environ["S3_BUCKET_NAME"]
REGION_NAME = os.getenv("AWS_REGION_NAME") or "us-east-1"
```

Second, we should create a [SecurityGroup](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.ServiceResource.create_security_group) and add [inbound](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.SecurityGroup.authorize_ingress) and [outbound](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.SecurityGroup.authorize_egress) rules:

```python
ec2_resource = boto3.resource("ec2", region_name=REGION_NAME)

security_group = ec2_resource.create_security_group(
    Description="sg-for-lambdas",
    GroupName="django-rds-security-group",
    VpcId=os.environ["DEFAULT_VPC_ID"],
    TagSpecifications=[
        {
            "ResourceType": "security-group",
            "Tags": [
                {"Key": "Name", "Value": "django-demo-rds-security-group"},
            ],
        },
    ],
    DryRun=False,
)

_ = security_group.authorize_egress(
    DryRun=False,
    IpPermissions=[
        {
            "FromPort": 0,
            "IpProtocol": "-1",
            "IpRanges": [],
            "Ipv6Ranges": [
                {"CidrIpv6": "::/0", "Description": "allow all (demo only)"},
            ],
            "PrefixListIds": [],
            "ToPort": 0,
        },
    ],
    TagSpecifications=[
        {
            "ResourceType": "security-group-rule",
            "Tags": [
                {"Key": "Name", "Value": "egress rule"},
            ],
        },
    ],
)

_ = security_group.authorize_ingress(
    DryRun=False,
    IpPermissions=[
        {
            "FromPort": 0,
            "IpProtocol": "-1",
            "IpRanges": [
                {"CidrIp": "0.0.0.0/0", "Description": "allow all (demo only)"},
            ],
            "Ipv6Ranges": [
                {"CidrIpv6": "::/0", "Description": "allow all (demo only)"},
            ],
            "PrefixListIds": [],
            "ToPort": 0,
        },
    ],
    TagSpecifications=[
        {
            "ResourceType": "security-group-rule",
            "Tags": [
                {"Key": "Name", "Value": "ingress rule"},
            ],
        },
    ],
)
```

Third, we need to create an [RDS instance](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/rds.html#RDS.Client.create_db_instance) with Postgres engine:

```python
rds_client = boto3.client("rds", region_name=REGION_NAME)
_ = rds_client.create_db_instance(
    DBName=os.environ["RDS_DB_NAME"],
    DBInstanceIdentifier=os.environ["DB_INSTANCE_IDENTIFIER"],
    AllocatedStorage=20,
    DBInstanceClass="db.t2.micro",
    Engine="postgres",
    EngineVersion="12.5",
    MasterUsername=os.environ["RDS_USERNAME"],
    MasterUserPassword=os.environ["RDS_PASSWORD"],
    VpcSecurityGroupIds=[security_group.id],
    Tags=[{"Key": "name", "Value": "django_demo_rds"}],
)
```

Fourth, we should create an [S3 bucket](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Client.create_bucket) for static files:

```python
s3_client = boto3.client("s3", region_name=REGION_NAME)
_ = s3_client.create_bucket(
    ACL="private",
    Bucket=S3_BUCKET_NAME,
)
```

Fifth, we need to create a [CloudFront Origin Access Identity](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cloudfront.html#CloudFront.Client.create_cloud_front_origin_access_identity) and update the [S3 bucket policy](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.BucketPolicy.put) to allow a CloudFront distribution serving static files from the bucket:

```python
cloudfront_client = boto3.client("cloudfront", region_name=REGION_NAME)

response = cloudfront_client.create_cloud_front_origin_access_identity(
    CloudFrontOriginAccessIdentityConfig={
        "CallerReference": str(datetime.utcnow().timestamp()),
        "Comment": f'access-identity-{S3_BUCKET_NAME}.s3.amazonaws.com"',
    }
)
origin_access_identity_id = response["CloudFrontOriginAccessIdentity"]["Id"]

s3_resource = boto3.resource("s3")
bucket_policy = s3_resource.BucketPolicy(S3_BUCKET_NAME)
_ = bucket_policy.put(
    Policy=json.dumps(
        {
            "Version": "2008-10-17",
            "Statement": [
                {
                    "Sid": "1",
                    "Effect": "Allow",
                    "Principal": {
                        "AWS": f"arn:aws:iam::cloudfront:user/CloudFront "
                        f"Origin Access Identity {origin_access_identity_id}",
                    },
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{S3_BUCKET_NAME}/*",
                }
            ],
        }
    ),
)
```

Sixth, we need to create a [CloudFront Distribution](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cloudfront.html#CloudFront.Client.create_distribution) to serve static files from the S3 bucket

```python
cloudfront_distribution_response = cloudfront_client.create_distribution(
    DistributionConfig={
        "CallerReference": str(datetime.utcnow().timestamp()),
        "Origins": {
            "Quantity": 1,
            "Items": [
                {
                    "Id": S3_BUCKET_NAME,
                    "DomainName": f"{S3_BUCKET_NAME}.s3.amazonaws.com",
                    "S3OriginConfig": {
                        "OriginAccessIdentity": f"origin-access-identity/cloudfront/{origin_access_identity_id}"
                    },
                },
            ],
        },
        "Restrictions": {"GeoRestriction": {"RestrictionType": "none", "Quantity": 0}},
        "ViewerCertificate": {
            "CloudFrontDefaultCertificate": True,
        },
        "DefaultCacheBehavior": {
            "TargetOriginId": S3_BUCKET_NAME,
            "Compress": True,
            "ViewerProtocolPolicy": "allow-all",
            "AllowedMethods": {
                "Quantity": 3,
                "Items": ["GET", "HEAD", "OPTIONS"],
                "CachedMethods": {
                    "Quantity": 2,
                    "Items": ["GET", "HEAD"],
                },
            },
            "ForwardedValues": {
                "QueryString": False,
                "Cookies": {
                    "Forward": "none",
                },
            },
            "MinTTL": 0,
            "DefaultTTL": 3600,
            "MaxTTL": 86400,
        },
        "Enabled": True,
        "IsIPV6Enabled": True,
        "DefaultRootObject": "index.html",
        "Comment": "Django React static distribution",
    }
)
```

Then, we can wait until the RDS instance will be created to get the Database Host Name for Django project configurations:

```python
while True:
    rds_db_instances = rds_client.describe_db_instances(
        DBInstanceIdentifier="string",
        Filters=[
            {"Name": "db-instance-id", "Values": [os.environ["DB_INSTANCE_IDENTIFIER"]]},
        ],
        MaxRecords=20,
    )

    if rds_db_instances["DBInstances"][0].get("Endpoint"):
        db_host_name = rds_db_instances["DBInstances"][0]["Endpoint"]["Address"]
        break
    time.sleep(100)
```

Finally, we can print Database Host Name and CloudFront Distribution Domain Name to use them in Django project configurations:

```python
print(f"Database Host Name: {db_host_name}")
print(f"CloudFront Domain Name: {cloudfront_distribution_response['Distribution']['DomainName']}")

```

> Note, that this is an example of configuring AWS resources. Your production configuration can be different.


## Final Words

Today we saw one more way of how to prepare AWS infrastructure for a Django project. 

Don't forget to follow me on Twitter [@vadim_khodak](https://twitter.com/vadim_khodak) or on [LinkedIn](https://www.linkedin.com/in/vadym-khodak-0b1a05149/) so you do not miss the next posts.
