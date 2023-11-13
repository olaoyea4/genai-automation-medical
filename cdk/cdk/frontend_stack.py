import os
from aws_cdk import Stack
from constructs import Construct
from aws_cdk.aws_ecr_assets import ( DockerImageAsset, Platform)
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_ecs_patterns
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as route53_targets
from aws_cdk.aws_elasticloadbalancingv2 import (
    ApplicationProtocol, ListenerCondition, ListenerAction)
from aws_cdk.aws_elasticloadbalancingv2_actions import (
    AuthenticateCognitoAction)
from aws_cdk.aws_logs import RetentionDays
from aws_cdk.aws_ec2 import Port
from aws_cdk.aws_cloudfront_origins import (HttpOrigin)
from aws_cdk import aws_cloudfront as cf
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_apigateway as apigw
from aws_cdk import aws_s3 as s3
import random


class ChartAutomationFrontendStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, s3_bucket: s3.IBucket, api: apigw.IRestApi, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Get context values
        appCustomDomainName = self.node.try_get_context('appCustomDomainName')
        loadBalancerOriginCustomDomainName = self.node.try_get_context('loadBalancerOriginCustomDomainName')
        customDomainRoute53HostedZoneID = self.node.try_get_context('customDomainRoute53HostedZoneID')
        customDomainRoute53HostedZoneName = self.node.try_get_context('customDomainRoute53HostedZoneName')
        customDomainCertificateArn = self.node.try_get_context("customDomainCertificateArn")
        
        # generate 15 digit random string
        random_string = ''.join(random.choices('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ', k=15))

        # create cognito user pool
        

        # Retrive already existing resources
        certificate = acm.Certificate.from_certificate_arn(self, "ACMCertificate", customDomainCertificateArn )
        hosted_zone = route53.HostedZone.from_hosted_zone_attributes(self, "HostedZone",
            hosted_zone_id=customDomainRoute53HostedZoneID,
            zone_name=customDomainRoute53HostedZoneName
        )

        # Docker image build andd upload to ECR
        docker_image = DockerImageAsset(self, "DockerImage",
            directory=os.path.join(os.path.dirname(__file__), "../../frontend"),
            platform=Platform.LINUX_AMD64
        )

        # create fargate ecs cluster
        cluster = ecs.Cluster(self, "Cluster",
            enable_fargate_capacity_providers=True,
            container_insights=True
        )

        # create fargate task definition
        task_definition = ecs.FargateTaskDefinition(self, "TaskDefinition",
            cpu=512,
            memory_limit_mib=2048
        )

        # Add container to task definition
        app_container = task_definition.add_container("Container",
            image=ecs.ContainerImage.from_docker_image_asset(docker_image),
            cpu=512,
            memory_limit_mib=2048,
            logging=ecs.AwsLogDriver(stream_prefix="frontend", log_retention=RetentionDays.ONE_WEEK),
            environment={
                'BucketName': s3_bucket.bucket_name,
                'LLMAppAPIEndpoint': api.url,
                'BedrockRegion': self.region
            }
        )
        app_container.add_port_mappings(ecs.PortMapping(container_port=8501, protocol=ecs.Protocol.TCP))

        # Add policy to allow access to s3 bucket
        task_definition.add_to_task_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["s3:*"],
                resources=["*"]
            )
        )

        # Add policy to get step function execution status
        task_definition.add_to_task_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "states:DescribeExecution",
                    "states:GetActivityTask",
                    "states:GetExecutionHistory"
                ],
                resources=["*"]
            )
        )

        # Add policy to allow access to bedrock
        task_definition.add_to_task_role_policy(
            iam.PolicyStatement(
                actions = [
                    'bedrock:*'
                ],
                resources = ["*"]
            )
        )

        # ECS Fargate service
        ecs_service = aws_ecs_patterns.ApplicationLoadBalancedFargateService(self, "Service",
            cluster=cluster,
            task_definition=task_definition,
            protocol=ApplicationProtocol.HTTPS,
            certificate=certificate,
            domain_name=loadBalancerOriginCustomDomainName,
            domain_zone=hosted_zone
        )
        ecs_service.service.connections.allow_from_any_ipv4(
            port_range=Port.tcp(443),
            description="Allow HTTPS from anywhere"
            )
        
        # cloudfront distribution for ecs service
        origin = HttpOrigin(loadBalancerOriginCustomDomainName, 
            protocol_policy=cf.OriginProtocolPolicy.HTTPS_ONLY,
            custom_headers={
                 "X-Custom-Header": random_string
            }
        )

        # origin request policy for cloudfront distribution
        origin_request_policy = cf.OriginRequestPolicy(self, 'OriginRequestPolicy',
            cookie_behavior=cf.OriginRequestCookieBehavior.all(),
            header_behavior=cf.OriginRequestHeaderBehavior.all(),
            query_string_behavior=cf.OriginRequestQueryStringBehavior.all(),
            origin_request_policy_name='GenAIMedicalALBPolicy'
        )

        # cloudfront distribution
        cloudfront_distribution = cf.Distribution(self, "Distribution",
            certificate=certificate,
            domain_names=[appCustomDomainName],
            default_behavior=cf.BehaviorOptions(
                origin=origin,
                viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cf.AllowedMethods.ALLOW_ALL,
                cache_policy=cf.CachePolicy.CACHING_DISABLED,
                origin_request_policy=origin_request_policy
            )
        )

        # Add cf distribution to route53 record
        route53.ARecord(self, "ARecord",
            zone=hosted_zone,
            target=route53.RecordTarget.from_alias(route53_targets.CloudFrontTarget(cloudfront_distribution)),
            record_name=appCustomDomainName
        )
        
        # create cognito user pool and user pool client
        user_pool = cognito.UserPool(self, "UserPool",
            self_sign_up_enabled=True,
            sign_in_aliases={"email": True}
        )
        user_pool_client = user_pool.add_client("UserPoolClient",
            user_pool_client_name="alb-auth-client",
            generate_secret=True,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[cognito.OAuthScope.OPENID],
                callback_urls=[
                    "https://"+appCustomDomainName+"/oauth2/idpresponse",
                    "https://"+appCustomDomainName,
                    "https://"+cloudfront_distribution.distribution_domain_name+"/oauth2/idpresponse",
                    "https://"+cloudfront_distribution.distribution_domain_name,
                ],
                logout_urls=[
                    "https://"+appCustomDomainName,
                    "https://"+cloudfront_distribution.distribution_domain_name,
                ]
            ),
            supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO]
        )
        # cognito user pool domain
        user_pool_domain = user_pool.add_domain("UserPoolDomain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=f"genai-medical-{self.account}"
            )
        )

        ecs_service.listener.add_action(
            "cognito-auth",
            priority=1,
            conditions=[ListenerCondition.http_header("X-Custom-Header", [random_string])],
            action=AuthenticateCognitoAction(
                user_pool=user_pool,
                user_pool_client=user_pool_client,
                user_pool_domain=user_pool_domain,
                next=ListenerAction.forward(
                    target_groups=[
                        ecs_service.target_group
                    ]
                )
            )
        )

        ecs_service.listener.add_action(
            "default",
            action=ListenerAction.fixed_response(
                status_code=403,
                content_type="text/plain",
                message_body="Forbidden"
            )
        )
