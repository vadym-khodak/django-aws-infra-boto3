import json
import os
import time
from datetime import datetime
from typing import Dict, Optional

import boto3
from dotenv import load_dotenv

load_dotenv()

REGION_NAME = os.getenv("AWS_REGION_NAME") or "us-east-1"
S3_BUCKET_NAME: str = os.environ["S3_BUCKET_NAME"]


def create_aws_resource_for_django_on_lambda(region_name: Optional[str] = "us-east-1") -> Dict[str, str]:
    """
    There is a list of the necessary resources that will be created using this function:
    - SecurityGroup for RDS
    - RDS Postgres instance
    - S3 bucket
    - CloudFront Origin Access Identity
    - S3 bucket Policy
    - CloudFront Distribution

    :returns Dict with results like this
    {
        "db_host_name": "django-aws-postgres.bavmorkee3lr.us-east-1.rds.amazonaws.com",
        "cloudfront_domain_name": d3d21a4zu45wcp.cloudfront.net,
    }

    """
    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#vpc
    ec2_resource = boto3.resource("ec2")

    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#securitygroup
    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.ServiceResource.create_security_group
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

    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.SecurityGroup.authorize_egress
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

    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.SecurityGroup.authorize_ingress
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

    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/rds.html#RDS.Client.create_db_instance
    rds_client = boto3.client("rds", region_name=region_name)
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

    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Client.create_bucket
    s3_client = boto3.client("s3", region_name=region_name)
    _ = s3_client.create_bucket(
        ACL="private",
        Bucket=S3_BUCKET_NAME,
    )

    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cloudfront.html#id93
    cloudfront_client = boto3.client("cloudfront", region_name=region_name)

    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cloudfront.html#CloudFront.Client.create_cloud_front_origin_access_identity
    response = cloudfront_client.create_cloud_front_origin_access_identity(
        CloudFrontOriginAccessIdentityConfig={
            "CallerReference": str(datetime.utcnow().timestamp()),
            "Comment": f'access-identity-{S3_BUCKET_NAME}.s3.amazonaws.com"',
        }
    )
    origin_access_identity_id = response["CloudFrontOriginAccessIdentity"]["Id"]

    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#bucketpolicy
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

    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cloudfront.html#CloudFront.Client.create_distribution
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

    return {
        "db_host_name": db_host_name,
        "cloudfront_domain_name": cloudfront_distribution_response["Distribution"]["DomainName"],
    }


if __name__ == "__main__":
    result = create_aws_resource_for_django_on_lambda(REGION_NAME)
    print(result)
